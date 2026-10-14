# ZanDop Agency OS

A working local agency orchestration application: an eleven-stage workflow, persistent CRM, approval inbox, source connectors, delivery scaffolds, and branded client PDFs. The default demo uses fictional businesses and simulated external actions. It does not send email, create bookings, contact a model, issue invoices, or move money.

Provider choices and ZanDop's real rate card are intentionally undecided. Live service accounts have not been connected or validated.

## Run

**On Windows:** follow [WINDOWS-START-HERE.md](WINDOWS-START-HERE.md), then double-click **Start ZanDop.bat**. The launcher installs pinned dependencies, opens the dashboard, and always runs a separate local demo without loading live credentials.

Requires Python 3.12 and Chromium. This cloud machine already supplies Chromium at `/usr/bin/chromium`.

```bash
cd /workspace/Ferrari-website-on-Figma
bash scripts/install.sh
bash scripts/run.sh
```

The local service listens on port 8000. Health: `GET /api/health`. Run tests with `make test`. Installation uses the complete pinned dependency set in `requirements.lock`; `requirements.txt` records direct dependencies.

The app seeds six clearly labeled sample clients, actual PDF files, a sample store scaffold, and two review requests. Use **Run next cycle**, open a client, **Simulate booking**, add call notes, and review approvals. Invoice payment can only be simulated on demo records after an approved demo invoice exists. The scheduled worker processes live records every 30 seconds when live mode is explicitly enabled. Source discovery repeats every six hours. Demo records only advance through operator-triggered cycles.

Use this existing checkout. Each cloud task already has an isolated environment; do not create a Git worktree unless explicitly asked. Runtime data lives in ignored `data/`; back up the SQLite database, PDFs, and delivery files together. Use one Uvicorn worker. Live processes must be restarted in a new cloud task.

## The eleven agents

| Stage | Implemented behavior |
| --- | --- |
| 1. Lead Finder | Google Places API search; scheduled CSV/JSON/JSON-LD ingestion from configured public or authorized Shopify/WooCommerce directories, job boards, and LinkedIn exports; component-level opportunity scoring. Unknown revenue or traffic gets no invented score. |
| 2. Researcher | Robots-aware public-site inspection; platform detection; observed product links and prices; HTML-response timing; viewport evidence; supplied competitor URLs; versioned one-page PDF. Observed links are not a total catalog count. |
| 3. Outreach | Short messages reference a documented flaw. Instantly/Smartlead dedicated-campaign enrollment; secondary-sender checks; recent warmed-domain attestation; fresh campaign telemetry; suppression list; bounce auto-pause. |
| 4. Sales | Webhook reply logging, safe scheduling responses in provider threads, Cal.com booking for a client-confirmed slot, Calendly scheduling links, fixed-rate proposals requiring approval. Pricing/legal exceptions go to the human inbox. |
| 5. CRM | SQLite stores leads, messages, approvals, document versions, actions, webhook deduplication, and timestamps. Logging happens at every stage; stage five consolidates the handoff. |
| 6. Client Success | A signed booking event immediately generates and queues a branded, personalized four-page welcome PDF. Call notes drive a four-page working project plan. These contain no contracts, signature fields, or payment terms. |
| 7. Delivery | Shopify Liquid scaffold and product CSV; WooCommerce product CSV and theme scaffold; WordPress or React web scaffold; React Native starter component; model-backed editorial draft using brand voice and SEO keywords. Downloadable ZIPs remain unpublished. |
| 8. Quality | Local-link validation, viewport and size checks, actual Chromium layout checks at 375/768/1440 pixels, local preview timing and browser errors; minor whitespace repairs; final human approval with outstanding platform, scope and copy checks visible. |
| 9. Finance | Exact-payload approval before Stripe customer/invoice creation, finalization, and invoice email. `collection_method=send_invoice`, `auto_advance=false`; no auto-charge or card capture. Signed payment events must match invoice ID, amount and currency. |
| 10. Reporting | Weekly durable updates for active projects; no duplicate weekly messages. Final approved delivery plus confirmed payment closes the project. |
| 11. Referral | A personalized email is queued 30 days after close, with a unique tracking URL. Anonymous clicks are recorded before redirecting to the configured agency website. No incentives or money are promised. |

