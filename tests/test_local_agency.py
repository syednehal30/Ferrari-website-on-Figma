import json
import os
import tempfile
import unittest
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from zandop import conversations, engine, finance, mailbox
from zandop.db import add_lead, connect, data_dir, initialize, now, save_lead, set_setting, setting, unpack
from zandop.documents import create_document
from zandop.main import app
from zandop.policy import Blocked


class LocalAgencyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"ZANDOP_DATA_DIR": self.directory.name, "ZANDOP_LIVE_MODE": "false", "ZANDOP_LOCAL_WORKSPACE": "false", "ZANDOP_SEED_DEMO": "false", "ZANDOP_OPERATOR_TOKEN": "", "GMAIL_ADDRESS": "", "GMAIL_APP_PASSWORD": ""})
        self.environment.start()
        initialize()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def lead(self, demo=True):
        with connect() as db:
            lead = add_lead(db, {"name": "Client Studio", "email": "client@example.com", "service": "website", "platform": "React", "details": {"client_contact": True}}, demo=demo)
            lead["stage"] = 4
            save_lead(db, lead)
            return lead

    def read(self, lead_id):
        with connect() as db:
            return unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())

    def receive(self, lead, body, message_id="incoming-1", subject="Project details"):
        with connect() as db:
            return conversations.receive(db, {"name": lead["name"], "email": lead["email"], "subject": subject, "body": body, "message_id": message_id}, "demo" if lead["demo"] else "gmail:test", self.read(lead["id"]))

    def test_minimum_quote_and_revision_cancel_prior_authorization(self):
        lead = self.lead()
        with self.assertRaises(Blocked):
            finance.set_quote(lead["id"], 49999, "A three-page website with a contact form")
        first = finance.set_quote(lead["id"], 50000, "A three-page website with a contact form")
        engine.decide(first["id"], "approve", "owner")
        second = finance.set_quote(lead["id"], 75000, "Five pages with an additional gallery and contact form")
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM approvals WHERE id=?", (first["id"],)).fetchone()[0], "superseded")
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "cancelled")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM approvals WHERE id=?", (second["id"],)).fetchone()[0], "pending")

    def test_complete_email_discovery_to_payoneer_close_without_video_call(self):
        lead = self.lead()
        with patch("zandop.integrations.api", side_effect=AssertionError("No external API in demo")):
            self.receive(lead, "Hello, I would like to discuss a website.")
            engine.drain_outbox()
            answers = "We are a design studio. We need a home page, work gallery, and contact page for architecture clients. We have the logo and photography. React is our preferred platform and the copy will be supplied."
            self.receive(lead, answers, "answers")
            gate = finance.set_quote(lead["id"], 50000, "Build a three-page React website scaffold with responsive styles and a contact page.")
            engine.decide(gate["id"], "approve", "owner")
            engine.drain_outbox()
            engine.advance(lead["id"])
            self.assertEqual(self.read(lead["id"])["status"], "awaiting_acceptance")
            quote = self.read(lead["id"])["details"]["quote"]
            self.receive(lead, "I accept quote " + quote["reference"], "acceptance")
            for _ in range(8):
                engine.cycle()
            with connect() as db:
                gate = engine.latest_approval(db, lead["id"], "final_delivery")
            self.assertIsNotNone(gate)
            self.assertNotIn("call_booked", self.read(lead["id"])["details"])
            engine.decide(gate["id"], "approve", "owner")
            for _ in range(3):
                engine.cycle()
            finance.set_payment_link(lead["id"], "https://payoneer.com/approved-test-request")
            engine.advance(lead["id"])
            with connect() as db:
                gate = engine.latest_approval(db, lead["id"], "invoice")
            engine.decide(gate["id"], "approve", "owner")
            engine.drain_outbox()
            self.assertEqual(self.read(lead["id"])["details"]["invoice"]["provider"], "payoneer")
            self.receive(lead, "I have paid the invoice", "payment-claim")
            self.assertNotIn("paid_at", self.read(lead["id"])["details"])
            with self.assertRaises(Blocked):
                finance.confirm_payment(lead["id"], 50000, "receipt-123", False)
            with self.assertRaises(Blocked):
                finance.confirm_payment(lead["id"], 50001, "receipt-123", True)
            finance.confirm_payment(lead["id"], 50000, "receipt-123", True)
            engine.cycle()
            engine.cycle()
            self.assertEqual(self.read(lead["id"])["stage"], 11)
            with self.assertRaises(Blocked):
                finance.confirm_payment(lead["id"], 50000, "receipt-123", True)

    def test_financial_documents_and_changed_attachments_cannot_auto_send(self):
        lead = self.lead()
        lead["details"]["call_notes"] = "The requested budget is $700 and they want an initial deposit."
        with connect() as db:
            document = create_document(db, lead, "plan")
            result = engine.queue(db, lead, "plan", {"subject": "Project direction", "body": "Here is the project direction.", "attachment": document["path"]})
        self.assertEqual(result["status"], "approval")
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
        engine.decide(result["id"], "approve", "owner")
        with (data_dir() / document["path"]).open("ab") as output:
            output.write(b"changed after approval")
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertIn("attachment changed", db.execute("SELECT result FROM outbox").fetchone()[0].lower())

    def test_questionnaire_replay_scope_change_and_opt_out(self):
        lead = self.lead()
        self.receive(lead, "Please help us with our new website.")
        self.assertEqual(self.receive(lead, "Please help us with our new website.")["status"], "duplicate")
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE kind='questionnaire'").fetchone()[0], 1)
        finance.set_quote(lead["id"], 50000, "A clear three-page website with responsive styling.")
        self.receive(lead, "Can you add a membership portal?", "change")
        with connect() as db:
            self.assertIsNotNone(engine.latest_approval(db, lead["id"], "sales_exception"))
        self.receive(lead, "Please stop emailing me", "opt-out")
        engine.drain_outbox()
        self.assertEqual(self.read(lead["id"])["status"], "suppressed")
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox WHERE kind='client_reply'").fetchone()[0], "blocked")

    def test_client_pause_holds_already_queued_replies(self):
        lead = self.lead()
        self.receive(lead, "What is the project status?")
        with connect() as db:
            lead = self.read(lead["id"])
            lead["details"]["conversation_paused"] = True
            save_lead(db, lead)
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE direction='outbound'").fetchone()[0], 0)

    def test_payoneer_link_rejects_spoofed_hosts(self):
        for link in ["http://payoneer.com/a", "https://payoneer.com.evil.example/a", "https://payoneer.com@evil.example/a", "https://evil.example/a", "https://payoneer.com:444/a"]:
            with self.subTest(link=link), self.assertRaises(Blocked):
                finance.payoneer_url(link)
        self.assertEqual(finance.payoneer_url("https://login.payoneer.com/a"), "https://login.payoneer.com/a")

    def test_gmail_parser_ignores_auto_replies_and_quoted_original(self):
        message = EmailMessage()
        message["From"] = "Client <client@example.com>"
        message["To"] = "agency@gmail.com"
        message["Subject"] = "Hello"
        message["Message-ID"] = "<test-1@example.com>"
        message.set_content("Here are my answers.\nOn Thursday, Agency wrote:\n> Invoice $900")
        parsed = mailbox.parse_message(message.as_bytes(), "agency@gmail.com")
        self.assertEqual(parsed["body"], "Here are my answers.")
        message["Auto-Submitted"] = "auto-replied"
        self.assertIsNone(mailbox.parse_message(message.as_bytes(), "agency@gmail.com"))

    def test_gmail_poll_is_deduplicated_and_does_not_mark_read(self):
        config = {"email": "agency@gmail.com", "label": "ZanDop", "password": "test-only"}
        message = EmailMessage()
        message["From"] = "Client <client@example.com>"
        message["Subject"] = "Website enquiry"
        message["Message-ID"] = "<new-client@example.com>"
        message.set_content("Hello, we need a new website for our studio.")
        raw = message.as_bytes()
        connection = MagicMock()
        connection.response.side_effect = lambda key: (key, [b"1" if key == "UIDVALIDITY" else b"12"])
        def uid(command, *args):
            if command == "search":
                return "OK", [b"11"]
            if args[-1] == "(RFC822.SIZE)":
                return "OK", [f"1 (UID 11 RFC822.SIZE {len(raw)})".encode()]
            self.assertEqual(args[-1], "(BODY.PEEK[])")
            return "OK", [(b"1", raw)]
        connection.uid.side_effect = uid
        with connect() as db:
            set_setting(db, "gmail_cursor:" + mailbox.account_key(config), {"validity": 1, "last_uid": 10})
        with patch("zandop.mailbox.live_enabled", return_value=True), patch("zandop.mailbox.require_configuration", return_value=config), patch("zandop.mailbox.public_status", return_value={"verified": True}), patch("zandop.mailbox.imap_connection", return_value=connection):
            self.assertEqual(mailbox.poll()["processed"], 1)
            self.assertEqual(mailbox.poll()["processed"], 0)
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            self.assertEqual(setting(db, "gmail_cursor:" + mailbox.account_key(config))["last_uid"], 11)

    def test_smtp_uncertain_send_does_not_repeat(self):
        lead = self.lead(False)
        with connect() as db:
            engine.queue(db, lead, "client_reply", {"subject": "Project update", "body": "Your project is being reviewed."})
            set_setting(db, "automation_enabled", True)
        config = {"email": "agency@gmail.com", "password": "test-only"}
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.send_message.side_effect = TimeoutError("response lost")
        with patch.dict(os.environ, {"ZANDOP_LOCAL_WORKSPACE": "true"}), patch("zandop.mailbox.preflight", return_value=config), patch("zandop.mailbox.smtplib.SMTP_SSL", return_value=smtp):
            engine.drain_outbox()
            engine.drain_outbox()
        self.assertEqual(smtp.send_message.call_count, 1)
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "uncertain")

    def test_local_bootstrap_and_finance_api_require_operator_session(self):
        token = "test-operator-token-longer-than-thirty-two-characters"
        with patch.dict(os.environ, {"ZANDOP_LOCAL_WORKSPACE": "true", "ZANDOP_OPERATOR_TOKEN": token, "ZANDOP_LOCAL_BOOTSTRAP": "test-bootstrap"}), TestClient(app) as client:
            self.assertEqual(client.get("/api/state").status_code, 401)
            self.assertEqual(client.get("/local/session?code=wrong").status_code, 401)
            self.assertEqual(client.get("/local/session?code=test-bootstrap").status_code, 200)
            self.assertEqual(client.get("/api/state").json()["mode"], "paused")
            self.assertEqual(client.post("/api/local/automation", json={"enabled": True}).status_code, 409)
            lead = self.lead()
            self.assertEqual(client.post(f"/api/leads/{lead['id']}/quote", json={"amount": 49999, "scope": "A three-page responsive website"}).status_code, 422)
            self.assertEqual(client.post(f"/api/leads/{lead['id']}/quote", headers={"Origin": "https://untrusted.example"}, json={"amount": 50000, "scope": "A three-page responsive website"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
