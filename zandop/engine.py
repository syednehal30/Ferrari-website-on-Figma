import json
import hashlib
import os
import threading
from datetime import datetime, timedelta, timezone

from . import integrations
from .db import add_lead, connect, event, now, save_lead, set_setting, setting, uid, unpack
from .delivery import generate_delivery, quality_check
from .documents import create_document
from .policy import Blocked, live_enabled, outreach_policy, rate_for, client_rate, needs_approval
from .research import research, score_lead

LOCK = threading.RLock()
STAGES = [
    {"id": 1, "name": "Lead Finder", "short": "Discover", "description": "Source businesses and score the opportunity using explicit evidence.", "icon": "radar"},
    {"id": 2, "name": "Researcher", "short": "Research", "description": "Inspect the website, platform, catalog, performance and competitors. Produce a one-page brief.", "icon": "search"},
    {"id": 3, "name": "Outreach", "short": "Reach out", "description": "Write an individual first email with a local model. Send through personal Gmail within daily limits after prospect review.", "icon": "send"},
    {"id": 4, "name": "Sales", "short": "Qualify", "description": "Send questionnaires, manage client replies, and request an owner-edited quote starting at $500 USD.", "icon": "chat"},
    {"id": 5, "name": "CRM", "short": "Remember", "description": "Consolidate the handoff. Every agent also writes to this audit trail throughout the journey.", "icon": "database"},
    {"id": 6, "name": "Client Success", "short": "Welcome", "description": "Send a welcome PDF on booking and a project plan after call notes arrive.", "icon": "spark"},
    {"id": 7, "name": "Delivery", "short": "Create", "description": "Route to Shopify, WooCommerce, WordPress, React, React Native or the content specialist.", "icon": "code"},
    {"id": 8, "name": "Quality", "short": "Refine", "description": "Check artifacts, surface major issues and require final human release approval.", "icon": "shield"},
    {"id": 9, "name": "Finance", "short": "Invoice", "description": "Send owner-created Payoneer payment links only after exact-message approval. The owner verifies payment receipt.", "icon": "wallet"},
    {"id": 10, "name": "Reporting", "short": "Update", "description": "Send weekly progress updates while work is active and record the project close.", "icon": "chart"},
    {"id": 11, "name": "Referral", "short": "Grow", "description": "Thirty days after close, send a personal referral request with a unique tracking link.", "icon": "gift"},
]


def prepared_payload(lead, payload):
    from .db import data_dir
    payload = {**payload}
    payload.setdefault("recipient", lead["email"])
    if payload.get("attachment"):
        path = (data_dir() / payload["attachment"]).resolve()
        if not path.is_relative_to(data_dir()) or not path.is_file():
            raise Blocked("The document attachment is missing or outside the project folder.")
        payload.setdefault("attachment_sha256", hashlib.sha256(path.read_bytes()).hexdigest())
    return payload


def queue(db, lead, kind, payload, unique=None):
    payload = prepared_payload(lead, payload)
    key = unique or f"{lead['id']}:{kind}" + (":" + payload["approval_id"] if payload.get("approval_id") else "")
    row = db.execute("SELECT * FROM outbox WHERE id=?", (key,)).fetchone()
    if row:
        return dict(row)
    if needs_approval(db, kind, payload) and not payload.get("approval_id"):
        prior = db.execute("SELECT * FROM approvals WHERE lead_id=? AND kind=? AND payload=? AND status='pending'", (lead["id"], kind, json.dumps(payload))).fetchone()
        gate = unpack(prior) if prior else approval(db, lead, kind, f"Review {kind.replace('_', ' ')} for {lead['name']}", payload, fresh=True)
        return {"id": gate["id"], "status": "approval"}
    db.execute("INSERT INTO outbox(id,lead_id,kind,payload,created_at) VALUES(?,?,?,?,?)", (key, lead["id"], kind, json.dumps(payload), now()))
    event(db, lead["id"], "CRM", "action.queued", kind)
    return {"id": key, "status": "pending"}


def latest_approval(db, lead_id, kind):
    return unpack(db.execute("SELECT * FROM approvals WHERE lead_id=? AND kind=? AND status!='superseded' ORDER BY created_at DESC LIMIT 1", (lead_id, kind)).fetchone())


