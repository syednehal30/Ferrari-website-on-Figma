"""Local Gmail IMAP/SMTP. Credentials stay on the operator's Windows account."""
import base64
import ctypes
from ctypes import wintypes
import email
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, parseaddr
import hashlib
import imaplib
import json
import os
from pathlib import Path
import smtplib
import ssl
import threading

from .db import connect, data_dir, event, now, set_setting, setting, unpack
from .policy import Blocked, live_enabled, require_live

POLL_LOCK = threading.Lock()


def protect(value, decrypt=False):
    if os.name != "nt":
        raise Blocked("Saving a Gmail app password uses Windows encryption. On other systems use GMAIL_APP_PASSWORD in the process environment.")
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(value) if decrypt else value.encode()
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise Blocked("Windows could not unlock the saved Gmail app password. Reconnect Gmail from this Windows account.")
    try:
        result = ctypes.string_at(target.pbData, target.cbData)
        return result.decode() if decrypt else base64.b64encode(result).decode()
    finally:
        kernel.LocalFree(target.pbData)


def configuration(secret=False):
    path = data_dir() / "gmail.json"
    config = json.loads(path.read_text()) if path.is_file() else {}
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if os.environ.get("GMAIL_ADDRESS"):
        config["email"] = os.environ["GMAIL_ADDRESS"]
    config.setdefault("label", os.environ.get("GMAIL_LABEL", "ZanDop"))
    config["password_saved"] = bool(password or config.get("protected_password"))
    if secret:
        config["password"] = password or (protect(config["protected_password"], True) if config.get("protected_password") else "")
    config.pop("protected_password", None)
    return config


def configure(address, password, label):
    address = address.strip().lower()
    if parseaddr(address)[1] != address or "@" not in address or any(c in address + label for c in '\r\n"\\'):
        raise Blocked("Enter a valid Gmail address and a simple Gmail label name.")
    if not label or len(label) > 100 or label.lower() in {"[gmail]/spam", "[gmail]/trash"}:
        raise Blocked("Use a dedicated client label such as ZanDop.")
    path = data_dir() / "gmail.json"
    previous = json.loads(path.read_text()) if path.is_file() else {}
    encrypted = protect(password.replace(" ", "")) if password else previous.get("protected_password", "")
    if not encrypted and not os.environ.get("GMAIL_APP_PASSWORD"):
        raise Blocked("Enter a Gmail app password on your Windows computer.")
    if previous.get("email") not in {None, address} and not password:
        raise Blocked("Enter the app password for the new Gmail account.")
    config = {"email": address, "label": label, "protected_password": encrypted}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config), encoding="utf-8")
    temporary.replace(path)
    with connect() as db:
        set_setting(db, "automation_enabled", False)
        set_setting(db, "gmail_verified", False)
        event(db, None, "Human", "gmail.configured", "Client label configured; automation paused until connection test and activation")
    return public_status()


def account_key(config):
    return hashlib.sha256((config["email"] + ":" + config["label"]).encode()).hexdigest()[:24]


def require_configuration():
    config = configuration(True)
    if not config.get("email") or not config.get("password"):
        raise Blocked("Connect Gmail in Local setup with an app password, then test the connection.")
    return config


def imap_connection(config):
    connection = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20)
    try:
        connection.login(config["email"], config["password"])
        status, _ = connection.select('"' + config["label"] + '"', readonly=True)
        if status != "OK":
            raise Blocked("Create the selected label in Gmail and enable Show in IMAP, then test again.")
        return connection
    except Exception:
        try:
            connection.logout()
        except Exception:
            pass
        raise


def mailbox_position(connection):
    validity = connection.response("UIDVALIDITY")[1]
    next_uid = connection.response("UIDNEXT")[1]
    if not validity or not validity[0] or not next_uid or not next_uid[0]:
        raise Blocked("Gmail did not return a stable mailbox position.")
    return {"validity": int(validity[0]), "last_uid": int(next_uid[0]) - 1}


