# Two operating perspectives

Final pre-Telegram hardening, offline scenarios, startup and recovery are documented in [PRESENTATION_RUNBOOK.md](PRESENTATION_RUNBOOK.md). Exported DEMO scenarios now expose synthetic read-only alert lifecycle data; they never enable real mutations or notification delivery.

The subsequent product-experience work is documented in [PRODUCT_EXPERIENCE.md](PRODUCT_EXPERIENCE.md), including priority ordering, action confirmation/timeline, the persisted operations Copilot tool and additional validation. The foundation described below remains in place.

The audited foundation already provided deterministic environmental, machine and operational risk, Firestore snapshots, IoT/device identity, event deduplication, alert lifecycle, regional map infrastructure, a Next.js server-side backend adapter, explicit DEMO/showcase data and read-only AgroRiskAgent tools. Those engines, credentials and agent tool permissions remain intact.

## Product behavior

- **SOMPO Control Center:** environmental category distribution including unknown, loaded properties/machines, open/acknowledged/resolved alert counts, important active categories, machines with internal/operational exposure, and assets requiring attention. The existing property cards/map retain their explicit fire-risk perspective; the new exposure distribution uses the official overall environmental category.
- **Client Operations Center:** property selection, immediate attention, scoped alerts and machines, telemetry, recommendations, status/history, existing property explanation drawers and Risk Assistant. Regional weather notices retain their source/location/time; they do not assert that the selected property is affected.
- Both use the same adapters and components. The selector is presentation state, **not authentication or a tenant boundary**. Future identity/tenant authorization belongs in the BFF and backend auth provider, not in this selector. Do not expose this application as a multi-tenant client portal before implementing that boundary.
- Backend snapshots are the default. Environmental showcase and synthetic DEMO remain explicitly selected modes; real alert actions and lifecycle metrics are unavailable in those modes. The hardcoded lab-machine/telemetry presentation fallback was removed.
- Counts are explicitly a **bounded query sample**, not global portfolio totals: up to 20 properties, 4 machine detail reads per property and 100 recent alerts. Failed detail reads do not become low risk. An unknown category, missing measurements and missing coordinates remain unavailable. The map omits missing coordinates and only shows machine GPS marked current by the backend at read time.
- Refresh is explicit. The previous polling loop that replaced the entire machine list with a separate physical-device showcase list was removed to prevent cross-view/source contamination. Device ingestion and telemetry endpoints are unchanged.

## Alert actions and recommendations

The original `AlertService.update_status` still owns `open -> acknowledged -> resolved` and `open -> resolved`, timestamps and actor attribution. The frontend updates status only after a successful backend response. It never invents the person notified or a resolution explanation that the model does not contain.

`services/recommendation_service.py` supplies versioned deterministic rules with rule ID, basis and operational-guidance meaning. Inputs are existing alert types, official machine evidence, device freshness and official severe weather warnings. A temperature recommendation requires high/critical **internal/component** temperature evidence; ambient temperature does not imply engine overheating. Unknown conditions produce no recommendation. Neither the LLM nor the frontend authors authoritative recommendations.

`/api/alerts` keeps the application API key server-side. Browser writes require `SOMPO_ENABLE_ALERT_ACTIONS=true`, a non-production Next.js process and a same-origin request. They are disabled by default and always disabled in production until real user authentication is added. Existing authenticated Flask PATCH remains available. Use local development on loopback for the demonstration; the selector never grants permissions. GET requests do not dispatch notifications.

## Notification architecture

```text
Risk/event processing -> AlertService.emit -> NotificationDispatcher.enqueue
                                         -> Firestore notifications outbox
Explicit worker -> atomic attempt claim -> TelegramChannel -> recorded result
```

`notifications` is separate from `alerts`. Records contain notification ID, alert ID, channel, recipient configuration reference, creation/attempt/delivery timestamps, attempts and status. The stored message contains operational context, not credentials. The current recipient reference is `telegram_operations`; the actual chat ID/token are resolved from the worker environment. Drain/review pending records before changing the recipient configuration.

Creation uses a deterministic key of alert ID, occurrence creation time, severity, channel and recipient reference, preserving the original key encoding. Atomic document creation handles concurrent enqueues and new alerts; atomic `notification_attempts` documents arbitrate concurrent workers. Repeated evaluations/refreshes and acknowledgements do not repeatedly send. HIGH → CRITICAL creates an escalation; a reopened occurrence has its own identity. DEMO is excluded by default; only the explicit `scripts.telegram_demo` path permits a development/test property under `demo_telegram_`, with the DEMO label first in every message.

Run explicitly (or schedule externally):

```powershell
.venv/Scripts/python.exe -m scripts.dispatch_notifications
```