def approval(db, lead, kind, title, payload, fresh=False):
    row = latest_approval(db, lead["id"], kind)
    if row and not fresh:
        return row
    payload = prepared_payload(lead, payload)
    approval_id = uid("ap_")
    db.execute("INSERT INTO approvals(id,lead_id,kind,title,payload,created_at) VALUES(?,?,?,?,?,?)", (approval_id, lead["id"], kind, title, json.dumps(payload), now()))
    event(db, lead["id"], STAGES[lead["stage"] - 1]["name"], "approval.requested", title)
    return {"id": approval_id, "status": "pending", "payload": payload}


def send_status(db, lead, kind):
    row = db.execute("SELECT status FROM outbox WHERE lead_id=? AND kind=? ORDER BY created_at DESC LIMIT 1", (lead["id"], kind)).fetchone()
    return row[0] if row else None


def welcome(db, lead):
    if lead["details"].get("welcome_document"):
        return
    doc = create_document(db, lead, "welcome")
    lead["details"]["welcome_document"] = doc["id"]
    queue(db, lead, "welcome", {"subject": f"{lead['name']} × ZanDop — your next chapter", "body": f"Welcome to ZanDop. We have put together a welcome guide for your {lead['service']} project, tailored to {lead['industry'] or 'your business'}. It includes what to expect and which assets will help us get started.", "attachment": doc["path"]})
    event(db, lead["id"], "Client Success", "welcome.triggered", "Booking received; personalized PDF queued immediately")


