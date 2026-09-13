# Final product quality pass

Completed from the existing uncommitted UX work on 12–13 September 2026. No commit, push, deployment, data refresh, credential changes, or external messages.

The starting point was the saved [UX review](../frontend/artifacts/ux-polish/REVIEW.md), existing component/CSS changes, and the requested phase list. The earlier full task message was not available in this session; the on-disk review supplied the handoff. The existing hierarchy, colors, cards, map treatment, and progressive disclosure were preserved.

## Fresh screenshot audit and iterations

Twenty new baseline captures were taken from the uncommitted application before further changes: both perspectives plus high, moderate, and low exposure, at 390, 1366, 1440, and 1920 CSS pixels. See [baseline results](../frontend/artifacts/ux-polish/resumed-before/results.json).

The final production matrix contains 40 route/width combinations at **320, 390, 700, 768, 1024, 1366, 1440, and 1920px**, with full-page and viewport captures. It includes insurer overview, insured overview, and high/moderate/low detail. Additional captures cover assistant questions/answers, landscape at 844×390, and 640px reflow (equivalent CSS width to a 1280px screen at 200%). The 320px matrix also exercises the reflow width equivalent to 400% on a 1280px screen; browser zoom itself was not automated.

Visual inspection checked the executive overview, mobile priorities, selected property identity, recommendations, empty guidance, evidence disclosures, tablet density, assistant position, and long-name wrapping. Automated checks covered every matrix case for overflow and runtime errors.

| View | Fresh baseline | Final evidence |
| --- | --- | --- |
| Insurer, mobile | [390px](../frontend/artifacts/ux-polish/resumed-before/seguradora-390.png) | [390px](../frontend/artifacts/quality-final/insurer-390.png) |
| Insured, laptop | [1366px](../frontend/artifacts/ux-polish/resumed-before/segurado-1366.png) | [1366px](../frontend/artifacts/quality-final/insured-1366.png) |
| High exposure | [1440px](../frontend/artifacts/ux-polish/resumed-before/high-1440.png) | [1440px viewport](../frontend/artifacts/quality-final/high-1440-viewport.png) |
| Moderate exposure | [1366px](../frontend/artifacts/ux-polish/resumed-before/moderate-1366.png) | [1366px viewport](../frontend/artifacts/quality-final/moderate-1366-viewport.png) |
| Low exposure | [390px](../frontend/artifacts/ux-polish/resumed-before/low-390.png) | [390px](../frontend/artifacts/quality-final/low-390.png) |
| Tablet overview | — | [768px viewport](../frontend/artifacts/quality-final/insurer-768-viewport.png) |
| Large desktop | — | [1920px viewport](../frontend/artifacts/quality-final/insurer-1920-viewport.png) |
| Assistant | — | [Mobile](../frontend/artifacts/quality-final/assistant-390.png), [landscape](../frontend/artifacts/quality-final/assistant-landscape.png) |
| Unavailable capture | — | [320px fixture](../frontend/artifacts/quality-final/states/empty-segurado-320.png) |
| Unknown risk / long name | — | [320px fixture](../frontend/artifacts/quality-final/states/pending-long-name-segurado-320.png) |

Iteration 1 added keyboard access and accurate data-state messaging. The full accessibility scan then identified contrast failures in footer text and source disclosures (4.15:1 and 4.47:1); these were darkened. Screenshot review also caught the wide assistant launcher overlapping tablet actions, so tablet uses the compact launcher. An additional pending-property fixture exposed long-name overflow; the switcher and hero now wrap safely, and the unknown badge uses stronger contrast. Each failing check was rerun after its fix.

## P0 / P1 / P2 inventory

P0 means data loss, scope leakage, or an unusable primary route. P1 means a blocked interaction, misleading evidence, security dependency issue, or failing quality gate. P2 means readability, orientation, or consistency.

