# Product experience, action tracking and Risk Copilot

Subsequent consistency fixes, shared machine guidance, measurement freshness, concurrent alert protection and the isolated demo workflow are recorded in [PRESENTATION_RUNBOOK.md](PRESENTATION_RUNBOOK.md).

## Preserved foundation

This continues the existing uncommitted productization work. The environmental, machine and operational risk engines, alert lifecycle, deterministic recommendation rules, notification outbox, authenticated Flask APIs and default read-only browser behavior remain authoritative. No commit, push, deployment or real Telegram delivery was performed.

No applicable AGENTS.md existed at the initial audit. Running the isolated Next development test generated `frontend/AGENTS.md` and `frontend/CLAUDE.md`; the generated instructions and relevant bundled Next route-handler/NextRequest documentation were read. No skill was needed for this repository feature work.

## SOMPO and client views

The existing OperationsPanel now leads with “Prioridades agora” for SOMPO and “O que eu preciso fazer agora?” for clients. Counts explicitly describe loaded properties and machines. The insurer retains environmental distribution, lifecycle counts, active categories, attention assets and portfolio views. The client receives the selected property's priorities, alerts and machines. Selection remains presentation state, not tenant authentication.

The queue combines active alerts with property/machine snapshots that still need attention and avoids duplicating a snapshot item when an active alert already represents that entity. Resolving an alert does not lower a still-high persisted risk. Unknown evaluations and unavailable/stale telemetry remain visible. Up to six priority cards are shown, with the full number of signaled items disclosed; alerts and assets remain available below.

Ordering uses severity (critical, high, moderate, low, unknown), then open before acknowledged before assets without active alerts, then most recent recorded occurrence/analysis, then stable ID. Missing timestamps sort last within the same severity/state. It never computes a new risk score. Snapshot-only items explicitly say when an authoritative recommendation or factor is unavailable.

Recommendations are prominent in priority cards, alert cards and the existing machine panel. The UI uses backend recommendation text, and exposes the rule ID in alert details. It does not author replacement safety instructions.

## Action lifecycle and timeline

Open alerts can be acknowledged or resolved; acknowledged alerts can be resolved. Backend transition rules and timestamps are unchanged. Each mutation requires a small inline confirmation, can be cancelled, disables competing controls while pending, and uses a synchronous ref lock to prevent duplicate requests. Local state changes only after a successful backend response. Success and error feedback are announced through status/alert regions. No page reload is necessary.

Disabled environments visibly explain that actions are read-only and disable mutation buttons. Browser writes still require `SOMPO_ENABLE_ALERT_ACTIONS=true` and a non-production Next process. A real development-server test exposed Next's localhost normalization of nextUrl: the same-origin comparison now uses the incoming Host and request protocol, without trusting forwarded-host headers. Foreign/missing origins remain rejected. Production remains read-only even with the flag enabled.

The timeline shows only actual creation, acknowledgment, resolution and queried notification timestamps. Alert creation is not relabeled as an independent risk-detection event. Recommendations have no fabricated generation timestamp. Notification timestamps older than the current alert occurrence are excluded from its timeline because reopened alerts reuse IDs. Notification acceptance does not assert human receipt. Actor names are not invented.

## Map and machine health

The existing indicative map keeps real coordinates and current-GPS filtering. Its context label follows the selected perspective, property markers show official overall environmental severity when available, and the legend includes low and unknown alongside moderate/high/critical. Property tooltips expose environmental level and analysis freshness; selection opens the existing property details. No GIS replacement or new map points were introduced.

The lightweight machine-health view extends the existing MachinePanel with configured sensor descriptors, current GPS when present, and deterministic recommendations alongside its identity, connection, measurements and risk contexts. Machine selection uses the property/machine composite identity to avoid collisions. No 3D library was added.

## Read-only Risk Copilot