def advance(lead_id):
    with LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        if lead["status"] in {"closed", "rejected", "suppressed"}:
            return lead
        d, stage = lead["details"], lead["stage"]
        agent = STAGES[stage - 1]["name"]
        before = (lead["stage"], lead["status"], d.get("blocker"))
        try:
            d.pop("blocker", None)
            if stage == 1:
                d["score_components"] = score_lead(lead)
                lead["score"] = d["score_components"]["total"]
                lead["stage"], lead["status"] = 2, "ready"
                event(db, lead_id, agent, "lead.scored", json.dumps(d["score_components"]))
            elif stage == 2:
                d["research"] = research(lead)
                create_document(db, lead, "brief")
                lead["stage"], lead["status"] = 3, "ready"
                event(db, lead_id, agent, "research.completed", "Evidence, limitations and brief saved")
            elif stage == 3:
                if d.get("call_booked"):
                    lead["stage"], lead["status"] = 4, "awaiting_call"
                else:
                    flaw = d.get("research", {}).get("flaw")
                    if not flaw:
                        raise Blocked("No concrete flaw was substantiated; further research is needed before outreach.")
                    if not lead["demo"]:
                        outreach_policy(db, lead)
                    message = {"subject": f"A small idea for {lead['name']}", "body": f"Hi {lead['name']} team,\n\n{flaw}\n\nWe help {lead['industry'] or 'business'} teams improve their {lead['service']} experience. Worth a quick conversation about a focused fix?\n\nZanDop\nIf this is not relevant, reply 'no thanks' and we will not follow up."}
                    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" and not lead["demo"]:
                        message = d["outreach_draft"]
                        row = queue(db, lead, "cold_email", message, unique=f"{lead['id']}:cold_email:{d['outreach_review_hash']}")
                    else:
                        row = queue(db, lead, "cold_email", message)
                    if row["status"] in {"done", "simulated"}:
                        lead["stage"], lead["status"] = 4, "awaiting_reply"
                    else:
                        lead["status"] = "queued"
            elif stage == 4:
                if not (d.get("call_notes") or d.get("requirements")):
                    lead["status"] = "awaiting_call" if d.get("call_booked") else "awaiting_requirements" if d.get("questionnaire") else "awaiting_reply"
                else:
                    rate = client_rate(lead)
                    proposal = approval(db, lead, "proposal", f"Review proposal for {lead['name']}", {"amount": rate["amount"], "currency": rate["currency"], "scope": rate["scope"],
                        "subject": f"{lead['name']} — proposed scope", "body": f"Based on our conversation: {rate['scope']}. Proposed fee: {rate['amount']/100:,.2f} {rate['currency'].upper()}. This is a proposal for discussion, not a signed contract. No legal agreement has been executed."})
                    if proposal["status"] == "rejected":
                        lead["status"] = "rejected"
                    elif proposal["status"] == "executed":
                        if (lead["demo"] and not d.get("quote")) or d.get("quote_accepted", {}).get("reference") == rate.get("reference") and rate.get("reference"):
                            from .growth import reserve_start
                            if reserve_start(db, lead):
                                welcome(db, lead)
                                lead["stage"], lead["status"] = 5, "ready"
                            else:
                                lead["status"] = "awaiting_capacity"
                        else:
                            lead["status"] = "awaiting_acceptance"
                    else:
                        lead["status"] = "approval"
            elif stage == 5:
                event(db, lead_id, "CRM", "handoff.completed", "Contact, research, messages, call notes, proposal and document versions consolidated")
                lead["stage"], lead["status"] = 6, "ready"
            elif stage == 6:
                if not (d.get("call_notes") or d.get("requirements")):
                    raise Blocked("Questionnaire answers or discovery-call notes are required for the project plan.")
                if not d.get("plan_document"):
                    doc = create_document(db, lead, "plan")
                    d["plan_document"] = doc["id"]
                    queue(db, lead, "plan", {"subject": f"{lead['name']} — your project blueprint", "body": "Here is your working project plan, shaped by your discovery answers. It outlines the delivery direction, milestones and next steps.", "attachment": doc["path"]}, unique=f"{lead['id']}:plan:{doc['id']}")
                if send_status(db, lead, "plan") in {"done", "simulated"}:
                    lead["stage"], lead["status"] = 7, "ready"
                else:
                    lead["status"] = "queued"
            elif stage == 7:
                if not d.get("delivery"):
                    d["delivery"] = generate_delivery(db, lead)
                lead["stage"], lead["status"] = 8, "ready"
            elif stage == 8:
                if not d.get("quality"):
                    d["quality"] = quality_check(lead)
                    event(db, lead_id, agent, "quality.checked", json.dumps(d["quality"]))
                gate = approval(db, lead, "final_delivery", f"Approve final delivery for {lead['name']}", {"checks": d["quality"], "files": d["delivery"]["files"], "subject": f"{lead['name']} — your approved deliverables", "body": "Your ZanDop deliverables are attached, following final human review. The handoff notes describe setup and any remaining production requirements.", "attachment": d["delivery"]["path"]})
                if gate["status"] == "executed":
                    lead["stage"], lead["status"] = 9, "ready"
                else:
                    lead["status"] = "rejected" if gate["status"] == "rejected" else "approval"
            elif stage == 9:
                from .finance import request_payload
                gate = latest_approval(db, lead_id, "invoice")
                if not gate:
                    gate = approval(db, lead, "invoice", f"Approve Payoneer request for {lead['name']}", request_payload(db, lead))
                if d.get("paid_at") and gate["status"] == "executed":
                    lead["stage"], lead["status"] = 10, "ready"
                else:
                    lead["status"] = "awaiting_payment" if gate["status"] == "executed" else "rejected" if gate["status"] == "rejected" else "approval"
            elif stage == 10:
                d["closed_at"] = now()
                d["referral_token"] = uid("ref_")
                lead["stage"], lead["status"] = 11, "scheduled"
                event(db, lead_id, agent, "project.closed", "Final delivery approved and invoice payment confirmed; referral scheduled in 30 days")
            elif stage == 11:
                due = datetime.fromisoformat(d["closed_at"]) + timedelta(days=30)
                if datetime.now(timezone.utc) >= due:
                    base = "https://example.com" if lead["demo"] else os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
                    if base:
                        link = base + "/r/" + d["referral_token"]
                    else:
                        from urllib.parse import quote
                        from .mailbox import configuration
                        address = configuration().get("email", "")
                        if not address:
                            raise Blocked("Configure the agency email for local referral links.")
                        link = "mailto:" + address + "?subject=" + quote("ZanDop introduction " + d["referral_token"])
                    row = queue(db, lead, "referral", {"subject": f"A month on, {lead['name']} — know someone we could help?", "body": f"It was a pleasure working on your {lead['service']} project. If someone in your network is planning a similar next step, we would love an introduction. Your personal referral link: {link}\n\nThanks for being part of ZanDop."})
                    if row["status"] in {"done", "simulated"}:
                        lead["status"] = "closed"
                else:
                    lead["status"] = "scheduled"
        except Blocked as exc:
            lead["status"] = "blocked"
            d["blocker"] = str(exc)
        except Exception as exc:
            lead["status"] = "blocked"
            d["blocker"] = f"{type(exc).__name__}: agent operation failed. Inspect configuration and retry."
        after = (lead["stage"], lead["status"], d.get("blocker"))
        if before != after:
            event(db, lead_id, agent, "stage.updated", f"Stage {lead['stage']} / {lead['status']}" + (f" / {d['blocker']}" if d.get("blocker") else ""))
        save_lead(db, lead)
        return lead