| Priority | Finding | Resolution and evidence |
| --- | --- | --- |
| P0 | No P0 reproduced in this pass | Insured APIs/UI exclude other clients; malicious scope inputs fail; both routes load. No persistence or risk-engine changes. |
| P1 | Assistant lacked dialog focus management and an input label | Radix dialog supplies focus containment, Escape and focus return; labeled textarea, live conversation log, loading announcement and retry verified at all eight widths. |
| P1 | Footer/source text failed contrast | Darker text; zero reported violations in 23 production scans and eight fixture scans. Unknown-risk badge also darkened. |
| P1 | Very long property names overflowed narrow layouts | Wrapped hero and switcher text, constrained grid children; 320px static-render fixture passes. Missing client names no longer reach an unsafe non-null sort lookup. |
| P1 | Data banner claimed real evidence regardless of availability | Banner derives from available properties and origins. Empty/mixed/unknown states avoid a blanket real-evidence claim. Read-only unknown properties offer no analysis mutation button. |
| P1 | Four existing checks depended on obsolete UI/contracts | Root dashboard tests use its explicit mode route; assistant tests verify deterministic wording and actual scope; client filters use current controls; production read-only and development creation are both tested. The BFF adapter test owns an isolated fixture server. |
| P1 | Two high-severity dependency advisories | Compatible lockfile updates for affected transitive dependencies; npm audit reports zero vulnerabilities. |
| P2 | Missing skip link and duplicate page headings | Keyboard skip link, one h1 per page, property h2, and focus/scroll to newly selected property. |
| P2 | Small touch targets and textarea text | Primary filters, perspective links, disclosures and dialog controls have 44px minimum height; textarea uses 16px text. |
| P2 | Tablet cards and assistant competed for space | Two-column priority grid at medium widths and compact launcher through 1050px; retained three columns on desktop. |
| P2 | Assistant content was hard to read and lost new answers below the fold | Readable transcript, preserved paragraphs, automatic transcript scroll, fixed header/form, and viewport-relative dialog height. |
| P2 | Mobile evidence disclosure and time zone were easy to miss | Visible “Sobre os dados” affordance on mobile and Brasília label on portfolio timestamps. |
| P2 | Invalid property URL silently showed overview | Explicit unavailable-in-this-scope notice while keeping only permitted properties visible. |

No reproduced P0/P1/P2 from this inventory remains open in the tested presentation scope.

## Quality gates

| Gate | Result |
| --- | --- |
| ESLint, including zero warnings | Pass |
| TypeScript `tsc --noEmit` | Pass |
| Next production build | Pass |
| npm audit | Pass: zero vulnerabilities |
| Python unittest discovery | Pass: 208 tests run, 205 passed, three explicit integration opt-in skips |
| Operations rules | Pass: ordering, dedupe, scope, unknown data, factual timeline |
| Deployment loader | Pass: remote precedence, malformed/error fallback, missing snapshot, original scores/timestamps, no production filesystem reads |
| Product check | Pass: both legacy views, alert acknowledge/resolve, rejected write recovery, composite machine selection, write gate and real BFF adapters against isolated fixtures |
| Visual check | Pass: legacy desktop dashboard and drawer, no overflow/hydration/runtime errors |
| Perspective check | Pass: scoped APIs, property switching without document reload, refresh/deep links, client filtering, assistant scope, production read-only behavior |
| Portfolio check | Pass: seven assistant questions, actual deterministic response contract, provenance, original factors, scoped client UI |
| Existing UX polish check | Pass: 20 layouts and priority/map/history/assistant/registration interactions |
| Final quality browser check | Pass: 40 production layouts, 23 axe scans, keyboard interaction, retry, history, sort, invalid scope and stale snapshot rejection; landscape and reflow checks |
| Empty/pending state check | Pass: eight layouts and eight axe scans; static server-rendered components using current production CSS, not hydrated interaction tests |
| Vercel scenarios | Pass: unconfigured and unavailable backend, 16 layouts, concurrent scope isolation, read-only registration, no implicit localhost Flask requests |
| Development action gate | Pass: same-origin enforcement, server-only fixture key and permitted transitions |
| Development workflow | Pass: intercepted registration, pending analysis, explicit 503 response, exported demo at four widths in both legacy perspectives |
| `git diff --check` | Pass |

