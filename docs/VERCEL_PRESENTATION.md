# Vercel presentation deployment

The frontend needs no application environment variables, Flask process, Firebase,
Telegram or Ollama. `/` redirects to `/seguradora`; explicit legacy `?mode=` links
remain available. `/segurado` receives only Cliente A's Araguaia and Horizonte
properties, including scoped map, events and Copilot context. This is public demo
navigation, not authentication or production RBAC.

## Data

The server-only loader tries an explicitly configured `SOMPO_BACKEND_URL` first
(3.5 second timeout), then uses `frontend/src/data/presentation-portfolio.json`.
Invalid backend JSON/schema also falls back. Invalid bundled data produces an
empty, explained unavailable state. Rendering/programmer errors are not swallowed.
The JSON is a static import, included in Next's build inside the frontend root;
no output tracing overrides or external runtime files are needed.

The fixture preserves the canonical capture's original timestamps, scores,
environmental context, attribution and fictional identities. It excludes raw
provider payloads, additional registrations and acquisition debug information.
Stored operational alert/notification state is projected when present; absent
state remains unqueried, never inferred to be zero or delivered. Freshness becomes
cached/stale on read, never live merely because the page was opened.

To deliberately replace the fixture after a canonical capture, run from frontend:

```powershell
node scripts/export-presentation.mjs
```

The exporter only accepts the four known demo identities, rejects sensitive keys
and credential patterns, and preserves environmental evidence without querying
providers or calculating risk. Review the resulting diff before publication.
This is a maintenance command, never an install/build requirement.

## Environment and filesystem audit

| Location | Classification / behavior |
| --- | --- |
| Bundled presentation JSON | Safe read-only server import; scoped projection sent to browser |
| `PRESENTATION_PORTFOLIO_PATH` | Explicit local development override only; ignored on Vercel/production |
| `SOMPO_DEMO_SCENARIO_PATH` | Explicit synthetic demo export, local development only |
| Implicit `../data/presentation_portfolio.json` / `process.cwd()` | Removed from frontend runtime |
| Backend URL fallback | Local development only; production/Vercel never assumes localhost |
| `/api/insured/properties` | Production/Vercel returns explained 403 before backend calls; no filesystem writes |
| Alert actions | Disabled in production; missing backend GET returns controlled 503 |
| `/api/machines` | Missing backend returns empty inventory |
| `/api/agent` | Non-portfolio AI requests return explained 503 without backend |
| Portfolio Copilot | Deterministic stored-context summary, no LLM or provider requests; snapshot mismatch 409, out-of-scope property 404 |
| Browser map | Existing browser map and bundled assets retained; no credential/filesystem dependency |
| `scripts/*` artifact/Windows paths | Local maintenance and browser checks only, not runtime imports |

Required variables: **none**. Optional server variables:

- `SOMPO_BACKEND_URL`: separately deployed backend base URL.
- `SOMPO_BACKEND_API_KEY`: bearer key if that backend requires authentication.
- `SOMPO_PHYSICAL_FARM_ID`, `SOMPO_PHYSICAL_MACHINE_ID`: optional physical machine
  lookup IDs for legacy machine views when a remote backend exists.

Do not set local snapshot paths, Firebase keys, Telegram tokens, Ollama URLs or
`NEXT_PUBLIC_` secrets. Vercel supplies its own environment detection (`VERCEL`);
`NODE_ENV=production` also enforces presentation restrictions when self-hosted.

## Settings and redeployment

Framework Preset: **Next.js**. Root Directory: **frontend**. Build Command:
**npm run build** (default). Output Directory: **Next.js default**, leave override
off (do not set `out`). Install Command: **npm ci**. No custom `vercel.json`.

Remove a stale localhost `SOMPO_BACKEND_URL` from the relevant Vercel environments,
or replace it with the actual remote service. The patch must first be included
in the source being deployed, including the new JSON and modules; redeploying the
old commit cannot apply local changes. After publishing the reviewed patch yourself,
deploy that revision, preferably first as Preview. Verify `/`, both perspectives,
Copilot and the read-only registration explanation; then promote to Production.
Inspect runtime logs for any error. No commit, push or deployment is performed
by this patch task.

## Production verification

From an isolated copy of frontend with no `.env`, Firebase key or sibling data:

```powershell
npm ci
npm run typecheck
npm run lint
npm run build
node scripts/deployment-loader-check.mjs
node scripts/vercel-check.mjs
```

The check runs built `next start` twice, with no backend and an invalid explicit
backend, checks HTTP/API behavior and concurrent perspective isolation, and opens
both perspectives in Chrome at 390/1366/1440/1920 pixels. It exercises detail,
map, Copilot and registration, and saves screenshots in ignored `artifacts/vercel`.
Port 5000 must be free: a trap counts accidental implicit localhost requests.
Chrome path may be supplied using `CHROME_PATH`.
