import asyncio
import csv
import hmac
import io
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import engine, integrations, finance, conversations, mailbox, growth, free_leads
from .db import add_lead, connect, data_dir, event, initialize, now, save_lead, set_setting, setting, uid, unpack
from .policy import Blocked, live_enabled


class LeadDetails(BaseModel):
    client_contact: bool = False
    outreach_candidate: bool = False
    contact_source: str = Field(default="", max_length=2000)
    revenue_score: int = Field(default=0, ge=0, le=25)
    traffic_score: int = Field(default=0, ge=0, le=25)
    visual_score: int = Field(default=0, ge=0, le=30)
    revenue_estimate: str = Field(default="Unknown", max_length=200)
    traffic_estimate: str = Field(default="Unknown", max_length=200)
    competitors: list[str] = Field(default_factory=list, max_length=3)
    goals: str = Field(default="", max_length=1200)
    brand_voice: str = Field(default="", max_length=1200)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    product_csv: str = Field(default="", max_length=200000)


class LeadCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    website: str = Field(default="", max_length=2000)
    service: Literal["ecommerce", "website", "content"]
    platform: str = Field(default="", max_length=60)
    industry: str = Field(default="", max_length=120)
    source: Literal["manual", "google_maps", "shopify_directory", "woocommerce_directory", "job_board", "linkedin"] = "manual"
    details: LeadDetails = Field(default_factory=LeadDetails)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    confirmation: str


class CallNotes(BaseModel):
    notes: str = Field(min_length=10, max_length=10000)


class Booking(BaseModel):
    start: str = Field(min_length=20, max_length=50)
    timezone: str = Field(min_length=3, max_length=80)
    client_confirmed: bool


class ImportCSV(BaseModel):
    csv_text: str = Field(max_length=500000)


class SearchPlaces(BaseModel):
    query: str = Field(min_length=3, max_length=250)


class Reconcile(BaseModel):
    action_id: str
    outcome: Literal["sent", "not_sent"]
    evidence: str = Field(min_length=15, max_length=2000)
    provider_id: str | None = Field(default=None, max_length=200)


class QuoteEdit(BaseModel):
    amount: int = Field(ge=50000, le=100000000, strict=True)
    scope: str = Field(min_length=20, max_length=1200)


class PayoneerLink(BaseModel):
    url: str = Field(min_length=20, max_length=2000)


class PaymentConfirmation(BaseModel):
    amount: int = Field(ge=50000, strict=True)
    reference: str = Field(min_length=4, max_length=150)
    confirmed: bool


