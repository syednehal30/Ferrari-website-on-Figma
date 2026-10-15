"""Client email assistant. Bounded, factual replies require no paid AI service."""
import re
from datetime import datetime, timedelta, timezone

from .db import add_lead, event, now, save_lead, uid, unpack
from .policy import Blocked, sensitive_text


def questionnaire(lead):
    common = ["What does your business do, and who is the project for?", "What result would make this project successful?", "Which pages, features or deliverables are essential?", "Do you have a preferred launch date and timezone?", "Which brand assets, copy and examples can you share? Do not email passwords."]
    specific = {
        "ecommerce": ["Shopify or WooCommerce, and is this a new store or rebuild?", "How many products and variants? Can you provide a product CSV?", "Which regions, shipping options and integrations does the store need?"],
        "website": ["Which platform do you prefer: WordPress, React, React Native, or a custom website?", "Do you need forms, accounts, integrations, or an existing site migrated?", "Who will maintain the site, and which devices matter most?"],
        "content": ["What formats and quantities do you need: pages, articles, or product copy?", "Which SEO keywords, audience and brand-voice examples should guide the work?", "Which factual sources and claims have you approved?"],
    }
    questions = common + specific[lead["service"]]
    return "Thanks for reaching out to ZanDop. Please reply to these questions so we can shape the right scope for you:\n\n" + "\n\n".join(f"{i + 1}. {question}" for i, question in enumerate(questions)) + "\n\nWe can handle discovery by email. If a video call would help, share your availability and timezone; the agency owner will join the call.\n\nZanDop client assistant"


def request_questionnaire(db, lead):
    from . import engine
    if not lead["demo"] and not lead["details"].get("client_contact"):
        raise Blocked("Confirm this client expects to hear from you before sending a questionnaire through Gmail.")
    row = engine.queue(db, lead, "questionnaire", {"subject": f"{lead['name']} — a few questions to shape your project", "body": questionnaire(lead)})
    lead["details"].setdefault("questionnaire", {})["queued_at"] = now()
    lead["details"]["conversation_status"] = "questionnaire_queued"
    event(db, lead["id"], "Sales", "questionnaire.queued", "Service-specific discovery questions queued")
    return row


