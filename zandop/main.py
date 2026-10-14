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

from . import engine, integrations
from .db import add_lead, connect, data_dir, event, initialize, now, save_lead, setting, uid, unpack
from .policy import Blocked, live_enabled


class LeadDetails(BaseModel):
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


async def worker():
    while True:
        await asyncio.sleep(30)
        if live_enabled():
            try:
                await asyncio.to_thread(engine.discover_configured_sources)
                await asyncio.to_thread(engine.cycle, False)
            except Exception as exc:
                with connect() as db:
                    event(db, None, "Orchestrator", "worker.error", type(exc).__name__)


@asynccontextmanager
async def lifespan(app):
    if live_enabled() and len(os.environ.get("ZANDOP_OPERATOR_TOKEN", "")) < 32:
        raise RuntimeError("Live mode requires a ZANDOP_OPERATOR_TOKEN of at least 32 characters.")
    initialize()
    if os.environ.get("ZANDOP_SEED_DEMO", "true").lower() == "true":
        await asyncio.to_thread(engine.seed_demo)
    # A process interruption may leave an ambiguous external action. Never replay it automatically.
    with connect() as db:
        stranded = list(db.execute("SELECT lead_id,kind FROM outbox WHERE status='sending'"))
        db.execute("UPDATE outbox SET status='uncertain',result='Process interrupted; reconcile provider before retrying' WHERE status='sending'")
        for row in stranded:
            event(db, row["lead_id"], "CRM", "action.uncertain", row["kind"] + " interrupted")
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ZanDop Agency OS", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)


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
    return {"status": "ok", "mode": "live" if live_enabled() else "demo", "authentication_required": bool(os.environ.get("ZANDOP_OPERATOR_TOKEN"))}


@app.post("/api/session")
def session():
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie("zandop_session", os.environ.get("ZANDOP_OPERATOR_TOKEN", ""), httponly=True, samesite="strict", secure=os.environ.get("PUBLIC_BASE_URL", "").startswith("https://"), max_age=3600)
    return response


def provider_status():
    provider = os.environ.get("OUTREACH_PROVIDER", "instantly")
    definitions = [
        ("outreach", "Cold outreach", "Instantly / Smartlead", ["INSTANTLY_API_KEY" if provider == "instantly" else "SMARTLEAD_API_KEY", "OUTREACH_SENDER", "OUTREACH_DOMAIN", "OUTREACH_WARMED_AT", "OUTREACH_CAMPAIGN_ID", "AGENCY_PRIMARY_DOMAIN", "PERSONAL_EMAIL_DOMAINS", "AUTOMATION_WEBHOOK_SECRET"]),
        ("calendar", "Call scheduling", "Cal.com / Calendly", ["BOOKING_URL", "CALCOM_WEBHOOK_SECRET" if os.environ.get("CALENDAR_PROVIDER", "calcom") == "calcom" else "CALENDLY_WEBHOOK_SECRET"]),
        ("stripe", "Invoices & payment events", "Stripe", ["STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET"]),
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
                "providers": provider_status(), "outbox": actions, "mode": "live" if live_enabled() else "demo", "outreach_health": setting(db, "outreach_health", {}), "updated_at": now()}


@app.post("/api/leads", status_code=201)
def create_lead(body: LeadCreate):
    with connect() as db:
        return add_lead(db, body.model_dump())


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
        return {"lead": lead, "messages": [dict(row) for row in db.execute("SELECT * FROM messages WHERE lead_id=? ORDER BY created_at", (lead_id,))], "events": [dict(row) for row in db.execute("SELECT * FROM events WHERE lead_id=? ORDER BY created_at DESC", (lead_id,))]}


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
    secrets = {"relay": ("AUTOMATION_WEBHOOK_SECRET", "x-zandop-signature", False), "stripe": ("STRIPE_WEBHOOK_SECRET", "stripe-signature", True), "calcom": ("CALCOM_WEBHOOK_SECRET", "x-cal-signature-256", False), "calendly": ("CALENDLY_WEBHOOK_SECRET", "calendly-webhook-signature", True)}
    if provider not in secrets:
        raise HTTPException(404, "Unknown webhook provider")
    key, header, timestamped = secrets[provider]
    if not integrations.verify_signature(raw, request.headers.get(header, ""), os.environ.get(key, ""), timestamped):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw)
        if provider == "stripe":
            if payload["type"] != "invoice.paid":
                return {"status": "ignored"}
            invoice = payload["data"]["object"]
            payload = {"id": payload["id"], "type": "invoice.paid", "lead_id": invoice["metadata"]["zandop_lead"], "data": {"invoice_id": invoice["id"], "amount_paid": invoice["amount_paid"], "currency": invoice["currency"]}}
        elif provider == "calcom":
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
