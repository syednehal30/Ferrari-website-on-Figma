import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from zandop import conversations, engine, free_leads, growth, mailbox
from zandop.db import add_lead, connect, initialize, now, save_lead, set_setting, setting, uid, unpack
from zandop.main import app
from zandop.policy import Blocked, outreach_policy


class GrowthTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "ZANDOP_DATA_DIR": self.directory.name, "ZANDOP_LOCAL_WORKSPACE": "true",
            "ZANDOP_SEED_DEMO": "false", "ZANDOP_OPERATOR_TOKEN": "",
            "GMAIL_ADDRESS": "owner@gmail.com", "GMAIL_APP_PASSWORD": "test-only"})
        self.environment.start()
        initialize()
        self.config = mailbox.configuration(True)
        with connect() as db:
            for key, value in {"automation_enabled": True, "gmail_outreach_enabled": True,
                               "gmail_verified": mailbox.account_key(self.config), "gmail_daily_limit": 10,
                               "gmail_bounce_checked_at": now(), "gmail_bounce_checked_account": mailbox.account_key(self.config)}.items():
                set_setting(db, key, value)

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def prospect(self, name="Cedar"):
        draft = {"subject": name + " mobile page", "body": "The page is missing a mobile viewport declaration. Would a clearer mobile experience be useful for your customers?\nZanDop"}
        with connect() as db:
            lead = add_lead(db, {"name": name, "email": name.lower()+"@example.com", "service": "website", "details": {
                "research": {"flaw": "The page is missing a mobile viewport declaration."},
                "outreach_draft": draft, "outreach_review_hash": growth.draft_hash(draft), "outreach_candidate": True}})
            lead["stage"] = 3
            save_lead(db, lead)
            return lead

    def attempt(self, lead):
        with connect() as db:
            db.execute("INSERT INTO outreach_attempts VALUES(?,?,?,?,?)", (uid(), uid(), lead["id"], lead["email"], now()))

    def test_personal_gmail_send_uses_reviewed_text_and_daily_limit(self):
        first, second = self.prospect(), self.prospect("Birch")
        with connect() as db:
            set_setting(db, "gmail_daily_limit", 1)
            outreach_policy(db, first)  # Personal Gmail is explicitly allowed in local mode.
        engine.advance(first["id"])
        engine.advance(second["id"])
        with patch("zandop.mailbox.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            engine.drain_outbox()
            engine.drain_outbox()
            sender = smtp.return_value.__enter__.return_value
            self.assertEqual(sender.send_message.call_count, 1)
            sent = sender.send_message.call_args.args[0]
            self.assertEqual(sent["From"], "owner@gmail.com")
            self.assertEqual(sent["Subject"], first["details"]["outreach_draft"]["subject"])
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outreach_attempts").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE status='done'").fetchone()[0], 1)
            self.assertIn("limit", db.execute("SELECT result FROM outbox WHERE status='pending'").fetchone()[0])

    def test_draft_change_and_stale_monitor_block_sends(self):
        lead = self.prospect()
        with connect() as db:
            set_setting(db, "gmail_bounce_checked_at", (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat())
            with self.assertRaisesRegex(Blocked, "five minutes"):
                outreach_policy(db, lead)
            set_setting(db, "gmail_bounce_checked_at", now())
            lead["details"]["outreach_draft"]["body"] += "Changed text."
            save_lead(db, lead)
            with self.assertRaisesRegex(Blocked, "Review this prospect"):
                outreach_policy(db, lead)
        with self.assertRaisesRegex(Blocked, "draft changed"):
            growth.review(lead["id"], "0"*64)

    def test_two_starts_capacity_is_idempotent_and_active_work_carries_over(self):
        leads = [self.prospect(name) for name in ("One", "Two", "Three")]
        with connect() as db:
            for lead in leads:
                lead["details"]["quote"] = {"reference": "Q-"+lead["id"], "amount": 50000}
            self.assertTrue(growth.reserve_start(db, leads[0]))
            self.assertTrue(growth.reserve_start(db, leads[0]))
            self.assertTrue(growth.reserve_start(db, leads[1]))
            self.assertFalse(growth.reserve_start(db, leads[2]))
            self.assertEqual(growth.capacity(db)["booked_amount"], 100000)
            db.execute("UPDATE project_starts SET week_key='2000-W01'")
            self.assertFalse(growth.reserve_start(db, leads[2]), "Unfinished work still occupies capacity next week")
            leads[0]["details"]["closed_at"] = now()
            save_lead(db, leads[0])
            self.assertTrue(growth.reserve_start(db, leads[2]))

    def test_permanent_bounce_suppresses_recipient_and_pauses_outreach_once(self):
        lead = self.prospect()
        self.attempt(lead)
        raw = ("From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\r\nMessage-ID: <bounce1>\r\n"
               "MIME-Version: 1.0\r\nContent-Type: multipart/report; boundary=x; report-type=delivery-status\r\n\r\n"
               "--x\r\nContent-Type: text/plain\r\n\r\nDelivery failed.\r\n"
               "--x\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; googlemail.com\r\n\r\n"
               "Final-Recipient: rfc822; cedar@example.com\r\nAction: failed\r\nStatus: 5.1.1\r\n\r\n--x--\r\n").encode()
        with connect() as db:
            self.assertTrue(mailbox.record_bounce(db, raw))
            self.assertFalse(mailbox.record_bounce(db, raw))
            self.assertTrue(setting(db, "gmail_outreach_paused"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE action='gmail.bounced'").fetchone()[0], 1)

    def test_inbox_reads_known_prospect_reply_without_importing_personal_mail(self):
        lead = self.prospect()
        self.attempt(lead)
        key = "gmail_bounce_cursor:" + mailbox.account_key(self.config)
        with connect() as db:
            set_setting(db, key, {"validity": 1, "last_uid": 10})
            set_setting(db, "gmail_outreach_enabled", False)  # Disabling prospecting must not disable replies.
        incoming = EmailMessage()
        incoming["From"], incoming["To"], incoming["Subject"], incoming["Message-ID"] = lead["email"], "owner@gmail.com", "Website help", "<known-11>"
        incoming.set_content("Hello, yes please send the questions about the website.")
        connection = MagicMock()
        connection.select.return_value = ("OK", [])
        body_requests = []
        def imap_call(command, *args):
            if command == "search": return "OK", [b"11 12"]
            identifier, query = args
            if "HEADER.FIELDS" in query:
                address = lead["email"] if identifier == "11" else "friend@example.com"
                return "OK", [(b"header", ("From: "+address+"\r\nContent-Type: text/plain\r\n\r\n").encode())]
            body_requests.append(identifier)
            return "OK", [(b"body", incoming.as_bytes())]
        connection.uid.side_effect = imap_call
        with patch("zandop.mailbox.imap_connection", return_value=connection), patch("zandop.mailbox.mailbox_position", return_value={"validity": 1, "last_uid": 12}):
            mailbox.poll_bounces(self.config)
        self.assertEqual(body_requests, ["11"])
        with connect() as db:
            saved = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead["id"],)).fetchone())
            self.assertEqual(saved["stage"], 4)
            self.assertTrue(saved["details"]["client_contact"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 1)

    def test_public_contacts_are_not_guessed_and_imports_deduplicate(self):
        html = '<title>Cedar Furniture</title><a href="mailto:hello@cedar.test">Contact us</a>'
        with patch("zandop.free_leads.respect_robots"), patch("zandop.free_leads.fetch_public", return_value=(html, "https://cedar.test")):
            first = free_leads.inspect_sites(["https://cedar.test"], "ecommerce")
            second = free_leads.inspect_sites(["https://cedar.test"], "ecommerce")
        self.assertEqual(first["results"][0]["email"], "hello@cedar.test")
        self.assertEqual(second["results"][0]["status"], "existing")
        with patch("zandop.free_leads.respect_robots"), patch("zandop.free_leads.fetch_public", return_value=("<title>No contact</title>", "https://other.test")):
            self.assertEqual(free_leads.inspect_sites(["https://other.test"], "website")["results"][0]["status"], "needs_contact")

    def test_outreach_requires_local_model_grounded_observation_and_no_money(self):
        lead = self.prospect()
        with patch("zandop.integrations.generate_local_json", return_value=lead["details"]["outreach_draft"]):
            self.assertIn("no thanks", growth.write_outreach(lead)["body"])
        for body in ("I admire your work. "*8, lead["details"]["outreach_draft"]["body"]+" Our price is $500."):
            with patch("zandop.integrations.generate_local_json", return_value={"subject": "An idea", "body": body}), self.assertRaises(Blocked):
                growth.write_outreach(lead)

    def test_automatic_drafting_leaves_client_processing_unlocked_and_requires_review(self):
        lead = self.prospect()
        with connect() as db:
            set_setting(db, "ollama_model", "test-local-model")
            lead["details"].pop("outreach_draft")
            lead["details"].pop("outreach_review_hash")
            save_lead(db, lead)
        lock_available = []
        def model(system, prompt):
            def check_client_worker():
                acquired = engine.LOCK.acquire(timeout=0.5)
                lock_available.append(acquired)
                if acquired:
                    engine.LOCK.release()
            thread = threading.Thread(target=check_client_worker)
            thread.start()
            thread.join(timeout=1)
            return {"subject": "Your mobile experience", "body": "The page is missing a mobile viewport declaration. A clearer mobile page could help customers explore your services. Would you like to discuss it? ZanDop"}
        findings = {"platform": "WordPress", "flaw": "The page is missing a mobile viewport declaration.", "evidence": "https://cedar.test"}
        with patch("zandop.research.research", return_value=findings), patch("zandop.integrations.generate_local_json", side_effect=model) as generator:
            growth.prepare_next()
            growth.prepare_next()
            self.assertEqual(generator.call_count, 1)
        self.assertEqual(lock_available, [True])
        with connect() as db:
            updated = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead["id"],)).fetchone())
            self.assertEqual(updated["status"], "awaiting_review")
            self.assertNotIn("outreach_review_hash", updated["details"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM documents WHERE kind='brief'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_api_limits_and_enable_requires_local_model(self):
        with connect() as db:
            set_setting(db, "automation_enabled", False)
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/growth/settings", json={"market": "Furniture stores", "daily_limit": 13}).status_code, 422)
            response = client.post("/api/growth/outreach", json={"enabled": True})
            self.assertEqual(response.status_code, 409)
            self.assertIn("Ollama", response.json()["detail"])
            self.assertEqual(client.post("/api/growth/sites", json={"urls": ["https://a.test"]*13}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