def receive(db, message, channel, lead=None):
    from . import engine
    message_id = message["message_id"]
    key = channel + ":" + message_id
    if db.execute("SELECT 1 FROM webhooks WHERE id=?", (key,)).fetchone():
        return {"status": "duplicate"}
    demo = channel == "demo"
    if not lead:
        lead = unpack(db.execute("SELECT * FROM leads WHERE email=? AND demo=?", (message["email"].lower(), int(demo))).fetchone())
    if lead and bool(lead["demo"]) != demo:
        raise Blocked("Demo messages cannot affect real clients.")
    if not lead:
        if not channel.startswith("gmail:"):
            raise Blocked("Register this client before adding a conversation.")
        lower = message["body"].lower()
        service = "ecommerce" if any(x in lower for x in ["shopify", "woocommerce", "store", "products"]) else "content" if any(x in lower for x in ["writing", "articles", "seo content"]) else "website"
        lead = add_lead(db, {"name": message["name"][:120], "email": message["email"], "service": service, "source": "manual", "details": {"client_contact": True, "channel": "gmail"}})
        lead["stage"] = 4
    d = lead["details"]
    d.update({"client_contact": True, "channel": "gmail" if not demo else "demo", "last_message_id": message_id,
              "last_client_message_at": now(), "reply_due_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
    body = message["body"].strip()[:10000]
    db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (uid("msg_"), lead["id"], "inbound", message["subject"], body, "received", message_id, now()))
    db.execute("INSERT INTO webhooks VALUES(?,?,?)", (key, channel, now()))
    event(db, lead["id"], "CRM", "client.message_received", "New client email recorded")
    lower = body.lower()
    response = None
    if any(word in lower for word in ["unsubscribe", "no thanks", "remove me", "stop emailing", "do not contact"]):
        db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?)", (lead["email"], "Client asked to stop", now()))
        lead["status"] = "suppressed"
        d["conversation_status"] = "suppressed"
    elif lead["status"] == "suppressed" or d.get("conversation_paused"):
        d["conversation_status"] = "paused"
    else:
        quote = d.get("quote", {})
        reference = quote.get("reference", "")
        accepted = reference and re.search(r"\bi accept quote\s+" + re.escape(reference) + r"\b", body, re.I)
        if accepted:
            gate = db.execute("SELECT status FROM approvals WHERE lead_id=? AND kind='proposal' AND json_extract(payload,'$.reference')=? ORDER BY created_at DESC LIMIT 1", (lead["id"], reference)).fetchone()
            if gate and gate[0] == "executed":
                d["quote_accepted"] = {"reference": reference, "at": now(), "message_id": message_id}
                response = "Thank you. I've recorded your confirmation of the agreed scope. We'll move on to the project plan and keep you updated on progress."
                d["conversation_status"] = "scope_confirmed"
                engine.welcome(db, lead)
                event(db, lead["id"], "Sales", "quote.accepted", reference)
            else:
                response = "Thank you. The agency owner still needs to complete the review. We'll follow up once that decision is recorded."
        elif sensitive_text(body) or re.search(r"\b(how much|rates?|packages?|quotes?|paid|cheaper|expensive)\b", lower):
            engine.approval(db, lead, "sales_exception", f"Review client request from {lead['name']}", {"request": body, "reason": "Review the financial or legal request. Edit the client quote or compose a financial reply in the inbox; each send needs your approval."}, fresh=True)
            response = "Thanks for the details. I've passed this request to the agency owner for review. We'll follow up after a decision, and I won't commit to a change before that review."
            d["conversation_status"] = "needs_owner"
        elif re.search(r"\b(add|extra|additional|change the scope|change scope|new feature|instead|expand)\b", lower) and d.get("quote"):
            d.setdefault("change_requests", []).append({"at": now(), "body": body})
            d["change_requests"] = d["change_requests"][-30:]
            engine.approval(db, lead, "sales_exception", f"Scope change requested by {lead['name']}", {"request": body, "reason": "Decide whether this changes the agreed scope, timing or manual price before committing."}, fresh=True)
            response = "I've recorded the requested change and sent it to the agency owner to check against the agreed scope. We'll confirm the next steps after that review."
            d["conversation_status"] = "needs_owner"
        elif re.search(r"\b(progress|update|status|how is|how's)\b", lower):
            stages = {4: "discovery and scope review", 5: "organizing the project brief", 6: "preparing the project plan", 7: "preparing the delivery draft", 8: "quality review", 9: "the final project administration", 10: "the handoff", 11: "the completed-project follow-up"}
            response = "Your project is currently in " + stages.get(lead["stage"], "discovery") + ". "
            response += "The agency owner has a decision to review before the next step." if lead["status"] in {"approval", "blocked", "rejected"} else "We'll send another update as the next milestone is completed."
        elif re.search(r"\b(call|meet|zoom|video|availability|schedule)\b", lower):
            d.setdefault("call_requests", []).append({"at": now(), "body": body})
            d["call_requests"] = d["call_requests"][-20:]
            response = "The agency owner will handle the video call. Please send two suitable times and your timezone; we'll confirm the slot with you."
            d["conversation_status"] = "call_requested"
            event(db, lead["id"], "Sales", "call.requested", "Owner needs to confirm a video-call time")
        elif not d.get("questionnaire"):
            request_questionnaire(db, lead)
            if len(body) >= 80:
                d["requirements"] = body
        elif not d.get("questionnaire", {}).get("received_at") and len(body) >= 80:
            d["requirements"] = body
            d["questionnaire"]["received_at"] = now()
            d["questionnaire"]["answers"] = body
            d["goals"] = body[:1200]
            response = "Thank you — I've saved your answers in the project brief. The agency owner will review the requirements and send the proposed scope after checking it. If any must-have details are missing, you can reply here."
            d["conversation_status"] = "requirements_received"
            event(db, lead["id"], "Sales", "requirements.received", "Questionnaire answers ready for the owner's manual scope and price")
        elif re.search(r"\b(logo|assets|files|photos|images|brand|copy|csv|attachment)\b", lower):
            d.setdefault("asset_notes", []).append(body)
            d["asset_notes"] = d["asset_notes"][-20:]
            response = "I've recorded your note about the project assets. Please share accessible file links and any usage instructions here. Email attachments need the owner to review and import them; don't send passwords."
        elif re.search(r"\b(thanks|thank you|great|sounds good)\b", lower):
            response = "You're welcome. I'll keep the project history up to date and send the next update when there's progress or a decision to make."
        else:
            d.setdefault("client_notes", []).append({"at": now(), "body": body})
            d["client_notes"] = d["client_notes"][-30:]
            response = "I've saved your message with the project. Could you identify the page, feature or deliverable it concerns, and the result you're looking for? That will help us give you a specific answer."
            d["conversation_status"] = "clarification_requested"
        if response:
            # A real human conversation is not a high-volume autoresponder loop.
            since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            count = db.execute("SELECT COUNT(*) FROM outbox WHERE lead_id=? AND kind='client_reply' AND created_at>?", (lead["id"], since)).fetchone()[0]
            if count >= 8:
                d["conversation_status"] = "needs_owner"
                event(db, lead["id"], "Client Success", "reply.rate_limited", "Eight automatic replies within one hour; inspect the conversation before continuing")
            else:
                engine.queue(db, lead, "client_reply", {"subject": "Re: " + message["subject"].removeprefix("Re: "), "body": response + "\n\nZanDop client assistant", "in_reply_to": message_id}, unique=f"{lead['id']}:client_reply:{uid()}")
                if d.get("conversation_status") not in {"needs_owner", "call_requested", "requirements_received"}:
                    d["conversation_status"] = "reply_queued"
    save_lead(db, lead)
    return {"status": "received", "lead_id": lead["id"]}