def test_connection():
    config = require_configuration()
    try:
        connection = imap_connection(config)
        try:
            position = mailbox_position(connection)
        finally:
            connection.logout()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(config["email"], config["password"])
            smtp.noop()
    except (OSError, imaplib.IMAP4.error, smtplib.SMTPException):
        raise Blocked("Gmail connection failed. Check the address, app password, IMAP label and internet connection. No test email was sent.") from None
    with connect() as db:
        key = "gmail_cursor:" + account_key(config)
        if not setting(db, key):
            set_setting(db, key, position)
        set_setting(db, "gmail_verified", account_key(config))
        set_setting(db, "gmail_health", {"checked_at": now(), "status": "ready", "detail": "Login verified. Only newly arriving messages in the selected label will be processed."})
        event(db, None, "CRM", "gmail.verified", "IMAP and SMTP authentication verified; no message sent")
    return public_status()


def public_status():
    config = configuration()
    with connect() as db:
        verified = bool(config.get("email")) and setting(db, "gmail_verified") == account_key(config)
        return {"email": config.get("email", ""), "label": config["label"], "password_saved": config["password_saved"],
                "verified": verified, "enabled": setting(db, "automation_enabled", False),
                "health": setting(db, "gmail_health", {}), "local_workspace": os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true",
                "poll_seconds": 60, "reply_target_seconds": 300}


def set_enabled(enabled):
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") != "true":
        raise Blocked("Open Start ZanDop Workspace.bat to connect real client email. The demo launcher cannot enable live actions.")
    if enabled and not public_status()["verified"]:
        raise Blocked("Test your Gmail connection successfully before enabling automatic replies.")
    with connect() as db:
        set_setting(db, "automation_enabled", enabled)
        event(db, None, "Human", "automation.enabled" if enabled else "automation.paused", "Client email automation; financial, legal and final delivery approvals remain mandatory")
    return public_status()


def preflight(lead):
    require_live()
    config = require_configuration()
    if not public_status()["verified"]:
        raise Blocked("Test the Gmail connection before sending client correspondence.")
    if not (lead["details"].get("client_contact") or lead["details"].get("call_booked")):
        raise Blocked("Gmail is only for existing client conversations or expected questionnaires, not cold outreach.")
    if lead["email"].lower() == config["email"].lower():
        raise Blocked("The client address must differ from the agency inbox.")
    return config