The worker selects `created` and retryable `failed` records, verifies the persisted alert, claims each attempt and persists `attempting` before sending. Obsolete/resolved unsent occurrences and expired weather notifications become `cancelled`. Telegram success becomes `delivered`, including safe `telegramMessageId` when returned. Explicit 4xx authentication/configuration errors are `failed` with `retryable=false`. Connect timeout, explicit Telegram 5xx rejection and 429 retry at most three times, with at least 60/120 seconds between attempts and the longer upstream `retry_after` respected; exhaustion becomes `permanently_failed`. Read timeout, connection reset, malformed/non-JSON response and ambiguous server delivery become `unknown` without automatic resend. A crash or persistence failure after sending leaves an attempt requiring operator reconciliation. Exactly-once external delivery is not claimed. Delivery means channel acceptance, not proof of human reading. API semantics follow the [Telegram Bot API](https://core.telegram.org/bots/api#responseparameters).

Policy: official HIGH/CRITICAL environmental category, fire/hotspot, machine and operational alerts are eligible. LOW, ordinary MODERATE, missing/stale data by itself and informational types are excluded. Official weather Perigo/Grande Perigo requires a matched monitored property; Perigo Potencial additionally requires a persisted environmental HIGH/CRITICAL snapshot no older than two hours. `scripts.process_weather_alerts` is explicit ingestion, never a dashboard GET. The existing INMET adapter supplies Tempestade events only. Matching requires an exact municipality/UF entry in upstream location (semicolon/comma separated); regional descriptions alone are insufficient and stay dashboard-only. No polygon or fuzzy match is fabricated. Each upstream weather ID has a separate persisted alert identity.

Resolving an externally delivered alert queues one closure per occurrence, only when a delivered record for that occurrence exists. Acknowledgement adds no message. Closure says the alert was closed by the responsible person; it does not claim that weather/sensor conditions have normalized. Older records lacking occurrence metadata do not authorize an automatic closure. UI and read-only Copilot expose safe persisted state; Copilot reads notification details for at most 20 alerts and cannot send or mutate.

Enqueue failure never changes the risk result. Fixed safe logs, HTTP log filters and a metadata allowlist exclude token/chat ID and raw response/exception payloads. The explicit worker repairs enqueue from up to 100 recent alerts, and checks up to 100 resolved alerts after delivery to repair a resolution racing the original send. Outbox queries are bounded at 100 records per state per invocation; this is not a full portfolio sweep or an atomic alert/outbox transaction. Recipient routing remains a single server-managed destination; review pending records before changing it.

No real Telegram message was sent during implementation or tests. Email, webhook, WhatsApp/push, tenant-specific recipient routing, background scheduling, reconciliation UI, atomic alert/outbox transactions and production user auth are intentionally deferred. Regional dataset rollout remains deferred. Global count aggregation/pagination and a full action-assignment model are also deferred; current sample limits are visible.

## Configuration

Backend/worker `.env`:

```dotenv
TELEGRAM_NOTIFICATIONS_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Set enabled to `true` and fill credentials locally only when ready to enqueue/deliver real notifications. Existing `FIREBASE_KEY_PATH` and application auth configuration remain required. Retry queries use equality on status and retryable; preserve Firestore automatic indexes. See the runbook for exact isolated delivery commands and current validation results.

Frontend `.env.local`:

```dotenv
SOMPO_ENABLE_ALERT_ACTIONS=false
```

Set to `true` only for a local `npm run dev` demonstration of real alert changes. Existing `SOMPO_BACKEND_URL` and `SOMPO_BACKEND_API_KEY` are unchanged. Ollama settings remain unchanged; the agent remains read-only and receives the selected property's context in the client view.

## Validation and changed files

Backend: `python -m unittest discover -s tests -q` — 135 tests, passing with 3 opt-in integration skips — and `python -m compileall -q config.py server.py integracoes services scripts tests` passed. New tests cover recommendation mapping, semantic temperature checks, delivery deduplication, concurrent claims, retry bounds, ambiguous delivery, failure isolation, secret handling, additive API contracts, auth and weather severity. Two existing tests were missing Firebase boundary mocks; their original assertions were preserved and the missing mocks added.

Frontend: `npm run typecheck`, `npm run lint`, `npm run build`, `npm run product-check` and `npm run visual-check` all passed. Browser checks ran against the local production build at 390px/1440px and 1366px/1920px, with no runtime, hydration or overflow errors. Product checks use explicit isolated fixtures, verify desktop/mobile rendering, scope, lifecycle actions, the default write gate and real BFF adapter behavior for missing data and DEMO exclusion. The contract test binds a temporary stub to loopback port 5000 and refuses to overwrite a running backend; use an isolated test environment. Screenshots are saved under ignored `frontend/artifacts/`. No Firebase or Telegram integration write tests were enabled.

Primary changes: `server.py`, `services/alert_service.py`, new `services/recommendation_service.py`, new `services/notification_service.py`, new `scripts/dispatch_notifications.py`; frontend `command-center.tsx`, new `operations-panel.tsx`, `risk-map.tsx`, `risk-assistant.tsx`, `lib/backend.ts`, `lib/types.ts`, new `app/api/alerts/route.ts`, `package.json`, new `scripts/product-check.mjs`, updated `scripts/visual-check.mjs`; `.env.example` files, API/architecture/README/OpenAPI documentation; new `tests/test_productization.py` and boundary-mock fixes in `test_stage4.py` / `test_stage5.py`.

Dependency installation used the existing requirements and lockfile. npm reported two high-severity dependency advisories; dependency upgrades were not bundled into this product change. No commit, push, deployment or external notification was performed.
