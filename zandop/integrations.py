"""Provider adapters. Network effects run only through the durable outbox."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from .policy import Blocked, require_live


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise Blocked(f"Configure {name} in environment settings.")
    return value


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise Blocked("Research URLs must be public HTTP(S) URLs on standard ports.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise Blocked("The website hostname could not be resolved.")
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise Blocked("Private, local, and reserved network destinations are forbidden.")
    return url


def fetch_public(url):
    # Retain TLS verification. Revalidate each redirect; cap redirects and body size.
    # Production deployment must additionally enforce public-only network egress to defeat DNS rebinding.
    with httpx.Client(timeout=15, trust_env=True) as client:
        for _ in range(5):
            public_url(url)
            with client.stream("GET", url, headers={"User-Agent": "ZanDopResearch/1.0"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise Blocked("Research response exceeds the 2 MB limit.")
                return bytes(content).decode("utf-8", errors="replace"), str(response.url)
    raise Blocked("Too many website redirects.")


def api(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=25, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    except httpx.HTTPStatusError as exc:
        # Do not log request URLs (Smartlead uses query authentication), response bodies, or credentials.
        raise Blocked(f"Provider returned HTTP {exc.response.status_code}; inspect the provider dashboard.") from None
    except (httpx.HTTPError, ValueError):
        raise Blocked("Provider response was unavailable or invalid; reconcile before retrying.") from None


def send_cold(lead, payload, key):
    require_live()
    campaign = required("OUTREACH_CAMPAIGN_ID")
    provider = os.environ.get("OUTREACH_PROVIDER", "instantly")
    variables = {"company_name": lead["name"], "email_body": payload["body"], "email_subject": payload["subject"]}
    if provider == "instantly":
        config = api("GET", f"https://api.instantly.ai/api/v2/campaigns/{campaign}", headers={"Authorization": f"Bearer {required('INSTANTLY_API_KEY')}"})
        verify_campaign_senders(config.get("email_list", []))
        return api("POST", "https://api.instantly.ai/api/v2/leads", headers={"Authorization": f"Bearer {required('INSTANTLY_API_KEY')}"},
                   json={"email": lead["email"], "company_name": lead["name"], "campaign": campaign,
                         "custom_variables": variables, "skip_if_in_workspace": True})
    if provider == "smartlead":
        accounts = api("GET", f"https://server.smartlead.ai/api/v1/campaigns/{campaign}/email-accounts", params={"api_key": required("SMARTLEAD_API_KEY")})
        if not isinstance(accounts, list):
            raise Blocked("Could not verify the campaign sending accounts.")
        verify_campaign_senders([account.get("from_email", "") for account in accounts])
        return api("POST", f"https://server.smartlead.ai/api/v1/campaigns/{campaign}/leads",
                   params={"api_key": required("SMARTLEAD_API_KEY")},
                   json={"lead_list": [{"email": lead["email"], "company_name": lead["name"], "custom_fields": variables}],
                         "settings": {"ignore_global_block_list": False, "ignore_unsubscribe_list": False, "ignore_duplicate_leads_in_other_campaign": False}})
    raise Blocked("OUTREACH_PROVIDER must be instantly or smartlead.")


def verify_campaign_senders(senders):
    expected = required("OUTREACH_SENDER").lower()
    if not senders or not isinstance(senders, list) or any(not isinstance(sender, str) or sender.lower() != expected for sender in senders):
        raise Blocked("Use a dedicated campaign containing only the verified secondary-domain sender.")


def send_reply(lead, payload, key):
    require_live()
    if not payload.get("thread_id"):
        raise Blocked("An outreach provider thread ID is required to reply.")
    if os.environ.get("OUTREACH_PROVIDER", "instantly") == "instantly":
        return api("POST", "https://api.instantly.ai/api/v2/emails/reply", headers={"Authorization": f"Bearer {required('INSTANTLY_API_KEY')}"},
                   json={"reply_to_uuid": payload["thread_id"], "eaccount": required("OUTREACH_SENDER"), "subject": payload["subject"], "body": {"text": payload["body"]}})
    if not payload.get("provider_lead_id"):
        raise Blocked("Smartlead replies require the provider lead ID from the reply event.")
    return api("POST", f"https://server.smartlead.ai/api/v1/campaigns/{required('OUTREACH_CAMPAIGN_ID')}/reply-email-thread", params={"api_key": required("SMARTLEAD_API_KEY")},
               json={"email_body": payload["body"], "reply_message_id": payload["thread_id"], "lead_id": payload["provider_lead_id"]})


def pause_campaign():
    require_live()
    campaign = required("OUTREACH_CAMPAIGN_ID")
    if os.environ.get("OUTREACH_PROVIDER", "instantly") == "instantly":
        return api("POST", f"https://api.instantly.ai/api/v2/campaigns/{campaign}/pause", headers={"Authorization": f"Bearer {required('INSTANTLY_API_KEY')}"})
    return api("POST", f"https://server.smartlead.ai/api/v1/campaigns/{campaign}/status", params={"api_key": required("SMARTLEAD_API_KEY")}, json={"status": "PAUSED"})


def send_transactional(lead, payload, key):
    require_live()
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
        from .mailbox import send
        return send(lead, payload, key)
    sender = required("CLIENT_EMAIL_FROM")
    if sender.split("@")[-1].strip("> ").lower() != required("AGENCY_PRIMARY_DOMAIN").lower():
        raise Blocked("Client correspondence must use the configured agency domain.")
    message = {"from": sender, "to": [lead["email"]], "subject": payload["subject"], "text": payload["body"]}
    if payload.get("attachment"):
        from .db import data_dir
        path = (data_dir() / payload["attachment"]).resolve()
        if not path.is_relative_to(data_dir()) or not path.is_file():
            raise Blocked("Invalid document attachment.")
        message["attachments"] = [{"filename": path.name, "content": base64.b64encode(path.read_bytes()).decode()}]
    return api("POST", "https://api.resend.com/emails", json=message,
               headers={"Authorization": f"Bearer {required('RESEND_API_KEY')}", "Idempotency-Key": key})


def issue_invoice(lead, payload, key):
    require_live()
    from .finance import payoneer_url
    payoneer_url(payload["payment_url"])
    result = send_transactional(lead, payload, key)
    return {"id": result["id"], "provider": "payoneer", "status": "request_sent", "payment_url": payload["payment_url"]}


def book_call(lead, payload, key):
    require_live()
    if os.environ.get("CALENDAR_PROVIDER", "calcom") != "calcom":
        raise Blocked("Calendly uses the configured scheduling link and signed booking webhook. Direct booking is implemented for Cal.com.")
    return api("POST", "https://api.cal.com/v2/bookings", headers={"Authorization": f"Bearer {required('CALCOM_API_KEY')}", "cal-api-version": "2024-08-13"},
               json={"eventTypeId": int(required("CALCOM_EVENT_TYPE_ID")), "start": payload["start"],
                     "attendee": {"name": lead["name"], "email": lead["email"], "timeZone": payload["timezone"], "language": "en"},
                     "metadata": {"zandop_lead": lead["id"], "idempotency_key": key}})


def discover_places(query):
    require_live()
    response = api("POST", "https://places.googleapis.com/v1/places:searchText", headers={"X-Goog-Api-Key": required("GOOGLE_PLACES_API_KEY"), "X-Goog-FieldMask": "places.id,places.displayName,places.websiteUri,places.formattedAddress"}, json={"textQuery": query, "pageSize": 20})
    return [{"name": p.get("displayName", {}).get("text", ""), "website": p.get("websiteUri", ""), "source": "google_maps", "source_id": p["id"], "address": p.get("formattedAddress", "")} for p in response.get("places", [])]


def generate_json(system, prompt):
    require_live()
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
        from .db import connect, setting
        with connect() as db:
            model = setting(db, "ollama_model", "")
        if not model:
            raise Blocked("For content drafting, install Ollama locally, download a model, and enter its name in Local setup. No paid AI API is required.")
        try:
            response = httpx.post("http://127.0.0.1:11434/api/chat", timeout=120, trust_env=False,
                json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "format": "json", "stream": False})
            response.raise_for_status()
            return json.loads(response.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError):
            raise Blocked("The local Ollama model could not produce a valid draft. Check that Ollama and your selected model are running.") from None
    base = required("MODEL_BASE_URL").rstrip("/")
    if not base.startswith("https://"):
        raise Blocked("The model gateway must use HTTPS.")
    result = api("POST", base + "/chat/completions", headers={"Authorization": f"Bearer {required('MODEL_API_KEY')}"},
                 json={"model": required("MODEL_NAME"), "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "temperature": 0.3})
    try:
        return json.loads(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError):
        raise Blocked("Model response did not match the JSON contract.")


def verify_signature(body, signature, secret, timestamped=False):
    if not signature or not secret:
        return False
    if timestamped:
        try:
            fields = {}
            for field in signature.split(","):
                k, v = field.split("=", 1)
                fields.setdefault(k, []).append(v)
            timestamp = fields["t"][0]
            if abs(time.time() - int(timestamp)) > 300:
                return False
            expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            return any(hmac.compare_digest(expected, value) for value in fields.get("v1", []))
        except (ValueError, KeyError):
            return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))