def send(lead, payload, key):
    config = preflight(lead)
    msg = EmailMessage()
    msg["From"] = config["email"]
    msg["To"] = lead["email"]
    msg["Subject"] = payload["subject"]
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = "<" + hashlib.sha256((config["email"] + key).encode()).hexdigest() + "@zandop.local>"
    msg["Auto-Submitted"] = "auto-replied"
    thread = payload.get("in_reply_to") or lead["details"].get("last_message_id")
    if thread and "\n" not in thread and "\r" not in thread and len(thread) < 500:
        msg["In-Reply-To"] = thread
        msg["References"] = thread
    msg.set_content(payload["body"])
    if payload.get("attachment"):
        path = (data_dir() / payload["attachment"]).resolve()
        if not path.is_relative_to(data_dir()) or not path.is_file() or path.stat().st_size > 15_000_000:
            raise Blocked("The attachment is missing or exceeds the local email size limit.")
        subtype = "pdf" if path.suffix == ".pdf" else "zip" if path.suffix == ".zip" else "octet-stream"
        msg.add_attachment(path.read_bytes(), maintype="application", subtype=subtype, filename=path.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as smtp:
        smtp.login(config["email"], config["password"])
        refused = smtp.send_message(msg)
        if refused:
            raise Blocked("Gmail did not accept the recipient. Inspect the action before retrying.")
    return {"id": str(msg["Message-ID"]), "provider": "gmail", "status": "accepted"}


def parse_message(raw, own_address):
    message = email.message_from_bytes(raw, policy=policy.default)
    name, address = parseaddr(message.get("From", ""))
    address = address.lower()
    automated = str(message.get("Auto-Submitted", "no")).lower() != "no"
    automated |= str(message.get("Precedence", "")).lower() in {"bulk", "list", "junk"}
    automated |= bool(message.get("List-ID")) or message.get_content_type() == "multipart/report"
    if automated or not address or address == own_address.lower() or "@" not in address or any(x in address for x in ("mailer-daemon", "postmaster@", "noreply", "no-reply")):
        return None
    body = message.get_body(preferencelist=("plain", "html")) if message.is_multipart() else message
    text = body.get_content() if body else ""
    if not isinstance(text, str):
        return None
    if body.get_content_type() == "text/html":
        from html.parser import HTMLParser
        class TextOnly(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, value):
                self.parts.append(value)
        parser = TextOnly()
        parser.feed(text)
        text = "\n".join(parser.parts)
    # Keep the latest reply, not quoted copies of our own price or questionnaire.
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or (line.startswith("On ") and line.rstrip().endswith("wrote:")) or line.strip() == "-----Original Message-----":
            break
        lines.append(line)
    return {"name": name or address.split("@")[0], "email": address, "subject": str(message.get("Subject", "Client message"))[:200],
            "body": "\n".join(lines).strip()[:10000], "message_id": str(message.get("Message-ID", ""))[:500] or hashlib.sha256(raw).hexdigest()}


def poll():
    if not live_enabled() or not POLL_LOCK.acquire(blocking=False):
        return {"processed": 0}
    connection = None
    try:
        from . import conversations, engine
        config = require_configuration()
        if not public_status()["verified"]:
            raise Blocked("Reconnect and test Gmail before polling.")
        connection = imap_connection(config)
        position = mailbox_position(connection)
        cursor_key = "gmail_cursor:" + account_key(config)
        with connect() as db:
            cursor = setting(db, cursor_key)
        if not cursor or cursor["validity"] != position["validity"]:
            with connect() as db:
                set_setting(db, "automation_enabled", False)
                set_setting(db, cursor_key, position)
            raise Blocked("The Gmail label changed identity. Review the mailbox and enable automation again; old messages were not replayed.")
        status, data = connection.uid("search", None, "UID", f"{cursor['last_uid'] + 1}:*")
        if status != "OK":
            raise Blocked("Gmail could not search new client messages.")
        ids = sorted(int(value) for value in (data[0] or b"").split() if int(value) > cursor["last_uid"])[:50]
        processed = 0
        for message_uid in ids:
            status, metadata = connection.uid("fetch", str(message_uid), "(RFC822.SIZE)")
            import re
            size_match = re.search(rb"RFC822.SIZE (\d+)", b" ".join(value for value in metadata if isinstance(value, bytes)))
            if status != "OK" or not size_match:
                raise Blocked("A Gmail message could not be inspected; it will remain pending for the next poll.")
            parsed = None
            if int(size_match[1]) <= 1_000_000:
                status, fetched = connection.uid("fetch", str(message_uid), "(BODY.PEEK[])")
                raw = next((value[1] for value in fetched if isinstance(value, tuple)), None)
                if status != "OK" or raw is None:
                    raise Blocked("A Gmail message could not be read; it will remain pending for the next poll.")
                parsed = parse_message(raw, config["email"])
            with engine.LOCK, connect() as db:
                if parsed:
                    conversations.receive(db, parsed, "gmail:" + account_key(config))
                    processed += 1
                elif int(size_match[1]) > 1_000_000:
                    event(db, None, "CRM", "mail.needs_review", f"Message UID {message_uid} exceeds 1 MB; inspect this message in Gmail")
                cursor["last_uid"] = message_uid
                set_setting(db, cursor_key, cursor)
        with connect() as db:
            set_setting(db, "gmail_health", {"checked_at": now(), "status": "connected", "detail": f"Checked client label; {processed} new messages recorded."})
        return {"processed": processed}
    except (OSError, imaplib.IMAP4.error, ValueError, Blocked) as exc:
        detail = str(exc) if isinstance(exc, Blocked) else "Gmail polling failed. Check your connection and app password in Local setup."
        with connect() as db:
            previous = setting(db, "gmail_health", {})
            set_setting(db, "gmail_health", {"checked_at": now(), "status": "error", "detail": detail})
            if previous.get("detail") != detail:
                event(db, None, "CRM", "mail.error", detail)
        return {"processed": 0, "error": detail}
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass
        POLL_LOCK.release()
