import os
import re
from datetime import datetime, timezone


class Blocked(Exception):
    """An action requires configuration, evidence, or a human decision."""


def live_enabled():
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
        from .db import connect, setting
        with connect() as db:
            return bool(setting(db, "automation_enabled", False))
    return os.environ.get("ZANDOP_LIVE_MODE", "false").lower() == "true"


MINIMUM_PACKAGE = 50000  # USD cents; no floating point money.


def sensitive_text(text):
    """Conservative document routing, in addition to explicit financial action gates."""
    return bool(re.search(r"[$€£]|\b(?:usd|eur|gbp|pkr|dollars?|invoice|payments?|payoneer|stripe|refunds?|discounts?|deposits?|prices?|pricing|fees?|costs?|budgets?|contracts?|agreements?|signatures?|liability|guarantee|legal)\b", str(text), re.I))


def needs_approval(db, kind, payload):
    if kind in {"proposal", "invoice", "final_delivery", "financial_reply", "legal_document", "custom_reply"}:
        return True
    if any(key in payload for key in ("amount", "payment_url", "price", "fee")):
        return True
    if sensitive_text(payload.get("subject", "") + " " + payload.get("body", "")):
        return True
    if payload.get("attachment"):
        row = db.execute("SELECT p.requires_approval FROM documents d LEFT JOIN document_policy p ON p.document_id=d.id WHERE d.path=?", (payload["attachment"],)).fetchone()
        # Older/unclassified attachments also need a human review.
        return not row or row[0] is None or bool(row[0])
    return False


def client_rate(lead):
    quote = lead["details"].get("quote")
    if not quote and lead["demo"]:
        quote = rate_for(lead["service"], True)
    if not quote:
        raise Blocked("Review the client's requirements and set a manual quote of at least $500 USD.")
    if type(quote.get("amount")) is not int or quote["amount"] < MINIMUM_PACKAGE or quote.get("currency") != "usd" or not quote.get("scope"):
        raise Blocked("Every package requires a manual scope and a price of at least $500 USD.")
    return quote


def require_live():
    if not live_enabled():
        raise Blocked("Live actions are disabled. Configure providers and explicitly enable ZANDOP_LIVE_MODE.")


def outreach_policy(db, lead):
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
        require_live()
        from .growth import outreach_policy as local_policy
        return local_policy(db, lead)
    from .db import setting
    require_live()
    sender = os.environ.get("OUTREACH_SENDER", "").lower().strip()
    secondary = os.environ.get("OUTREACH_DOMAIN", "").lower().strip()
    personal = os.environ.get("PERSONAL_EMAIL_DOMAINS", "").lower().split(",")
    primary = os.environ.get("AGENCY_PRIMARY_DOMAIN", "").lower().strip()
    if not primary or not personal or not any(x.strip() for x in personal):
        raise Blocked("Declare agency and personal email domains before enabling outreach.")
    prohibited = {x.strip() for x in personal if x.strip()} | {primary, "gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "icloud.com", "proton.me"}
    if not secondary or not sender or sender.count("@") != 1 or sender.split("@")[1] != secondary or secondary in prohibited:
        raise Blocked("Outreach requires a dedicated secondary domain; personal and primary domains are forbidden.")
    try:
        verified = datetime.fromisoformat(os.environ.get("OUTREACH_WARMED_AT", "").replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - verified).total_seconds()
        if age < 0 or age > 30 * 86400:
            raise ValueError()
    except (ValueError, TypeError):
        raise Blocked("A warmed-domain verification dated within the last 30 days is required.")
    if db.execute("SELECT 1 FROM suppressions WHERE email=?", (lead["email"],)).fetchone():
        raise Blocked("Recipient is suppressed.")
    health = setting(db, "outreach_health", {})
    if health.get("paused"):
        raise Blocked("Outreach is paused because the bounce threshold was reached.")
    try:
        health_age = (datetime.now(timezone.utc) - datetime.fromisoformat(health["checked_at"])).total_seconds()
        if not 0 <= health_age <= 3600:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise Blocked("Fresh campaign health telemetry is required (within one hour).")
    if not os.environ.get("OUTREACH_CAMPAIGN_ID"):
        raise Blocked("Configure a dedicated campaign with the generated email_body custom field.")


def rate_card():
    import json
    try:
        card = json.loads(os.environ.get("ZANDOP_RATE_CARD", "{}"))
    except json.JSONDecodeError:
        raise Blocked("ZANDOP_RATE_CARD must be valid JSON.")
    return card


def rate_for(service, demo=False):
    if demo:
        return {"amount": {"ecommerce": 480000, "website": 320000, "content": 120000}[service], "currency": "usd", "scope": "Illustrative demo scope"}
    rate = rate_card().get(service)
    if not rate or type(rate.get("amount")) is not int or rate["amount"] <= 0 or rate.get("currency", "").lower() not in {"usd", "gbp", "eur", "cad", "aud", "pkr"} or not rate.get("scope"):
        raise Blocked("A fixed rate, currency, and scope must be configured for this service.")
    return rate