class GmailConfig(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(default="", max_length=100)
    label: str = Field(default="ZanDop", min_length=1, max_length=100)


class Toggle(BaseModel):
    enabled: bool


class ClientMessage(BaseModel):
    subject: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")
    body: str = Field(min_length=2, max_length=10000)


class QuestionnaireSend(BaseModel):
    client_expects_contact: bool


class ModelSetting(BaseModel):
    model: str = Field(default="", max_length=120, pattern=r"^[a-zA-Z0-9_:./-]*$")


class FreeSource(BaseModel):
    kind: Literal["shopify_directory", "woocommerce_directory", "job_board", "linkedin"]
    url: str = Field(min_length=10, max_length=2000, pattern=r"^https?://")
    service: Literal["ecommerce", "website", "content"] = "website"


class GrowthSettings(BaseModel):
    market: str = Field(min_length=3, max_length=200)
    daily_limit: int = Field(ge=1, le=12, strict=True)
    sources: list[FreeSource] = Field(default_factory=list, max_length=10)


class OutreachToggle(BaseModel):
    enabled: bool
    reviewed_bounces: bool = False


class SiteIntake(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=12)
    service: Literal["ecommerce", "website", "content"] = "website"


class DraftReview(BaseModel):
    draft_hash: str = Field(min_length=64, max_length=64)


async def worker():
    while True:
        await asyncio.sleep(60)
        if live_enabled():
            try:
                await asyncio.to_thread(engine.discover_configured_sources)
                await asyncio.to_thread(engine.cycle, False)
                await asyncio.to_thread(growth.prepare_next)
            except Exception as exc:
                with connect() as db:
                    event(db, None, "Orchestrator", "worker.error", type(exc).__name__)


async def mail_worker():
    while True:
        await asyncio.sleep(60)
        if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" and live_enabled():
            try:
                await asyncio.to_thread(mailbox.poll)
                await asyncio.to_thread(engine.drain_outbox)
            except Exception as exc:
                with connect() as db:
                    event(db, None, "Client Success", "mail.worker_error", type(exc).__name__)


@asynccontextmanager
async def lifespan(app):
    initialize()
    if live_enabled() and len(os.environ.get("ZANDOP_OPERATOR_TOKEN", "")) < 32:
        raise RuntimeError("Live mode requires a ZANDOP_OPERATOR_TOKEN of at least 32 characters.")
    if os.environ.get("ZANDOP_SEED_DEMO", "true").lower() == "true":
        await asyncio.to_thread(engine.seed_demo)
    # A process interruption may leave an ambiguous external action. Never replay it automatically.
    with connect() as db:
        stranded = list(db.execute("SELECT lead_id,kind FROM outbox WHERE status='sending'"))
        db.execute("UPDATE outbox SET status='uncertain',result='Process interrupted; reconcile provider before retrying' WHERE status='sending'")
        for row in stranded:
            event(db, row["lead_id"], "CRM", "action.uncertain", row["kind"] + " interrupted")
    task = asyncio.create_task(worker())
    mail_task = asyncio.create_task(mail_worker())
    yield
    task.cancel()
    mail_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await mail_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ZanDop Agency OS", version="0.3.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def access_control(request: Request, call_next):
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > 1_000_000:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    token = os.environ.get("ZANDOP_OPERATOR_TOKEN", "")
    if request.url.path.startswith("/api/") and request.url.path != "/api/health" and token:
        given = request.headers.get("authorization", "").removeprefix("Bearer ") or request.cookies.get("zandop_session", "")
        if not hmac.compare_digest(given, token):
            return JSONResponse({"detail": "Operator authentication required"}, status_code=401)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin mutation denied"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Blocked)
async def blocked_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(KeyError)
async def missing_error(request, exc):
    return JSONResponse({"detail": "Record not found"}, status_code=404)


@app.exception_handler(sqlite3.IntegrityError)
async def duplicate_error(request, exc):
    return JSONResponse({"detail": "A record with this identity already exists"}, status_code=409)


@app.get("/api/health")
def health():
    with connect() as db:
        db.execute("SELECT 1")
    return {"status": "ok", "mode": workspace_mode(), "authentication_required": bool(os.environ.get("ZANDOP_OPERATOR_TOKEN"))}


def workspace_mode():
    return "live" if live_enabled() else "paused" if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" else "demo"


@app.get("/local/session")
def local_session(request: Request, code: str):
    current = os.environ.get("ZANDOP_OPERATOR_TOKEN", "")
    if current and hmac.compare_digest(request.cookies.get("zandop_session", ""), current):
        return RedirectResponse("/", status_code=303)
    expected = os.environ.get("ZANDOP_LOCAL_BOOTSTRAP", "")
    if not expected or not hmac.compare_digest(code, expected):
        raise HTTPException(401, "Reopen the workspace using its Windows launcher.")
    os.environ.pop("ZANDOP_LOCAL_BOOTSTRAP", None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("zandop_session", os.environ["ZANDOP_OPERATOR_TOKEN"], httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/session")
def session():
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie("zandop_session", os.environ.get("ZANDOP_OPERATOR_TOKEN", ""), httponly=True, samesite="strict", secure=os.environ.get("PUBLIC_BASE_URL", "").startswith("https://"), max_age=3600)
    return response


def provider_status():
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true" or not live_enabled():
        status = mailbox.public_status()
        with connect() as db:
            model = setting(db, "ollama_model", "")
        return [
            {"id": "gmail", "name": "Client email", "provider": "Gmail IMAP + SMTP", "configured": status["verified"], "requirements": [{"name": "Gmail connection tested", "present": status["verified"]}]},
            {"id": "payoneer", "name": "Payoneer", "provider": "Manual request link + explicit send approval + owner payment verification", "configured": True, "requirements": []},
            {"id": "pricing", "name": "Client pricing", "provider": "Manual quotes · minimum $500 USD", "configured": True, "requirements": []},
            {"id": "conversation", "name": "Routine conversations", "provider": "Local rule-based assistant · no AI subscription", "configured": True, "requirements": []},
            {"id": "model", "name": "Individual email drafting", "provider": "Local Ollama model · no paid API", "configured": bool(model), "requirements": [{"name": "Local model name", "present": bool(model)}]},
            {"id": "outreach", "name": "Personal Gmail outreach", "provider": "Up to 12 reviewed first emails daily · bounce auto-pause", "configured": growth.dashboard()["enabled"], "requirements": []},
        ]
    provider = os.environ.get("OUTREACH_PROVIDER", "instantly")
    definitions = [
        ("outreach", "Cold outreach", "Instantly / Smartlead", ["INSTANTLY_API_KEY" if provider == "instantly" else "SMARTLEAD_API_KEY", "OUTREACH_SENDER", "OUTREACH_DOMAIN", "OUTREACH_WARMED_AT", "OUTREACH_CAMPAIGN_ID", "AGENCY_PRIMARY_DOMAIN", "PERSONAL_EMAIL_DOMAINS", "AUTOMATION_WEBHOOK_SECRET"]),
        ("calendar", "Call scheduling", "Cal.com / Calendly", ["BOOKING_URL", "CALCOM_WEBHOOK_SECRET" if os.environ.get("CALENDAR_PROVIDER", "calcom") == "calcom" else "CALENDLY_WEBHOOK_SECRET"]),
        ("payoneer", "Payoneer payment requests", "Owner-created link; approval before sending; owner verifies receipt", []),
        ("email", "Client correspondence", "Resend", ["RESEND_API_KEY", "CLIENT_EMAIL_FROM", "AGENCY_PRIMARY_DOMAIN"]),
        ("places", "Business discovery", "Google Places", ["GOOGLE_PLACES_API_KEY"]),
        ("model", "Content generation", "OpenAI-compatible API", ["MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME"]),
        ("pricing", "Fixed rate card", "Agency policy", ["ZANDOP_RATE_CARD"]),
    ]
    return [{"id": id, "name": name, "provider": label, "configured": all(os.environ.get(key) for key in keys), "requirements": [{"name": key, "present": bool(os.environ.get(key))} for key in keys]} for id, name, label, keys in definitions]


@app.get("/api/state")
def state():
    with connect() as db:
        leads = [unpack(row) for row in db.execute("SELECT * FROM leads ORDER BY score DESC, created_at DESC")]
        approvals = [unpack(row) for row in db.execute("SELECT a.*,l.name AS client,l.demo FROM approvals a JOIN leads l ON a.lead_id=l.id ORDER BY a.created_at DESC")]
        documents = [dict(row) for row in db.execute("SELECT d.*,l.name AS client,l.demo,l.service,l.industry FROM documents d JOIN leads l ON d.lead_id=l.id ORDER BY d.created_at DESC")]
        events = [dict(row) for row in db.execute("SELECT e.*,l.name AS client FROM events e LEFT JOIN leads l ON e.lead_id=l.id ORDER BY e.created_at DESC LIMIT 100")]
        actions = [unpack(row) for row in db.execute("SELECT id,lead_id,kind,status,result,created_at FROM outbox WHERE status IN ('pending','blocked','uncertain') ORDER BY created_at DESC")]
        return {"leads": leads, "approvals": approvals, "documents": documents, "events": events, "stages": engine.STAGES,
                "providers": provider_status(), "outbox": actions, "mode": workspace_mode(), "outreach_health": setting(db, "outreach_health", {}), "updated_at": now(),
                "mailbox": mailbox.public_status(), "ollama_model": setting(db, "ollama_model", ""), "minimum_package": 50000, "growth": growth.dashboard()}


@app.post("/api/leads", status_code=201)
def create_lead(body: LeadCreate):
    with connect() as db:
        record = body.model_dump()
        record["details"]["outreach_candidate"] = not body.details.client_contact
        lead = add_lead(db, record)
        if body.details.client_contact:
            lead["stage"] = 4
            save_lead(db, lead)
            conversations.request_questionnaire(db, lead)
            save_lead(db, lead)
        return lead


@app.post("/api/leads/{lead_id}/quote")
def edit_quote(lead_id: str, body: QuoteEdit):
    return finance.set_quote(lead_id, body.amount, body.scope)


@app.post("/api/leads/{lead_id}/payoneer")
def payment_link(lead_id: str, body: PayoneerLink):
    return finance.set_payment_link(lead_id, body.url)


@app.post("/api/leads/{lead_id}/confirm-payment")
def payment_received(lead_id: str, body: PaymentConfirmation):
    return finance.confirm_payment(lead_id, body.amount, body.reference, body.confirmed)


@app.post("/api/leads/{lead_id}/questionnaire")
def send_questionnaire(lead_id: str, body: QuestionnaireSend):
    if not body.client_expects_contact:
        raise Blocked("Confirm that the client expects this questionnaire. Use Lead finder to prepare a first-contact email.")
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        lead["details"]["client_contact"] = True
        if lead["stage"] < 4:
            lead["stage"] = 4
        result = conversations.request_questionnaire(db, lead)
        save_lead(db, lead)
    engine.drain_outbox()
    return result


@app.post("/api/leads/{lead_id}/conversation-pause")
def pause_conversation(lead_id: str, body: Toggle):
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        lead["details"]["conversation_paused"] = body.enabled
        save_lead(db, lead)
        event(db, lead_id, "Human", "conversation.paused" if body.enabled else "conversation.resumed", "Client-specific reply control changed")
    return {"status": "saved"}


@app.post("/api/leads/{lead_id}/reply")
def compose_reply(lead_id: str, body: ClientMessage):
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        # Operator-authored financial messages still require the separate explicit approval.
        result = engine.queue(db, lead, "custom_reply", body.model_dump(), unique=uid("reply_"))
        event(db, lead_id, "Human", "reply.composed", "Reply prepared; financial or legal content requires approval")
    engine.drain_outbox()
    return result


@app.post("/api/leads/{lead_id}/simulate-message")
def simulate_message(lead_id: str, body: ClientMessage):
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead or not lead["demo"]:
            raise Blocked("Only fictional demo clients accept simulated messages.")
        result = conversations.receive(db, {**body.model_dump(), "email": lead["email"], "name": lead["name"], "message_id": uid("demo_message_")}, "demo", lead)
    engine.drain_outbox()
    return result


@app.post("/api/local/gmail")
def configure_gmail(body: GmailConfig):
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") != "true":
        raise Blocked("Use the real local workspace launcher to connect Gmail.")
    return mailbox.configure(body.email, body.password, body.label)


@app.post("/api/local/gmail/test")
def test_gmail():
    return mailbox.test_connection()


@app.post("/api/local/automation")
def automation(body: Toggle):
    return mailbox.set_enabled(body.enabled)


@app.post("/api/local/poll")
def check_mail():
    result = mailbox.poll()
    engine.drain_outbox()
    return result


@app.post("/api/local/model")
def local_model(body: ModelSetting):
    with connect() as db:
        set_setting(db, "ollama_model", body.model)
        event(db, None, "Human", "model.configured", "Local Ollama model selection updated")
    return {"status": "saved"}


@app.post("/api/growth/settings")
def growth_settings(body: GrowthSettings):
    with connect() as db:
        set_setting(db, "target_market", body.market)
        set_setting(db, "gmail_daily_limit", body.daily_limit)
        set_setting(db, "free_lead_sources", [source.model_dump() for source in body.sources])
        event(db, None, "Human", "growth.configured", "Target market, daily limit and public directory sources updated")
    return growth.dashboard()


@app.post("/api/growth/outreach")
def outreach_toggle(body: OutreachToggle):
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") != "true":
        raise Blocked("Use Start ZanDop Workspace.bat for personal Gmail outreach.")
    with engine.LOCK:
        if body.enabled:
            if not mailbox.public_status()["verified"]:
                raise Blocked("Connect and test your Gmail account in Local setup first.")
            with connect() as db:
                if not setting(db, "ollama_model", ""):
                    raise Blocked("Choose an installed local Ollama model in Local setup first.")
                if setting(db, "gmail_outreach_paused", False) and not body.reviewed_bounces:
                    raise Blocked("Review the delivery failure or sending error before resuming outreach.")
            mailbox.start_bounce_monitor()
        with connect() as db:
            set_setting(db, "gmail_outreach_enabled", body.enabled)
            if body.enabled:
                set_setting(db, "gmail_outreach_paused", False)
            event(db, None, "Human", "gmail_outreach.enabled" if body.enabled else "gmail_outreach.disabled", "Personal Gmail prospecting control changed; daily limit, review and capacity checks remain enforced")
    return growth.dashboard()


@app.post("/api/growth/sites")
def inspect_sites(body: SiteIntake):
    return free_leads.inspect_sites(body.urls, body.service)


@app.post("/api/leads/{lead_id}/outreach-draft")
def prepare_outreach(lead_id: str):
    return growth.prepare(lead_id)


@app.post("/api/leads/{lead_id}/review-outreach")
def review_outreach(lead_id: str, body: DraftReview):
    return growth.review(lead_id, body.draft_hash)


@app.post("/api/leads/import")
def import_csv(body: ImportCSV):
    rows = list(csv.DictReader(io.StringIO(body.csv_text)))
    if not 1 <= len(rows) <= 500:
        raise Blocked("Import 1–500 leads per CSV.")
    # Validate every row before mutation; the transaction is all-or-nothing.
    try:
        parsed = [LeadCreate.model_validate(row).model_dump() for row in rows]
    except ValidationError:
        raise HTTPException(422, "CSV rows require a valid name, email, service, and source. See the import example.") from None
    with connect() as db:
        return {"imported": [add_lead(db, row)["id"] for row in parsed]}


@app.get("/api/leads/{lead_id}")
def lead_detail(lead_id: str):
    with connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        return {"lead": lead, "outreach_hash": growth.draft_hash(lead["details"].get("outreach_draft", {})), "messages": [dict(row) for row in db.execute("SELECT * FROM messages WHERE lead_id=? ORDER BY created_at", (lead_id,))], "events": [dict(row) for row in db.execute("SELECT * FROM events WHERE lead_id=? ORDER BY created_at DESC", (lead_id,))]}


@app.post("/api/leads/{lead_id}/advance")
def advance(lead_id: str):
    lead = engine.advance(lead_id)
    engine.drain_outbox()
    return lead


@app.post("/api/leads/{lead_id}/notes")
def notes(lead_id: str, body: CallNotes):
    with engine.LOCK, connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        lead["details"]["call_notes"] = body.notes
        save_lead(db, lead)
        event(db, lead_id, "Human", "call.notes", "Call notes saved by operator")
    return {"status": "saved"}


@app.post("/api/leads/{lead_id}/book")
def book(lead_id: str, body: Booking):
    if not body.client_confirmed:
        raise Blocked("The client must confirm the time and timezone before a call is booked.")
    if os.environ.get("ZANDOP_LOCAL_WORKSPACE") == "true":
        from datetime import datetime
        try:
            start = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
            if start.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise Blocked("Enter a valid call time including its UTC offset.") from None
        with engine.LOCK, connect() as db:
            lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
            if not lead:
                raise KeyError(lead_id)
            lead["details"]["call_booked"] = {"start": start.isoformat(), "timezone": body.timezone, "provider": "owner-confirmed"}
            lead["details"]["client_contact"] = True
            if lead["stage"] < 4:
                lead["stage"] = 4
            engine.welcome(db, lead)
            save_lead(db, lead)
            event(db, lead_id, "Human", "call.confirmed", "Confirmed slot recorded; owner adds calendar event and hosts the video call")
        engine.drain_outbox()
        return {"status": "recorded", "calendar_event_created": False}
    with connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        if not lead:
            raise KeyError(lead_id)
        row = engine.queue(db, lead, "booking", body.model_dump())
    engine.drain_outbox()
    return row


@app.post("/api/run")
def run():
    return engine.cycle()


@app.post("/api/actions/reconcile")
def reconcile(body: Reconcile):
    return engine.reconcile_action(body.action_id, body.outcome, body.evidence, body.provider_id)


@app.post("/api/approvals/{approval_id}")
def decide(approval_id: str, body: Decision):
    if body.confirmation != approval_id:
        raise Blocked("The confirmation must identify this exact approval.")
    with connect() as db:
        gate = db.execute("SELECT kind FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if gate and gate["kind"] == "sales_exception" and body.decision == "approve":
        raise Blocked("This is an escalation, not an executable send. Resolve the sales request with the client before dismissing it.")
    result = engine.decide(approval_id, body.decision, "authenticated operator" if os.environ.get("ZANDOP_OPERATOR_TOKEN") else "demo operator")
    engine.drain_outbox()
    return result


@app.get("/api/documents/{document_id}/download")
def document(document_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        raise KeyError(document_id)
    return FileResponse(data_dir() / row["path"], media_type="application/pdf", filename=f"ZanDop-{row['kind']}-v{row['version']}.pdf")


@app.get("/api/leads/{lead_id}/artifact")
def artifact(lead_id: str):
    with connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
    if not lead or not lead["details"].get("delivery"):
        raise KeyError(lead_id)
    return FileResponse(data_dir() / lead["details"]["delivery"]["path"], filename="ZanDop-delivery.zip", media_type="application/zip")


@app.get("/api/leads/{lead_id}/preview")
def preview(lead_id: str):
    with connect() as db:
        lead = unpack(db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
    path = lead and lead["details"].get("delivery", {}).get("preview")
    if not path:
        raise KeyError(lead_id)
    return FileResponse(data_dir() / path, media_type="text/html", headers={"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"})


@app.post("/api/discover/places")
def discover(body: SearchPlaces):
    prospects = integrations.discover_places(body.query)
    with connect() as db:
        event(db, None, "Lead Finder", "discovery.completed", f"Google Places: {len(prospects)} businesses; contact enrichment required before outreach")
    return {"prospects": prospects}


@app.post("/api/demo/events")
def demo_event(payload: dict):
    if not all(k in payload for k in ["id", "type", "lead_id"]):
        raise HTTPException(422, "Event requires id, type and lead_id")
    with engine.LOCK, connect() as db:
        result = engine.ingest_event(db, "demo", payload)
    engine.drain_outbox()
    return result


@app.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request):
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Request too large")
    secrets = {"relay": ("AUTOMATION_WEBHOOK_SECRET", "x-zandop-signature", False), "calcom": ("CALCOM_WEBHOOK_SECRET", "x-cal-signature-256", False), "calendly": ("CALENDLY_WEBHOOK_SECRET", "calendly-webhook-signature", True)}
    if provider not in secrets:
        raise HTTPException(404, "Unknown webhook provider")
    key, header, timestamped = secrets[provider]
    if not integrations.verify_signature(raw, request.headers.get(header, ""), os.environ.get(key, ""), timestamped):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw)
        if provider == "calcom":
            if payload["triggerEvent"] != "BOOKING_CREATED":
                return {"status": "ignored"}
            booking = payload["payload"]
            payload = {"id": booking["uid"], "type": "call.booked", "email": booking["attendees"][0]["email"], "data": {"start": booking["startTime"]}}
        elif provider == "calendly":
            if payload["event"] != "invitee.created":
                return {"status": "ignored"}
            invitee = payload["payload"]
            payload = {"id": invitee["uri"], "type": "call.booked", "email": invitee["email"], "data": {"start": invitee.get("scheduled_event", {}).get("start_time")}}
        elif payload.get("type") not in {"reply.received", "email.sent", "email.bounced", "email.unsubscribed", "campaign.health"}:
            raise HTTPException(422, "Relay may only submit outreach events")
        with engine.LOCK, connect() as db:
            result = engine.ingest_event(db, provider, payload)
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "Invalid webhook payload") from None
    # The worker dispatches durable queued work. This endpoint acknowledges promptly.
    return result


@app.get("/r/{token}")
def referral(token: str):
    with connect() as db:
        row = db.execute("SELECT id FROM leads WHERE json_extract(details,'$.referral_token')=?", (token,)).fetchone()
        if not row:
            raise HTTPException(404, "Referral not found")
        db.execute("INSERT INTO referral_clicks VALUES(?,?,?)", (uid("click_"), row[0], now()))
        event(db, row[0], "Referral", "referral.clicked", "Anonymous referral click recorded")
    url = os.environ.get("AGENCY_WEBSITE", "")
    if not url.startswith("https://"):
        return JSONResponse({"agency": "ZanDop", "message": "Thanks for the introduction. Get in touch with your ZanDop contact."})
    return RedirectResponse(url, status_code=302)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend")