The editable visual is [docs/workflow.svg](docs/workflow.svg); [Mermaid source](docs/workflow.mmd) is also included. The dashboard's Agent workflow page displays the funnel and downloads the SVG. No external whiteboard account is needed.

## Operating boundaries

Human approval binds to the exact payload stored in the approval record. The dispatcher checks the approved payload again before external action. Rejected proposals or deliveries are held. Legal agreements and signatures have no automatic execution path. Proposal sends and invoice creation/sends require approval; the model has no direct tools or money permissions.

The durable outbox marks an action as sending before making a provider request. Uncertain responses or interrupted sends are never automatically repeated. Inspect the provider's receipts, then use `POST /api/actions/reconcile` with the exact action ID, `outcome` (`sent` or `not_sent`), evidence, and a provider ID for confirmed sends. This is an operator action recorded in the audit trail. Money actions retain their original exact-payload approval. Do not claim `not_sent` without checking the provider; Stripe/Resend idempotency windows are finite.

Browser checks exercise generated local previews, not the production Shopify/WordPress store or a real native device. Scaffolds need target-platform integration, complete application features, deployment, and the visible final quality review. No automatic production deploy, store publish, contract signature, or card charge is implemented.

## Configure live services

Copy `.env.example` to `.env` only if it does not already exist, or inject variables through environment settings. Never paste secrets in chat or commit `.env`. `scripts/run.sh` loads a local `.env` without printing its contents. Set a strong `ZANDOP_OPERATOR_TOKEN` (at least 32 characters) before enabling `ZANDOP_LIVE_MODE=true`. The UI accepts the operator token for the current browser session. API mutations reject cross-origin browser requests; private endpoints require the operator credential when configured. Expose the service only behind authenticated HTTPS. Keep one process and enforce public-only research egress in production, including DNS-rebinding protection.

Configuration presence is not provider validation. Test against the chosen providers' test accounts before enabling client traffic. The Instantly and Smartlead adapters target their public REST APIs; endpoint availability, permissions and response schemas must be verified with your account. No live credentials were supplied during development.

* **Outreach:** choose `OUTREACH_PROVIDER=instantly` or `smartlead`, its API key, a dedicated `OUTREACH_CAMPAIGN_ID`, and a single `OUTREACH_SENDER`. Every sending account in that campaign must match the configured sender. `OUTREACH_DOMAIN` must be different from `AGENCY_PRIMARY_DOMAIN`, every `PERSONAL_EMAIL_DOMAINS` entry, and the blocked personal-mail providers. Configure and verify SPF/DKIM/DMARC and warmup in your sending platform; set `OUTREACH_WARMED_AT` only after verifying readiness. Attestation expires after 30 days. This app does not itself warm a domain. Configure campaign templates to render `email_subject` and `email_body`. Disable provider follow-up sequences unless separately reviewed; a provider campaign continues outside this process until paused.
* **Bounce protection:** relay authenticated sent, bounced and opt-out events plus hourly cumulative health snapshots. No cold email is enrolled without health telemetry less than one hour old. At a default bounce rate of 2%, local sends stop immediately and the next worker pass requests provider campaign pause. The pause is sticky; investigate the campaign before clearing it. Provider pause failures appear in the audit trail. Keep sender-platform bounce limits enabled too.
* **Calendar:** choose Cal.com or Calendly; set `BOOKING_URL` and the native webhook signing secret. Cal.com direct bookings additionally need `CALCOM_API_KEY` and `CALCOM_EVENT_TYPE_ID`. A direct booking requires an explicit client-confirmed slot and timezone. Cal.com uses its `2024-08-13` booking API version.
* **Client email:** configure Resend with `RESEND_API_KEY` and a verified `CLIENT_EMAIL_FROM` on the primary agency domain. It sends welcome/plan PDFs, approved final packages, weekly reports, and referral emails. Cold outreach and sales replies remain with Instantly/Smartlead.
* **Finance:** add Stripe test credentials first, `STRIPE_API_KEY` and `STRIPE_WEBHOOK_SECRET`. Define a fixed `ZANDOP_RATE_CARD` per service with integer minor-unit `amount`, `currency`, and exact `scope`. Demo prices are not real agency prices. No rate is assumed for real clients.
* **Discovery:** Google Places requires `GOOGLE_PLACES_API_KEY`; its API returns businesses and websites, not verified contact emails. Use `POST /api/discover/places` to inspect those prospects, then import verified business contacts. `ZANDOP_SOURCES` configures recurring public/authorized feeds for the other sources. HTML sources must expose business contacts in JSON-LD. Arbitrary directory DOM layouts, logged-in LinkedIn scraping, contact enrichment, and anti-bot bypass are not implemented. Unsupported sources require an authorized export or a dedicated adapter.
* **Writing:** set `MODEL_BASE_URL` to an HTTPS OpenAI-compatible API base, `MODEL_API_KEY`, and `MODEL_NAME`. Provide a brand voice, factual source notes, and SEO keywords. The model returns JSON; factual claims remain visible for review.
* **Referrals:** set the public HTTPS `PUBLIC_BASE_URL` and `AGENCY_WEBSITE`. Do not use a localhost address in client emails.