def decide(approval_id, decision, actor):
    with LOCK, connect() as db:
        gate = unpack(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())
        if not gate:
            raise KeyError(approval_id)
        if gate["status"] != "pending":
            raise Blocked("This decision has already been recorded.")
        if decision not in {"approve", "reject"}:
            raise Blocked("Invalid approval decision.")
        if decision == "approve" and (gate["kind"] == "sales_exception" or not gate["payload"].get("body")):
            raise Blocked("This escalation has no automatically executable action.")
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (gate["lead_id"],)).fetchone())
        if decision == "approve" and gate["kind"] in {"proposal", "invoice"}:
            from .policy import MINIMUM_PACKAGE
            if type(gate["payload"].get("amount")) is not int or gate["payload"]["amount"] < MINIMUM_PACKAGE or gate["payload"].get("currency") != "usd":
                raise Blocked("Package quotes and payment requests must be at least $500 USD.")
        if decision == "approve" and gate["kind"] == "final_delivery" and any(item["status"] == "failed" for item in gate["payload"].get("checks", [])):
            raise Blocked("Failed quality checks must be resolved before final delivery approval.")
        status = "approved" if decision == "approve" else "rejected"
        db.execute("UPDATE approvals SET status=?,decided_at=?,decided_by=? WHERE id=?", (status, now(), actor, approval_id))
        event(db, lead["id"], "Human", f"approval.{status}", f"{gate['title']} / actor={actor}")
        if status == "approved":
            queue(db, lead, gate["kind"], {**gate["payload"], "approval_id": approval_id})
        elif gate["kind"] in {"proposal", "invoice", "final_delivery"}:
            lead["status"] = "rejected"
            save_lead(db, lead)
        return {"status": status}