`consultar_operacoes(property_id)` reads persisted property and machine snapshots and alerts. Its bounded scope is up to 20 properties, four machines per property and 100 recent alerts. DEMO is excluded. It exposes overall/category risks, factors, lifecycle status/counts, deterministic recommendations, source availability and timestamps. Missing alert reads return unavailable counts, not zero. Insufficient machine evaluation is displayed as unknown, not low.

Executive and operational questions route to this context: property priorities, high/critical machines, open/acknowledged alerts, portfolio summary, principal risk, immediate attention, first checks and stale data. Client questions retain the selected property ID even if the property is absent from the portfolio snapshot list. Generic machine questions no longer use the entire sentence as a machine-name filter. Existing property, hotspot and weather tools remain available. Persisted multi-category property factors now reach the semantic explanation formatter, and persisted alerts now reach the model rather than being silently omitted.

The LLM remains an interpreter, never a risk calculator or mutation executor. Its prompt instructs it to explain official deterministic recommendations and preserve unavailable, insufficient and stale semantics. Tests validate contexts and routing with isolated service fixtures; live Ollama answer quality was not validated in this task.

## Validation

From the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -q
.venv/Scripts/python.exe -m compileall -q services tests
```

Backend: 141 tests passing, three opt-in integration skips. New tests cover executive/client queries, retained scope, recommendation visibility, persisted category explanations, DEMO exclusion, insufficient data, missing alert reads and read-only tools.

From `frontend`:

```powershell
npm run typecheck
npm run lint
node scripts/operations-check.mjs
npm run build
node scripts/action-gate-check.mjs
$env:FRONTEND_URL='http://127.0.0.1:3100'
npm run product-check
npm run visual-check
```

The browser commands require the production build running on loopback port 3100. Product-check owns an isolated backend stub on port 5000 and refuses to replace a running service. Run it before visual-check, not concurrently. The development gate test starts and stops its own Next process on 3001 and backend fixture on 5001; do not run it while another development process owns those ports. It uses a fixture-only API key and never reaches Firebase or Telegram.

Focused checks cover priority ties, resolved exclusion, scoped queues, unknown values, factual timelines and prior-occurrence notification exclusion. Browser checks cover both views at 390/1440px, confirmation/cancellation, failed mutations, successful acknowledgment/resolution, disabled actions, persisted timestamps, BFF null handling and DEMO exclusion. Visual-check checks 1366/1920px and existing drawers, with screenshots under ignored `frontend/artifacts/`. Actual desktop and mobile screenshots were inspected. An initial run was affected by another service taking port 3000; final browser validation uses the isolated port 3100.

## Files changed in this continuation

- `docs/PRODUCTIZATION.md`
- `docs/PRODUCT_EXPERIENCE.md`
- `frontend/src/components/operations-panel.tsx`
- `frontend/src/components/command-center.tsx`
- `frontend/src/components/risk-assistant.tsx`
- `frontend/src/components/risk-map.tsx`
- `frontend/src/lib/operations.ts`
- `frontend/src/lib/backend.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/app/api/alerts/route.ts`
- `frontend/scripts/product-check.mjs`
- `frontend/scripts/operations-check.mjs`
- `frontend/scripts/action-gate-check.mjs`
- `services/sompo_agro_agent/tools.py`
- `services/sompo_agro_agent/agent.py`
- `services/sompo_agro_agent/prompts.py`
- `tests/test_risk_copilot_operations.py`
- `frontend/AGENTS.md` and `frontend/CLAUDE.md` (generated by Next development startup).

Other pre-existing uncommitted productization files were preserved. Build/dev-generated `next-env.d.ts` is managed by Next, not a product feature change.

## Deferred

The final integration pass adds Telegram eligibility, escalation, closure, bounded retry metadata and human-readable notification labels in both scoped perspectives. Product browser checks verify the delivered label and the factual timeline. Copilot reads persisted delivery details and has no mutation tool. Actual external delivery still requires locally available Firebase and Telegram credentials; see the current runbook result. Production user/tenant auth, global aggregation, named assignment, actuarial estimates, 3D and new GIS infrastructure remain deferred.
