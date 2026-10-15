import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from zandop import engine, integrations
from zandop.db import add_lead, connect, data_dir, initialize, now, save_lead, set_setting, unpack
from zandop.delivery import products_from_csv
from zandop.documents import create_document
from zandop.main import app
from zandop.policy import Blocked, outreach_policy, rate_for
from zandop.research import score_lead


class AgencyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"ZANDOP_DATA_DIR": self.temp.name, "ZANDOP_LIVE_MODE": "false", "ZANDOP_SEED_DEMO": "false", "ZANDOP_OPERATOR_TOKEN": ""})
        self.env.start()
        initialize()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def lead(self, demo=True, service="ecommerce"):
        with connect() as db:
            return add_lead(db, {"name": "Test Studio", "email": "client@example.com", "service": service, "platform": "Shopify", "industry": "Design", "website": "https://example.com", "source": "manual", "details": {"revenue_score": 22, "traffic_score": 21, "visual_score": 27, "brand_voice": "Warm and clear", "keywords": ["design"]}}, demo)

    def read_lead(self, id):
        with connect() as db:
            return unpack(db.execute("SELECT * FROM leads WHERE id=?", (id,)).fetchone())

    def get_gate(self, id, kind):
        with connect() as db:
            return unpack(db.execute("SELECT * FROM approvals WHERE lead_id=? AND kind=?", (id, kind)).fetchone())

    def event(self, id, kind, data, event_id=None, provider="demo"):
        with connect() as db:
            return engine.ingest_event(db, provider, {"id": event_id or kind, "lead_id": id, "type": kind, "data": data})

    def test_complete_demo_journey_obeys_each_gate_and_never_uses_network(self):
        lead = self.lead()
        id = lead["id"]
        with patch("zandop.integrations.api", side_effect=AssertionError("Demo must not contact providers")):
            for _ in range(5):
                engine.cycle()
            self.assertEqual(self.read_lead(id)["stage"], 4)
            self.assertEqual(self.read_lead(id)["status"], "awaiting_reply")
            self.event(id, "call.booked", {"start": now()})
            self.event(id, "call.notes", {"notes": "Create a considered store with a small catalog and mobile-first customer journey."})
            for _ in range(3):
                engine.cycle()
            gate = self.get_gate(id, "proposal")
            self.assertEqual(gate["status"], "pending")
            self.assertEqual(self.read_lead(id)["stage"], 4)
            engine.decide(gate["id"], "approve", "test human")
            for _ in range(9):
                engine.cycle()
            gate = self.get_gate(id, "final_delivery")
            self.assertEqual(gate["status"], "pending")
            self.assertEqual(self.read_lead(id)["stage"], 8)
            checks = self.read_lead(id)["details"]["quality"]
            self.assertTrue(any(c["check"] == "Responsive layout / 375px" and c["status"] == "passed" for c in checks), checks)
            engine.decide(gate["id"], "approve", "test human")
            for _ in range(3):
                engine.cycle()
            invoice_gate = self.get_gate(id, "invoice")
            self.assertEqual(invoice_gate["status"], "pending")
            self.assertNotIn("invoice", self.read_lead(id)["details"])
            engine.decide(invoice_gate["id"], "approve", "test human")
            engine.cycle()
            engine.cycle()
            self.assertEqual(self.read_lead(id)["status"], "awaiting_payment")
            invoice = self.read_lead(id)["details"]["invoice"]
            self.event(id, "invoice.paid", {"invoice_id": invoice["id"], "amount_paid": invoice["amount"], "currency": invoice["currency"]})
            engine.cycle()
            engine.cycle()
            self.assertEqual(self.read_lead(id)["stage"], 11)
            engine.cycle()
            with connect() as db:
                self.assertIsNone(db.execute("SELECT id FROM outbox WHERE kind='referral'").fetchone())
                lead = self.read_lead(id)
                lead["details"]["closed_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
                save_lead(db, lead)
            engine.cycle()
            engine.cycle()
            self.assertEqual(self.read_lead(id)["status"], "closed")
            with connect() as db:
                kinds = [row[0] for row in db.execute("SELECT kind FROM documents")]
                self.assertIn("welcome", kinds)
                self.assertIn("plan", kinds)
                self.assertIn("brief", kinds)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE kind='referral'").fetchone()[0], 1)
                self.assertGreater(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 20)

    def test_booking_is_immediate_idempotent_and_documents_are_real_pdf(self):
        lead = self.lead()
        first = self.event(lead["id"], "call.booked", {"start": now()}, "same-booking")
        duplicate = self.event(lead["id"], "call.booked", {"start": now()}, "same-booking")
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(duplicate["status"], "duplicate")
        with connect() as db:
            docs = list(db.execute("SELECT * FROM documents"))
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["kind"], "welcome")
            content = (data_dir() / docs[0]["path"]).read_bytes()
            self.assertTrue(content.startswith(b"%PDF-"))
            self.assertGreater(len(content), 5000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE kind='welcome'").fetchone()[0], 1)

    def test_approval_cannot_be_replayed_or_mutated(self):
        lead = self.lead()
        with connect() as db:
            gate = engine.approval(db, lead, "invoice", "Issue invoice", {"amount": 50000, "currency": "usd", "description": "Approved scope", "body": "Approved payment request"})
        engine.decide(gate["id"], "approve", "human")
        with self.assertRaises(Blocked):
            engine.decide(gate["id"], "approve", "human")
        with connect() as db:
            row = unpack(db.execute("SELECT * FROM outbox").fetchone())
            row["payload"]["amount"] = 999999
            db.execute("UPDATE outbox SET payload=?", (json.dumps(row["payload"]),))
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "blocked")
        self.assertNotIn("invoice", self.read_lead(lead["id"])["details"])

    def test_invoice_effect_without_approval_is_blocked(self):
        lead = self.lead()
        with connect() as db:
            engine.queue(db, lead, "invoice", {"amount": 100, "currency": "usd"})
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM approvals").fetchone()[0], "pending")

    def test_wrong_payment_and_demo_live_crossing_are_rejected(self):
        lead = self.lead()
        with connect() as db:
            lead["details"]["invoice"] = {"id": "inv_expected", "amount": 100, "currency": "usd"}
            save_lead(db, lead)
        with self.assertRaises(Blocked):
            self.event(lead["id"], "invoice.paid", {"invoice_id": "inv_wrong", "amount_paid": 100, "currency": "usd"})
        with self.assertRaises(Blocked):
            self.event(lead["id"], "call.booked", {}, provider="calcom")
        self.assertNotIn("paid_at", self.read_lead(lead["id"])["details"])

    def test_failed_quality_checks_prevent_release(self):
        lead = self.lead()
        with connect() as db:
            gate = engine.approval(db, lead, "final_delivery", "Release", {"body": "Ready to deliver", "checks": [{"status": "failed", "check": "Broken link"}]})
        with self.assertRaises(Blocked):
            engine.decide(gate["id"], "approve", "human")

    def test_personal_or_primary_domain_cannot_send(self):
        lead = self.lead(False)
        env = {"ZANDOP_LIVE_MODE": "true", "AGENCY_PRIMARY_DOMAIN": "zandop.example", "PERSONAL_EMAIL_DOMAINS": "personal.example", "OUTREACH_SENDER": "me@personal.example", "OUTREACH_DOMAIN": "personal.example", "OUTREACH_WARMED_AT": now(), "OUTREACH_CAMPAIGN_ID": "campaign"}
        with patch.dict(os.environ, env), connect() as db:
            set_setting(db, "outreach_health", {"sent": 100, "bounced": 0, "checked_at": now()})
            with self.assertRaisesRegex(Blocked, "secondary"):
                outreach_policy(db, lead)
            os.environ["OUTREACH_DOMAIN"] = "zandop.example"
            os.environ["OUTREACH_SENDER"] = "agency@zandop.example"
            with self.assertRaisesRegex(Blocked, "secondary"):
                outreach_policy(db, lead)
            os.environ["OUTREACH_DOMAIN"] = "hello-zandop.example"
            os.environ["OUTREACH_SENDER"] = "team@hello-zandop.example"
            outreach_policy(db, lead)

    def test_bounce_threshold_pauses_and_suppresses(self):
        lead = self.lead(False)
        with patch.dict(os.environ, {"OUTREACH_CAMPAIGN_ID": "campaign"}), connect() as db:
            set_setting(db, "outreach_health", {"sent": 50, "bounced": 0, "checked_at": now()})
            engine.ingest_event(db, "relay", {"id": "bounce", "campaign_id": "campaign", "type": "email.bounced", "lead_id": lead["id"], "data": {}})
            health = json.loads(db.execute("SELECT value FROM settings WHERE key='outreach_health'").fetchone()[0])
            self.assertTrue(health["paused"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='pause_provider_pending'").fetchone()[0], "true")

    def test_mixed_campaign_senders_are_forbidden(self):
        with patch.dict(os.environ, {"OUTREACH_SENDER": "team@secondary.example"}):
            integrations.verify_campaign_senders(["team@secondary.example"])
            with self.assertRaises(Blocked):
                integrations.verify_campaign_senders(["team@secondary.example", "owner@gmail.com"])

    def test_unsubscribe_cancels_queued_cold_email(self):
        lead = self.lead()
        with connect() as db:
            engine.queue(db, lead, "cold_email", {"subject": "hello", "body": "hello"})
        self.event(lead["id"], "reply.received", {"body": "No thanks, remove me"})
        engine.drain_outbox()
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "blocked")

    def test_unknown_revenue_and_traffic_do_not_receive_invented_points(self):
        lead = self.lead()
        lead["details"] = {}
        score = score_lead(lead)
        self.assertEqual(score["revenue"], 0)
        self.assertEqual(score["traffic"], 0)
        with patch.dict(os.environ, {"ZANDOP_RATE_CARD": "{}"}):
            with self.assertRaises(Blocked):
                rate_for("ecommerce")

    def test_public_fetch_rejects_private_targets(self):
        for url in ["http://127.0.0.1", "http://169.254.169.254", "http://localhost", "file:///etc/passwd", "https://user:pass@example.com", "http://[::1]"]:
            with self.subTest(url=url), self.assertRaises(Blocked):
                integrations.public_url(url)

    def test_invalid_product_csv_is_rejected(self):
        for text in ["", "title,price\nBad,-1", "title,price\nBad,nan", "title,price\nBad,inf", "title,price\nBad,1.234"]:
            with self.subTest(text=text), self.assertRaises(Blocked):
                products_from_csv(text)
        self.assertEqual(len(products_from_csv("title,price\nGood,12.99")), 1)

    def test_uncertain_provider_effect_is_not_retried(self):
        lead = self.lead(False)
        with connect() as db:
            engine.queue(db, lead, "welcome", {"subject": "hello", "body": "hello"})
        with patch.dict(os.environ, {"ZANDOP_LIVE_MODE": "true"}), patch("zandop.integrations.send_transactional", side_effect=Blocked("Provider timed out")) as sender:
            engine.drain_outbox()
            engine.drain_outbox()
            self.assertEqual(sender.call_count, 1)
        with connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "uncertain")

    def test_weekly_reports_do_not_duplicate(self):
        lead = self.lead()
        lead["stage"] = 7
        lead["details"]["last_report_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        with connect() as db:
            save_lead(db, lead)
        engine.weekly_reports()
        engine.weekly_reports()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE kind='report'").fetchone()[0], 1)

    def test_uncertain_invoice_reconciliation_preserves_amount(self):
        lead = self.lead(False)
        with connect() as db:
            gate = engine.approval(db, lead, "invoice", "Approved invoice", {"amount": 55000, "currency": "usd", "description": "Fixed scope", "body": "Approved payment request"})
        engine.decide(gate["id"], "approve", "human")
        with connect() as db:
            db.execute("UPDATE outbox SET status='uncertain' WHERE lead_id=?", (lead["id"],))
            action_id = db.execute("SELECT id FROM outbox WHERE lead_id=?", (lead["id"],)).fetchone()[0]
        with self.assertRaises(Blocked):
            engine.reconcile_action(action_id, "sent", "Checked provider dashboard")
        engine.reconcile_action(action_id, "sent", "Matched exact invoice in provider dashboard", "inv_confirmed")
        invoice = self.read_lead(lead["id"])["details"]["invoice"]
        self.assertEqual(invoice["id"], "inv_confirmed")
        self.assertEqual(invoice["amount"], 55000)
        self.assertEqual(self.get_gate(lead["id"], "invoice")["status"], "executed")

    def test_api_operator_auth_and_webhook_signature(self):
        with patch.dict(os.environ, {"ZANDOP_OPERATOR_TOKEN": "test-operator-token", "AUTOMATION_WEBHOOK_SECRET": "signing-secret", "OUTREACH_CAMPAIGN_ID": "campaign"}), TestClient(app) as client:
            self.assertEqual(client.get("/api/state").status_code, 401)
            self.assertEqual(client.get("/api/state", headers={"Authorization": "Bearer test-operator-token"}).status_code, 200)
            payload = json.dumps({"id": "health-1", "type": "campaign.health", "campaign_id": "campaign", "data": {"sent": 100, "bounced": 1}}).encode()
            self.assertEqual(client.post("/webhooks/relay", content=payload).status_code, 401)
            sig = hmac.new(b"signing-secret", payload, hashlib.sha256).hexdigest()
            response = client.post("/webhooks/relay", content=payload, headers={"x-zandop-signature": sig})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(client.post("/webhooks/relay", content=payload, headers={"x-zandop-signature": sig}).json()["status"], "duplicate")

    def test_timestamped_signature_rejects_stale_and_tampered_events(self):
        body, secret = b'{"id":"evt"}', "secret"
        timestamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        self.assertTrue(integrations.verify_signature(body, f"t={timestamp},v1={digest}", secret, True))
        self.assertFalse(integrations.verify_signature(body + b"x", f"t={timestamp},v1={digest}", secret, True))
        self.assertFalse(integrations.verify_signature(body, f"t=1,v1={digest}", secret, True))


if __name__ == "__main__":
    unittest.main()