Required network destinations depend on provider selection: `api.instantly.ai` or `server.smartlead.ai`, `api.cal.com` when used, `api.resend.com`, `api.stripe.com`, `places.googleapis.com`, your model gateway, and the explicitly selected research/source websites. No environment allowlist was broadened during development.

## Webhook contracts

All webhook events are deduplicated in SQLite. Native endpoints:

* `POST /webhooks/calcom`: `BOOKING_CREATED`, `x-cal-signature-256` HMAC-SHA256 over the raw body.
* `POST /webhooks/calendly`: `invitee.created`, Calendly's timestamped signature.
* `POST /webhooks/stripe`: `invoice.paid`, Stripe's timestamped signature; five-minute tolerance.
* `POST /webhooks/relay`: normalized Instantly/Smartlead events, `x-zandop-signature` HMAC-SHA256 over the raw body using `AUTOMATION_WEBHOOK_SECRET`. Configure a trusted relay to verify the original provider and sign this envelope; a native Instantly/Smartlead webhook is not assumed to use this custom signature.

```json
{
  "id": "stable-provider-event-id",
  "campaign_id": "the-configured-dedicated-campaign",
  "type": "reply.received",
  "email": "client@business.example",
  "data": {
    "subject": "Re: A small idea",
    "body": "Let us set up a conversation.",
    "thread_id": "provider-message-id",
    "provider_lead_id": "needed-for-Smartlead"
  }
}
```

Relay event types: `reply.received`, `email.sent`, `email.bounced`, `email.unsubscribed`, `campaign.health`. Health data is `{ "sent": 100, "bounced": 1 }` for the dedicated campaign. Relays cannot submit payment or booking events. Demo events use `/api/demo/events`, require an operator credential when configured, and cannot affect live records or live campaign telemetry.

## Validation

The meaningful test suite in `tests/test_system.py` covers the complete eleven-stage demo journey with external provider calls forbidden; actual generated PDFs; mobile/desktop artifact checks; financial and final-delivery gates; approval payload tampering; replay protection; domain restrictions; mixed-sender campaigns; suppression; bounce pause; invoice matching; webhook signatures; uncertain-send handling; weekly report deduplication; and public-URL restrictions. No live provider API, real payment, real email delivery, production storefront, or new-cloud-task restoration is represented as verified.

The repository began empty. All application code and tests were created for this request. The original repository name is preserved.
