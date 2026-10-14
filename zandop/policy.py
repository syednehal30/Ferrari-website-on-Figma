import os
from datetime import datetime, timezone


class Blocked(Exception):
    """An action requires configuration, evidence, or a human decision."""


def live_enabled():
    return os.environ.get("ZANDOP_LIVE_MODE", "false").lower() == "true"


def require_live():
    if not live_enabled():
        raise Blocked("Live actions are disabled. Configure providers and explicitly enable ZANDOP_LIVE_MODE.")


def outreach_policy(db, lead):
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