def drain_outbox():
    with LOCK:
        with connect() as db:
            rows = [unpack(row) for row in db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY CASE WHEN kind IN ('client_reply','questionnaire') THEN 0 ELSE 1 END, created_at LIMIT 20")]
        for row in rows:
            with connect() as db:
                lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (row["lead_id"],)).fetchone())
                if lead["details"].get("conversation_paused") and row["kind"] in {"client_reply", "questionnaire", "report", "referral"}:
                    db.execute("UPDATE outbox SET result='Client conversation paused by owner' WHERE id=?", (row["id"],))
                    continue
                if db.execute("SELECT 1 FROM suppressions WHERE email=?", (lead["email"],)).fetchone() :
                    db.execute("UPDATE outbox SET status='blocked',result=? WHERE id=?", ("Recipient suppressed", row["id"]))
                    event(db, lead["id"], "Outreach", "send.blocked", "Recipient suppressed")
                    continue
                if needs_approval(db, row["kind"], row["payload"]) or row["payload"].get("approval_id"):
                    gate = db.execute("SELECT status,payload FROM approvals WHERE id=? AND lead_id=? AND kind=?", (row["payload"].get("approval_id"), lead["id"], row["kind"])).fetchone()
                    original = {k: v for k, v in row["payload"].items() if k != "approval_id"}
                    if not gate or gate["status"] != "approved" or original != json.loads(gate["payload"]):
                        db.execute("UPDATE outbox SET status='blocked',result=? WHERE id=?", ("Missing approval or payload mismatch", row["id"]))
                        event(db, lead["id"], "Policy", "send.blocked", "Missing exact-payload approval")
                        continue
                try:
                    if row["payload"].get("recipient") != lead["email"]:
                        raise Blocked("The recipient changed after this message was prepared.")
                    if row["payload"].get("attachment"):
                        from .db import data_dir
                        path = (data_dir() / row["payload"]["attachment"]).resolve()
                        if not path.is_relative_to(data_dir()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["payload"].get("attachment_sha256"):
                            raise Blocked("The attachment changed after preparation. Prepare a new approval.")
                    if not lead["demo"]:
                        integrations.require_live()
                        if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" and row["kind"] not in {"cold_email", "sales_reply", "booking"}:
                            from .mailbox import preflight
                            preflight(lead)
                        if row["kind"] in {"cold_email", "sales_reply"}:
                            outreach_policy(db, lead)
                        if row["kind"] == "cold_email" and os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
                            from .mailbox import preflight
                            preflight(lead, outreach=True)
                            draft = lead["details"].get("outreach_draft", {})
                            if any(row["payload"].get(key) != draft.get(key) for key in ("subject", "body")):
                                raise Blocked("The queued first email differs from the reviewed draft.")
                except Blocked as exc:
                    # This is a known preflight failure, so no provider request was attempted.
                    db.execute("UPDATE outbox SET result=? WHERE id=?", (str(exc), row["id"]))
                    continue
                claimed = db.execute("UPDATE outbox SET status='sending',attempts=attempts+1 WHERE id=? AND status='pending'", (row["id"],)).rowcount
                if not claimed:
                    continue
                if row["kind"] == "cold_email" and not lead["demo"] and os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
                    db.execute("INSERT INTO outreach_attempts VALUES(?,?,?,?,?)", (uid("attempt_"), row["id"], lead["id"], lead["email"], now()))
            try:
                if lead["demo"]:
                    result, status = {"demo": True, "id": uid("demo_"), **({"provider": "payoneer"} if row["kind"] == "invoice" else {})}, "simulated"
                else:
                    action = row["kind"]
                    result = integrations.send_cold(lead, row["payload"], row["id"]) if action == "cold_email" else integrations.send_reply(lead, row["payload"], row["id"]) if action == "sales_reply" else integrations.issue_invoice(lead, row["payload"], row["id"]) if action == "invoice" else integrations.book_call(lead, row["payload"], row["id"]) if action == "booking" else integrations.send_transactional(lead, row["payload"], row["id"])
                    status = "done"
                with connect() as db:
                    db.execute("UPDATE outbox SET status=?,result=? WHERE id=?", (status, json.dumps(result), row["id"]))
                    if row["payload"].get("approval_id"):
                        db.execute("UPDATE approvals SET status='executed',result=? WHERE id=?", (json.dumps(result), row["payload"]["approval_id"]))
                    if row["kind"] == "cold_email" and os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" and not lead["demo"]:
                        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead["id"],)).fetchone())
                        if lead["stage"] <= 3:
                            lead["stage"], lead["status"] = 4, "awaiting_reply"
                            lead["details"].pop("blocker", None)
                            save_lead(db, lead)
                    if row["kind"] == "invoice":
                        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead["id"],)).fetchone())
                        lead["details"]["invoice"] = {**result, "amount": row["payload"]["amount"], "currency": row["payload"]["currency"]}
                        save_lead(db, lead)
                    if row["kind"] in {"client_reply", "questionnaire"}:
                        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead["id"],)).fetchone())
                        lead["details"]["last_reply_at"] = now()
                        lead["details"].pop("reply_due_at", None)
                        if lead["details"].get("conversation_status") in {"reply_queued", "questionnaire_queued"}:
                            lead["details"]["conversation_status"] = "replied" if row["kind"] == "client_reply" else "awaiting_answers"
                        save_lead(db, lead)
                    if row["kind"] != "booking":
                        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (uid("msg_"), lead["id"], "outbound", row["payload"].get("subject", "Invoice"), row["payload"].get("body", row["payload"].get("description", "")), status, str(result.get("id", "")), now()))
                    event(db, lead["id"], "Finance" if row["kind"] == "invoice" else "Outreach" if row["kind"] == "cold_email" else "Client Success", f"{row['kind']}.{status}", "Demo action; no external request" if lead["demo"] else "Provider accepted the request; delivery confirmation is separate")
            except Exception as exc:
                with connect() as db:
                    db.execute("UPDATE outbox SET status='uncertain',result=? WHERE id=?", (str(exc) if isinstance(exc, Blocked) else type(exc).__name__, row["id"]))
                    if row["kind"] == "cold_email" and os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
                        set_setting(db, "gmail_outreach_paused", True)
                        event(db, lead["id"], "Outreach", "gmail.paused", "A Gmail sending error occurred; inspect the message and account before resuming")
                    event(db, lead["id"], "CRM", "action.uncertain", f"{row['kind']} needs reconciliation; automatic retries disabled to avoid duplicate side effects")


