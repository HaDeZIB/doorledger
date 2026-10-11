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
(the browser re-probes once on mount; the demo strip has *Retry API* / *Use mock*). A fixture day for a
fictional household (Rosa Martínez, 81, Tampa FL; aide Maria Gómez, BrightPath Home Care; insulin from
CVS Specialty) is generated for *today* in America/New_York. A client-side **demo clock** drives it:
state at any instant is derived from the fixture (`lib/mock/engine.ts`), and the porch temperature is
computed with a TypeScript port of `core/src/doorledger/exposure.py` (Newton heating, sun halves tau).
Proof frames are drawn as labelled illustrations; EVV CSV is generated in the browser.

Mock scenarios (demo-clock windows over the same day; default speed 60×, i.e. 1 s = 1 min):

| Button | Clock | What happens |
|---|---|---|
| Insulin on a hot porch | 1:05 PM → 2:36 PM | Drop at 1:12 PM in 94°F sun · text Rosa · call unanswered · at-risk at 2:17 PM → call neighbor Luis + notify Ana · box taken inside 2:26 PM (est. 28.7°C peak, under the 30°C limit) |
| Late & short visit | 8:55 AM → 10:15 AM | No check-in by 9:20 → agency + family alerted · check-in 9:41 (41 min late) · checkout 10:08 (27 of 60 min) → flagged |
| Full day | 7:00 AM → 7:45 PM | Both of the above + evening visit missed → backup aide requested → backup checks in 6:06 PM, completes · EVV export + daily summary |

The page opens at 2:05 PM (insulin already on the porch) and ticks in real time; after a scenario ends the
clock keeps running at 1×. **Reset** jumps to 7:00 AM.

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
- Temperatures are model estimates, labelled as such. Units toggle °F/°C by clicking the outdoor temperature.
- Accessibility: base font 17px, text colors ≥ 4.5:1, visible focus rings, `aria-live` feeds, reduced-motion respected.
