"""Manual client pricing and approved Payoneer payment requests; no payment API."""
import hashlib
from urllib.parse import urlsplit

from .db import connect, data_dir, event, now, save_lead, uid, unpack
from .documents import Book, PURPLE
from .policy import Blocked, MINIMUM_PACKAGE, client_rate


def payoneer_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        valid = parsed.scheme == "https" and (host == "payoneer.com" or host.endswith(".payoneer.com"))
        if not valid or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise ValueError()
    except ValueError:
        raise Blocked("Paste the HTTPS payment-request link created in your Payoneer account (payoneer.com).") from None
    return value


def financial_pdf(db, lead, quote, kind, payment_url=""):
    doc_id = uid("doc_")
    path = data_dir() / "documents" / (doc_id + ".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM documents WHERE lead_id=? AND kind=?", (lead["id"], kind)).fetchone()[0]
    title = "Project quote" if kind == "proposal" else "Payment request summary"
    book = Book(path, lead["name"], kind, bool(lead["demo"]))
    book.begin()
    book.text("PREPARED FOR " + lead["name"], 44, 720, 12, color=PURPLE, max_lines=2)
    book.text(title, 44, 670, 30, bold=True)
    book.text(f"USD {quote['amount'] / 100:,.2f}", 44, 610, 30, bold=True)
    book.text("Reference: " + quote.get("reference", "Demo quote"), 44, 565, 11)
    book.text("Scope", 44, 525, 16, bold=True)
    book.text(quote["scope"], 44, 495, 11, max_lines=16)
    if payment_url:
        book.text("Pay using the approved Payoneer request linked in the accompanying email.", 44, 190, 11, max_lines=3)
    book.text("Prepared for review. Sending requires the agency owner's explicit approval.\nThis document does not sign a contract or charge a payment method.", 44, 126, 10, max_lines=3)
    book.end()
    book.save()
    relative = path.relative_to(data_dir()).as_posix()
    db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (doc_id, lead["id"], kind, version, title, relative, now()))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    db.execute("INSERT INTO document_policy VALUES(?,?,1)", (doc_id, digest))
    event(db, lead["id"], "Finance", "document.created", f"{kind} PDF v{version}; approval required")
    return relative


def set_quote(lead_id, amount, scope):
    from . import engine
    if type(amount) is not int or amount < MINIMUM_PACKAGE:
        raise Blocked("The minimum package is $500 USD. Enter an amount of $500 or more.")
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        if lead["details"].get("invoice") or lead["details"].get("paid_at") or lead["stage"] >= 9:
            raise Blocked("A payment request is already in progress. Resolve it before changing the project price.")
        if db.execute("SELECT 1 FROM outbox WHERE lead_id=? AND kind IN ('proposal','invoice','plan','final_delivery') AND status IN ('sending','uncertain')", (lead_id,)).fetchone():
            raise Blocked("Reconcile the in-flight financial message before editing the quote.")
        db.execute("UPDATE approvals SET status='superseded' WHERE lead_id=? AND kind IN ('proposal','invoice','plan','final_delivery') AND status IN ('pending','approved','executed')", (lead_id,))
        db.execute("UPDATE outbox SET status='cancelled',result='Quote revised by operator' WHERE lead_id=? AND kind IN ('proposal','invoice','plan','final_delivery') AND status IN ('pending','blocked')", (lead_id,))
        quote = {"amount": amount, "currency": "usd", "scope": scope.strip(), "reference": "Q-" + uid()[:8].upper(), "edited_at": now()}
        lead["details"]["quote"] = quote
        lead["details"].pop("quote_accepted", None)
        lead["details"].pop("payoneer_url", None)
        for field in ("plan_document", "delivery", "quality"):
            lead["details"].pop(field, None)
        if lead["stage"] > 4:
            lead["stage"] = 4
        lead["status"] = "approval"
        doc = financial_pdf(db, lead, quote, "proposal")
        payload = {**quote, "subject": f"{lead['name']} — quote {quote['reference']}",
                   "body": f"Here is the scope reviewed by the ZanDop owner:\n\n{scope}\n\nTotal: USD {amount/100:,.2f}.\nReference: {quote['reference']}.\n\nTo confirm this scope, reply: I accept quote {quote['reference']}. Tell us about any changes before accepting. This is not a signed legal contract.", "attachment": doc}
        gate = engine.approval(db, lead, "proposal", f"Approve quote {quote['reference']} for {lead['name']}", payload, fresh=True)
        save_lead(db, lead)
        event(db, lead_id, "Human", "quote.edited", f"{quote['reference']} / USD {amount/100:.2f}; previous unsent approval invalidated")
        return gate


def set_payment_link(lead_id, url):
    from . import engine
    url = payoneer_url(url)
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        if lead["details"].get("invoice"):
            raise Blocked("The request was already sent. Reconcile it in Payoneer before replacing it.")
        if db.execute("SELECT 1 FROM outbox WHERE lead_id=? AND kind='invoice' AND status IN ('sending','uncertain')", (lead_id,)).fetchone():
            raise Blocked("Reconcile the financial message before changing its link.")
        db.execute("UPDATE approvals SET status='superseded' WHERE lead_id=? AND kind='invoice' AND status IN ('pending','approved')", (lead_id,))
        db.execute("UPDATE outbox SET status='cancelled' WHERE lead_id=? AND kind='invoice' AND status IN ('pending','blocked')", (lead_id,))
        lead["details"]["payoneer_url"] = url
        save_lead(db, lead)
        event(db, lead_id, "Human", "payoneer.link_saved", "Owner supplied a Payoneer request; nothing sent")
        return {"status": "saved"}


def request_payload(db, lead):
    quote = client_rate(lead)
    link = lead["details"].get("payoneer_url")
    if not link and lead["demo"]:
        link = "https://payoneer.com/demo-not-a-real-request"
    if not link:
        raise Blocked("Create the matching request in Payoneer, then add its payment link here for approval.")
    payoneer_url(link)
    doc = financial_pdf(db, lead, quote, "invoice", link)
    return {"amount": quote["amount"], "currency": "usd", "description": quote["scope"],
            "recipient": lead["email"], "payment_url": link, "provider": "payoneer",
            "subject": f"{lead['name']} — Payoneer payment request",
            "body": f"The approved project amount is USD {quote['amount']/100:,.2f}.\n\nScope: {quote['scope']}\n\nPayoneer request: {link}\n\nPlease use the request created by the ZanDop owner. We will confirm receipt after checking Payoneer.",
            "attachment": doc, "action": "Send this exact Payoneer link and summary by email. This does not create a request, charge a card, or sign a contract."}


def confirm_payment(lead_id, amount, reference, confirmed):
    from . import engine
    if not confirmed:
        raise Blocked("Confirm that you personally verified the payment in Payoneer.")
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        invoice = lead["details"].get("invoice")
        if not invoice or invoice.get("provider") != "payoneer" or amount != invoice["amount"]:
            raise Blocked("The verified payment must match the approved Payoneer request amount.")
        if lead["details"].get("paid_at"):
            raise Blocked("Payment has already been recorded.")
        lead["details"].update({"paid_at": now(), "payment_verification": {"provider": "payoneer", "amount": amount, "reference": reference, "verified_by": "workspace owner"}})
        save_lead(db, lead)
        event(db, lead_id, "Human", "payment.verified", f"Payoneer payment personally verified / USD {amount/100:.2f} / reference {reference}")
        return {"status": "confirmed"}