def reconcile_action(action_id, outcome, evidence, provider_id=None):
    with LOCK, connect() as db:
        row = unpack(db.execute("SELECT * FROM outbox WHERE id=?", (action_id,)).fetchone())
        if not row:
            raise KeyError(action_id)
        if row["status"] != "uncertain":
            raise Blocked("Only an uncertain action can be reconciled.")
        if outcome == "not_sent":
            db.execute("UPDATE outbox SET status='pending',result=? WHERE id=?", ("Operator confirmed no provider effect: " + evidence, action_id))
        elif outcome == "sent":
            if not provider_id:
                raise Blocked("A provider receipt or invoice ID is required to confirm an action.")
            result = {"id": provider_id, "reconciled": True, **({"provider": "payoneer"} if row["kind"] == "invoice" else {})}
            db.execute("UPDATE outbox SET status='done',result=? WHERE id=?", (json.dumps(result), action_id))
            if row["kind"] == "cold_email" and os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
                lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (row["lead_id"],)).fetchone())
                if lead["stage"] <= 3:
                    lead["stage"], lead["status"] = 4, "awaiting_reply"
                    lead["details"].pop("blocker", None)
                    save_lead(db, lead)
            if row["payload"].get("approval_id"):
                db.execute("UPDATE approvals SET status='executed',result=? WHERE id=?", (json.dumps(result), row["payload"]["approval_id"]))
            if row["kind"] == "invoice":
                lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (row["lead_id"],)).fetchone())
                lead["details"]["invoice"] = {**result, "amount": row["payload"]["amount"], "currency": row["payload"]["currency"]}
                save_lead(db, lead)
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (uid("msg_"), row["lead_id"], "outbound", row["payload"].get("subject", "Reconciled action"), row["payload"].get("body", ""), "confirmed_by_operator", provider_id, now()))
        else:
            raise Blocked("Invalid reconciliation outcome.")
        event(db, row["lead_id"], "Human", "action.reconciled", f"{row['kind']} / {outcome} / {evidence}")
        return {"status": "reconciled", "outcome": outcome}


def ingest_event(db, provider, payload):
    event_id = str(payload["id"])
    key = provider + ":" + event_id
    if db.execute("SELECT 1 FROM webhooks WHERE id=?", (key,)).fetchone():
        return {"status": "duplicate"}
    kind = payload["type"]
    if provider == "relay" and payload.get("campaign_id") != os.environ.get("OUTREACH_CAMPAIGN_ID"):
        raise Blocked("Outreach events must identify the configured dedicated campaign.")
    lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (payload.get("lead_id"),)).fetchone())
    if not lead and payload.get("email"):
        lead = unpack(db.execute("SELECT * FROM leads WHERE email=? AND demo=0", (payload["email"].lower(),)).fetchone())
    if kind != "campaign.health" and not lead:
        raise Blocked("No matching lead for this event.")
    if lead and bool(lead["demo"]) != (provider == "demo"):
        raise Blocked("Demo and live events cannot cross environments.")
    data = payload.get("data", {})
    if kind == "call.booked":
        lead["details"]["client_contact"] = True
        lead["details"]["call_booked"] = {"start": data.get("start"), "provider": provider, "event_id": event_id}
        welcome(db, lead)
    elif kind == "call.notes":
        if not data.get("notes"):
            raise Blocked("Call notes cannot be empty.")
        lead["details"]["call_notes"] = str(data["notes"])[:10000]
    elif kind == "reply.received":
        body = str(data.get("body", ""))[:10000]
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (uid("msg_"), lead["id"], "inbound", str(data.get("subject", "Reply"))[:200], body, "received", event_id, now()))
        lower = body.lower()
        if any(word in lower for word in ["unsubscribe", "no thanks", "remove me", "stop emailing"]):
            db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?)", (lead["email"], "Client opt out", now()))
            lead["status"] = "suppressed"
        elif any(word in lower for word in ["discount", "contract", "guarantee", "refund", "liability", "price", "cost", "budget"]):
            approval(db, lead, "sales_exception", f"Review sales request from {lead['name']}", {"request": body, "reason": "Money, legal terms or policy exception; compose an approved response manually."})
            lead["status"] = "approval"
        else:
            link = "https://example.com/demo-booking" if lead["demo"] else os.environ.get("BOOKING_URL", "")
            if not link:
                raise Blocked("Configure BOOKING_URL before replying to prospects.")
            # Draft replies are held until the outreach provider's thread identity is configured.
            reply = {"subject": "Re: A quick conversation", "body": f"Thanks for getting back to us. We can discuss the scope on a short call. Choose a time here: {link}", "thread_id": data.get("thread_id"), "provider_lead_id": data.get("provider_lead_id")}
            if lead["demo"] or data.get("thread_id"):
                queue(db, lead, "sales_reply", reply, f"{lead['id']}:reply:{event_id}")
            else:
                lead["details"]["reply_draft"] = reply
                event(db, lead["id"], "Sales", "reply.drafted", "Provider thread mapping required before sending this reply")
    elif kind == "invoice.paid":
        invoice = lead["details"].get("invoice", {})
        if provider != "demo" or data.get("invoice_id") != invoice.get("id") or data.get("amount_paid") != invoice.get("amount") or data.get("currency", "").lower() != invoice.get("currency", "").lower():
            raise Blocked("Payment must match the approved invoice ID, amount and currency through a demo event. Real Payoneer payments require owner verification.")
        lead["details"]["paid_at"] = now()
    elif kind in {"email.bounced", "email.unsubscribed"}:
        db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?)", (lead["email"], kind, now()))
        lead["status"] = "suppressed"
        if kind == "email.bounced" and provider != "demo":
            health = setting(db, "outreach_health", {"sent": 0, "bounced": 0})
            health["bounced"] = health.get("bounced", 0) + 1
            health["checked_at"] = now()
            threshold = float(os.environ.get("MAX_BOUNCE_RATE", "0.02"))
            health["paused"] = bool(health.get("paused")) or health["bounced"] / max(1, health.get("sent", 0)) >= threshold
            set_setting(db, "outreach_health", health)
            if health["paused"]:
                set_setting(db, "pause_provider_pending", True)
    elif kind == "email.sent":
        if provider != "demo":
            health = setting(db, "outreach_health", {"sent": 0, "bounced": 0})
            health["sent"] = health.get("sent", 0) + 1
            health["checked_at"] = now()
            set_setting(db, "outreach_health", health)
    elif kind == "campaign.health":
        if provider == "demo":
            raise Blocked("Demo events cannot modify live campaign health.")
        sent, bounced = int(data.get("sent", 0)), int(data.get("bounced", 0))
        if sent < 0 or bounced < 0 or bounced > sent:
            raise Blocked("Invalid campaign counters.")
        previous = setting(db, "outreach_health", {})
        paused = bool(previous.get("paused")) or (bounced / max(1, sent)) >= float(os.environ.get("MAX_BOUNCE_RATE", "0.02"))
        set_setting(db, "outreach_health", {"sent": sent, "bounced": bounced, "paused": paused, "checked_at": now()})
        if paused:
            set_setting(db, "pause_provider_pending", True)
    else:
        raise Blocked("Unsupported event type.")
    db.execute("INSERT INTO webhooks VALUES(?,?,?)", (key, provider, now()))
    if lead:
        save_lead(db, lead)
    event(db, lead["id"] if lead else None, "CRM", kind, f"Event recorded from {provider}: {event_id}")
    return {"status": "accepted"}


