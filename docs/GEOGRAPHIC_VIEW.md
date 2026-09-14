# Geographic detail layout and verification

## What exists in this repository

The legacy Command Center (`/?mode=portfolio`, also demo/backend modes) uses
`StateDrawer` for state portfolio aggregates and `PropertyDrawer` for a property
selected from the map or state list. Both live in `command-center.tsx` and use
Radix Dialog. The map plots property markers at disclosed IBGE municipal
reference coordinates. There is **no independent municipality selector or
municipal risk detail component** in the current tree.

`/seguradora` and `/segurado` use `ProductPerspective`: selecting a property
navigates to its inline page section. Their map, URL state, filtering and risk
presentation are preserved. This change does not invent municipal boundaries,
new geography selections or regional risk data.

## Cause and change

The original generic `SheetContent` already had `overflow-y:auto` and fixed
vertical edges. However, its absolutely positioned close button belonged to
that same scrolling container and could scroll out of reach. It had no safe
edge inset or separate control area. The detail content also contained rigid
rows/badges that could exceed narrow widths; long names needed wrapping.
Controlled dialogs lacked a registered trigger for reliable focus return.

`GeographicDetail` now provides a viewport-bounded dialog frame, a fixed control
header and a single keyboard-focusable body scroller. Its own frame accounts
for dynamic viewport height and safe-area insets. `StateDrawer` and
`PropertyDrawer` use it; unrelated event/hotspot sheets keep their component.

- Desktop: inset right panel up to 540 px wide, sticky entity heading on taller
  viewports, fixed close control, all original content retained.
- Mobile: nearly full available width with safe edge margins, wrapping rows and
  badges, reduced grid columns; entity heading scrolls with the content.
- Short height / landscape / zoom: entity heading also scrolls, leaving the
  compact control header fixed and the remaining height available to content.
- Radix retains modal focus containment, Escape, outside dismissal and page
  scroll locking. Overscroll stays in the detail body. Closing restores focus
  to the opener, including state-to-property and event-to-property transitions.
- Map markers now have a visible keyboard focus ring. Detail headings retain
  semantic titles/descriptions. Environmental value sources/times are inside
  their corresponding `dd` elements for valid definition-list semantics.

No content is line-clamped or removed to fit the frame. Existing disclosures
remain expandable. No risk values, geographic coordinates, portfolio data,
environmental providers, Copilot or Telegram rules are changed.

## Reproducible browser check

With a built frontend running locally on port 3216, run from `frontend`:

```powershell
node scripts/geographic-check.mjs
```

Override `FRONTEND_URL` and `CHROME_PATH` when needed. The check uses real Chrome
through Playwright, with these CSS viewport sizes:
320×800, 390×844, 430×932, 768×1024, 1024×768, 1366×900, 1440×900,
1920×1080, 1366×650 and 844×390. Each size covers both detail types using the
unchanged bundled portfolio and a browser-only stress fixture with 40 entries,
long municipal names and expanded environmental disclosures. No fixture is
written to the portfolio or sent as device telemetry.

A separate temporary Chrome profile applies native 200% page zoom through
Chrome settings in a 1366×650 browser window. This tests actual zoom reflow,
including the browser chrome reducing usable content height.

Artifacts are local and Git-ignored in `frontend/artifacts/geographic/`:
42 cases, top/bottom screenshots, a geometry/results JSON file, and four
targeted axe reports for desktop/mobile state/property details. Checks cover
horizontal containment, safe frame bounds, reaching the end by keyboard, close
control visibility, focus containment/return, switching states, restored map
interaction, page scroll unlocking and runtime errors. Screenshot names use
`municipality-reference` to identify the actual property detail being tested.

The existing product, perspective, portfolio, visual, UX, quality, UI-state,
development, Vercel, operation, loader and action-gate scripts remain applicable.
Images also require human visual review; assertions alone are insufficient.
