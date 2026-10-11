# DoorLedger dashboard

> Care is delivered through the front door. DoorLedger makes sure it arrived.

Web dashboard for DoorLedger: reconciles the care that was **expected** at an elderly person's front door
(caregiver visits, temperature-sensitive medication deliveries) against what their Ring doorbell **observed**,
and shows what the agent did about the differences.

- **Today** (family view): "right now" status, *Care plan vs. reality* day timeline, medication-on-the-porch
  card (exposure clock, estimated box temperature, countdown to unsafe, escalation chain, proof frame),
  caregiver-visit card (progress ring, check-in/out with source badges), findings feed, actions feed.
- **Agency** (coordinator view): visits with the six 21st Century Cures Act EVV fields, status chips,
  **Export EVV CSV**.
- **Ledger**: append-only audit trail of expectations, observations, findings and actions.
- **Demo strip**: run scenarios, set speed, reset. Press **D** to show/hide (hidden by default on phones).

Every observation shows its provenance badge: *Ring live view*, *Ring snapshot*, *Ring event*, *Own footage*, *Simulated*.

## Run

Requires Node 20+ (tested with Node 24).

```bash
cd web/dashboard
npm install
npm run dev          # http://localhost:3000, uses the backend if reachable, else mock
npm run dev:mock     # force mock mode (no backend needed)
npm run build && npm start   # production
```

### Configuration (`.env.local`, see `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8787` | FastAPI backend |
| `NEXT_PUBLIC_MOCK` | unset | `1` = always use mock data + client-side demo clock |

`NEXT_PUBLIC_*` values are inlined at build time; restart `next dev` / rebuild after changing them.

## Modes

**Live** — the server render fetches `/api/household`, `/api/state`, `/api/timeline` (800 ms timeout).
The browser then polls `/api/state` every 2.5 s and subscribes to `/api/stream` (SSE, auto-reconnect with
backoff); each streamed record is appended to the ledger and triggers a state refresh. Demo buttons call
`POST /api/demo/run` / `POST /api/demo/reset`; evidence images load from `/api/evidence/{path}`;
EVV export downloads `/api/evv.csv?date=…`. The backend must allow CORS from `http://localhost:3000`.

**Mock** — used when `NEXT_PUBLIC_MOCK=1`, or automatically when the backend is unreachable at load
(the browser re-probes once on mount; the demo strip has *Retry API* / *Use mock*). A fixture **winter** day
for a fictional household (Rosa Martínez, 81, Chicago, IL; aide Maria Gómez, BrightPath Home Care; insulin
refill from a pharmacy via UPS) is generated for *today* in America/Chicago. It mirrors the backend
scenarios in `core/src/doorledger/scenarios.py`. A client-side **demo clock** drives it: state at any instant
is derived from the fixture (`lib/mock/engine.ts`), and the box temperature is computed with a TypeScript
port of `core/src/doorledger/exposure.py` (Newton cooling/heating toward the outside temperature; on a
freezing porch the danger is the 0 °C freezing limit, on a hot one the 30 °C excursion limit).
Outside is −6 °C in the morning and −9 °C in the afternoon. EVV CSV is generated in the browser.

Provenance is honest: the 2:07 PM package drop shows a **real Ring Developer Playground frame**
(`public/ring/package.jpg`, copied from `fixtures/evidence/package.jpg`; source `ring_live_view`,
pre-labelled replay; clip CC BY 4.0, credited in the page footer). Scenes whose footage isn't filmed yet
(aide check-in/out, package pickup) are `simulated` with no `evidence_path`, and the UI shows a
"No camera frame · simulated" panel for them, never an image. Box temperatures are always labelled
"est.": they come from the thermal model, not a thermometer.

**"Right now" banner.** `lib/banner.ts` derives it with one pure function from state (open windows,
pending visits, unresolved warnings/criticals, what was resolved today); it never says "all clear"
over a late aide, an open delivery window or a short visit. `lib/banner.cases.ts` is its table of
cases: `next dev` checks it on load (console `[banner] N/N cases pass`), or run
`node_modules/.bin/jiti lib/banner.cases.ts`.

**Agency / EVV.** A check-in counts as *Verified at the door* only when its source is `own_footage`,
`ring_live_view` or `ring_snapshot` **and** `detail.method == "signed_code"`; simulated presence shows
*Simulated (demo)* and never fills EVV elements 5–6.

**Accessibility.** Today/Agency/Ledger are a WAI-ARIA tablist (←/→/Home/End), focus rings are always
visible, new findings/actions and banner changes are announced through a polite live region (critical
findings assertively), severity is icon + word (never color alone), and evidence frames carry alt
text from the vision note.

Mock scenarios (demo-clock windows over the same day; default speed 60×, i.e. 1 s = 1 min):

| Button | Clock | What happens |
|---|---|---|
| Insulin on a freezing porch | 1:55 PM → 2:55 PM | 2:05 van, 2:07 Ring sees the package (16°F / −9°C) → text Rosa (Spanish) · 2:27 at risk (~20 min from freezing) → neighbor Luis · 2:37 → Ana (call Rosa or someone nearby) · 2:40 brought inside (simulated pickup), est. 33°F / 0.7°C, never froze → "good news" to Ana |
| Late & short visit | 8:50 AM → 10:20 AM | No check-in by 9:16 → agency alerted · check-in 9:22 (22 min late, simulated) · checkout 10:05 (43 of 120 min, simulated) at 21°F / −6°C → flagged to Ana + agency |
| Full day | 8:50 AM → 2:55 PM | Both of the above |

The page opens at 2:20 PM (insulin already on the porch) and ticks in real time; after a scenario ends the
clock keeps running at 1×. **Reset** jumps to 8:30 AM.

### Recording the demo video

The *Today* view puts the story above the fold on desktop (≥1280 px wide): status banner, then
*Care plan vs. reality* next to the featured card (medication while a package is outside, the visit card
while a visit needs attention). It is sized to fit a 1280×720 viewport without scrolling; at
≥1800×1000 the root font scales up so 1920×1080 renders the same layout ~1.4× larger. Press **D** to hide
the demo strip once a scenario is running. New findings/actions slide in with a short highlight; new
timeline markers pop in.

## Layout

```
app/            layout, page (server: probes backend, builds initial data), globals.css (design tokens)
components/     Dashboard, Header, StatusBanner, DayTimeline (hero), MedicationCard, VisitCard,
                Feeds (findings/actions), AgencyView, LedgerView, DemoStrip, EvidenceFrame, ui, icons
lib/types.ts    API contract types (see API_CONTRACT.md)
lib/api.ts      typed fetch client + SSE subscription
lib/useDoorLedger.ts  data hook: live/mock switching, polling, stream, demo controls, toasts
lib/derive.ts   shared status logic, labels, EVV CSV
lib/mock/       fixture day + mock engine + demo clock
lib/thermal.ts  exposure model port (mock only)
```

## Notes

- No Ring logos or Amazon trademarks are used; the UI only says "Ring doorbell" in text.
- No face recognition anywhere: aides are identified only by the rotating signed code they show to the doorbell.
- Temperatures are model estimates, labelled as such. °F first (US families) with °C alongside; click the
  outdoor temperature to swap which one is primary.
- Each action shows a small language tag (e.g. `ES`) when the backend sends `data.language`; messages to
  Rosa are in Spanish.
- Accessibility: base font 17px, text colors ≥ 4.5:1, visible focus rings, `aria-live` feeds, reduced-motion respected.