def weekly_reports():
    with LOCK, connect() as db:
        for row in db.execute("SELECT * FROM leads WHERE stage BETWEEN 6 AND 10 AND status NOT IN ('rejected','suppressed','closed')"):
            lead = unpack(row)
            d = lead["details"]
            last = datetime.fromisoformat(d.get("last_report_at", lead["created_at"]))
            if datetime.now(timezone.utc) - last < timedelta(days=7):
                continue
            week = datetime.now(timezone.utc).strftime("%G-W%V")
            recent = [row[0] for row in db.execute("SELECT detail FROM events WHERE lead_id=? AND action IN ('delivery.generated','quality.checked','document.created') ORDER BY created_at DESC LIMIT 3", (lead["id"],))]
            queue(db, lead, "report", {"subject": f"{lead['name']} — your weekly ZanDop update", "body": f"This week, your project is in {STAGES[lead['stage']-1]['name']}.\n\nProgress:\n" + "\n".join(recent)[:1800] + f"\n\nNext: {STAGES[min(lead['stage'],10)]['description']}\n\nWe will keep you posted on decisions and milestones."}, f"{lead['id']}:report:{week}")
            d["last_report_at"] = now()
            save_lead(db, lead)
            event(db, lead["id"], "Reporting", "report.queued", week)


def cycle(include_demo=True):
    with connect() as db:
        ids = [row[0] for row in db.execute("SELECT id FROM leads WHERE (? OR demo=0) AND status NOT IN ('closed','rejected','suppressed')", (include_demo,))]
    for lead_id in ids:
        advance(lead_id)
    weekly_reports()
    drain_outbox()
    if live_enabled():
        with connect() as db:
            pending = setting(db, "pause_provider_pending", False)
        if pending:
            try:
                integrations.pause_campaign()
                with connect() as db:
                    set_setting(db, "pause_provider_pending", False)
                    event(db, None, "Outreach", "campaign.paused", "Provider campaign pause confirmed")
            except Exception:
                with connect() as db:
                    event(db, None, "Outreach", "campaign.pause_failed", "Local sends blocked; provider pause still needs attention")
    return {"processed": len(ids)}