Evidence: [production accessibility results](../frontend/artifacts/quality-final/results.json), [backend log](../frontend/artifacts/quality-backend.log), and per-state axe JSON beside each screenshot. Screenshot artifacts are intentionally Git-ignored; this report and reproducible checks remain in the uncommitted source changes.

## Enterprise credibility and boundaries

The UI distinguishes fictitious customer identities, cached environmental evidence, unknown operational state, unavailable recommendations, and non-probabilistic risk indices. Assistant presentation mode explicitly says it is a deterministic snapshot consultation without AI interpretation. Unsupported client/property inputs cannot broaden the insured scope. Dates remain the stored dates; no scores, recommendations, sources or timestamps were refreshed or fabricated for a better screenshot.

This is an enterprise presentation prototype. End-user authentication/RBAC, actuarial calibration, a real geographic basemap/property boundaries, and production observability remain outside this UX pass. The deterministic assistant still summarizes the available scope rather than providing unrestricted question-specific reasoning. Validation used installed Chrome on Windows; real iOS/Safari/Firefox devices, manual screen-reader sessions, and user research were not performed. Automated axe results are evidence, not a WCAG certification.

## Final ratings

These are evidence-based review scores against the requested 10/10 target, not claims of perfection.

| Dimension | Rating | Concrete justification |
| --- | --- | --- |
| Desktop visual quality | 9.5/10 | Clear executive hierarchy, aligned priority cards, compact comparison rows and readable selected-property details at 1366–1920px. The map remains indicative. |
| Mobile and responsive UX | 9.5/10 | 320–1920px coverage, tablet grid, compact assistant, landscape/reflow checks, long-name wrapping and no tested horizontal overflow. Real-device validation remains. |
| Interaction reliability | 9.5/10 | Navigation, history, sort, scope, dialog, retries and both read-only/development registration paths pass. |
| Accessibility | 9/10 | 31 zero-violation scans, keyboard focus/skip/Escape/return, headings, labels, announcements and reduced-motion coverage. Manual assistive-technology validation remains. |
| Enterprise credibility | 9/10 | Honest evidence and snapshot semantics, explicit unavailable states, deterministic assistant labeling and verified scope. Production identity/governance remains separate work. |
| Engineering validation | 9.5/10 | Lint/types/build, 205 passing backend tests, frontend contracts/workflows, deployment fallback and zero npm advisories. Three real-service integrations intentionally remain opt-in. |
| Overall presentation quality | **9.3/10** | All reproduced issues and requested validation phases are closed. An unconditional 10/10 would overstate cross-browser, assistive-technology and production-readiness evidence. |

## Reproducing the checks

From `frontend`, run `npm run build`, then `npm run start -- --hostname 127.0.0.1 --port 3202` in a separate terminal. `npm run quality-check` and `npm run quality:states` default to that URL. `CHROME_PATH` can override the installed Chrome executable.

Set `$env:FRONTEND_URL='http://127.0.0.1:3202'` for `product-check.mjs`, `visual-check.mjs`, `perspective-check.mjs`, `portfolio-check.mjs` and `ux-polish-check.mjs after`. Run the scripts from `frontend/scripts` using `node scripts/<name>.mjs`.

`node scripts/vercel-check.mjs`, `node scripts/action-gate-check.mjs` and `npm run quality:development` own their isolated servers and should run sequentially. Development checks require `frontend/artifacts/demo-scenario.json`, generated from the repository root using `.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario combined_critical`. No Firebase seed/write is required.

Backend: `.venv/Scripts/python.exe -m unittest discover -s tests -v`. Static checks: `npm run lint -- --max-warnings=0`, `npm run typecheck`, `npm audit`, and `git diff --check`.