def discover_configured_sources():
    if not live_enabled():
        return
    from .discovery import discover_source
    sources = json.loads(os.environ.get("ZANDOP_SOURCES", "[]"))
    with LOCK, connect() as db:
        local = os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true"
        if local:
            from .growth import periods, DAILY_TARGET
            sources = setting(db, "free_lead_sources", [])
            today = periods()[0]
            found_today = db.execute("SELECT COUNT(*) FROM leads WHERE demo=0 AND created_at>=? AND json_extract(details,'$.outreach_candidate')=1", (today,)).fetchone()[0]
        last = setting(db, "discovery_last_run")
        if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=6):
            return
        for source in sources:
            try:
                if source.get("service") not in {"ecommerce", "website", "content"}:
                    raise Blocked("Each discovery source needs a valid service.")
                records = discover_source(source["url"], source["kind"], source["service"])
                added = 0
                for record in records:
                    if not db.execute("SELECT 1 FROM leads WHERE email=? AND demo=0", (record["email"],)).fetchone():
                        if local and found_today >= DAILY_TARGET:
                            break
                        if local:
                            record["details"] = {"outreach_candidate": True, "contact_source": source["url"]}
                        add_lead(db, record)
                        added += 1
                        if local:
                            found_today += 1
                event(db, None, "Lead Finder", "discovery.completed", f"{source['kind']}: {added} new businesses with published contact details")
            except Exception as exc:
                event(db, None, "Lead Finder", "discovery.blocked", str(exc) if isinstance(exc, Blocked) else "Source could not be processed")
        if sources:
            set_setting(db, "discovery_last_run", now())


def seed_demo():
    with LOCK, connect() as db:
        if db.execute("SELECT 1 FROM leads WHERE demo=1").fetchone():
            return
        specs = [("Forma Studio", "ecommerce", "Shopify", "Home & living", 8), ("Olive & Earth", "website", "WordPress", "Sustainable skincare", 6), ("Northstar Coffee", "content", "Custom", "Specialty coffee", 4), ("Arc Athletics", "ecommerce", "WooCommerce", "Sport & wellness", 3), ("The Good Edit", "content", "WordPress", "Independent publishing", 2), ("Monogram", "website", "React", "Architecture & interiors", 1)]
        for index, (name, service, platform, industry, target) in enumerate(specs):
            lead = add_lead(db, {"name": name, "email": f"hello{index}@example.com", "website": f"https://example.com/{index}", "service": service, "platform": platform, "industry": industry, "source": ["shopify_directory", "google_maps", "linkedin", "woocommerce_directory", "job_board", "manual"][index], "details": {"revenue_score": 22-index, "traffic_score": 20-index, "visual_score": 30-index, "brand_voice": "Warm, considered, and quietly confident.", "keywords": ["thoughtful design", "everyday essentials"], "goals": "Build a clear, considered digital experience that turns interest into action."}}, demo=True)
            lead["details"]["score_components"] = score_lead(lead)
            lead["score"] = lead["details"]["score_components"]["total"]
            if target > 2:
                lead["details"]["research"] = research(lead)
                create_document(db, lead, "brief")
            if target >= 4:
                lead["details"]["client_contact"] = True
                lead["details"]["call_booked"] = {"start": "Demo booking", "provider": "demo"}
                lead["details"]["call_notes"] = "The client wants a clearer customer journey, a confident visual direction, and a simple handoff. Prioritize mobile usability and a focused first release."
                welcome(db, lead)
            if target > 6:
                doc = create_document(db, lead, "plan")
                lead["details"]["plan_document"] = doc["id"]
                lead["details"]["delivery"] = generate_delivery(db, lead)
                lead["details"]["quality"] = quality_check(lead)
                lead["stage"] = 8
                approval(db, lead, "final_delivery", f"Approve final delivery for {name}", {"checks": lead["details"]["quality"], "files": lead["details"]["delivery"]["files"], "subject": f"{name} — final deliverables", "body": "Your approved deliverables are attached.", "attachment": lead["details"]["delivery"]["path"]})
            if target == 4:
                rate = rate_for(service, True)
                approval(db, lead, "proposal", f"Review proposal for {name}", {"amount": rate["amount"], "currency": rate["currency"], "scope": "Demo editorial launch package", "subject": "Project proposal", "body": "Illustrative scope and pricing for demonstration only."})
            lead["stage"], lead["status"] = target, "approval" if target in {4,8} else "ready"
            save_lead(db, lead)
