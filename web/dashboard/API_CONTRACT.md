# DoorLedger dashboard ⇄ backend API contract

The dashboard (Next.js, `web/dashboard`) talks to the FastAPI backend at `NEXT_PUBLIC_API_BASE`
(default `http://localhost:8787`). TypeScript source of truth: `lib/types.ts`. The mock engine
(`lib/mock/engine.ts`) produces exactly these shapes, so it doubles as a reference implementation.

All timestamps are ISO-8601 strings **with an offset** (`2026-10-11T13:12:40-04:00` or `...Z`).
The UI renders every time in `household.patient.timezone`.

CORS: the browser calls the API directly (and opens `EventSource` on `/api/stream`), so the backend
must allow origin `http://localhost:3000` (GET, POST, `Content-Type: application/json`).

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/household` | `Household` |
| GET | `/api/state?at=ISO` | `State` (`at` optional; omitted = now / current demo clock) |
| GET | `/api/timeline?since=ISO` | `LedgerRecord[]` (`since` optional) |
| GET | `/api/stream` | Server-Sent Events; each `data:` line is one JSON `LedgerRecord` |
| GET | `/api/evidence/{path}` | `image/jpeg` proof frame (`path` = `Observation.evidence_path`) |
| GET | `/api/evv.csv?date=YYYY-MM-DD` | `text/csv` download |
| POST | `/api/demo/run` body `{ "scenario": "porch_cold" \| "late_short_visit" \| "full_day", "speed": number }` (`porch_heat` = legacy alias of `porch_cold`) | `{ "ok": boolean }` |
| POST | `/api/demo/reset` | `{ "ok": boolean }` |

## Types

```ts
Household {
  id: string
  patient: { name: string, age: number, address: string, timezone: string }
  people: { name: string, role: "patient"|"family"|"neighbor"|"agency"|"caregiver", escalation_order: number,
            language?: "en"|"es", channel?: "sms"|"push"|"agency_portal"|null }[]
  device: { id: string, name: string, online: boolean|null, source: "ring_playground"|"ring_api"|"replay" }
  ambient: { celsius: number, source: "open-meteo"|"override"|"fallback" }
}

State {
  now: ISO
  visits: { expectation: Expectation, check_in: Observation|null, check_out: Observation|null, minutes_on_site: number|null }[]
  deliveries: {
    expectation: Expectation, dropped: Observation|null, removed: Observation|null,
    estimate: { minutes_on_porch: number, ambient_c: number, estimated_internal_c: number,
                minutes_until_excursion_max: number|null,   // minutes until the RELEVANT limit (see direction)
                status: "safe"|"at_risk"|"compromised",
                direction?: "hot"|"cold"|null,              // cold = heading to freeze_c, hot = to excursion_max_c
                unsafe_c?: number|null } | null             // 0.0 for cold, 30.0 for hot
  }[]
  findings: Finding[]
  actions: Action[]
}

LedgerRecord { id: string, kind: "expectation"|"observation"|"finding"|"action"|"ring_event", subtype: string, at: ISO, ref: string|null, body: object }

RingEvent /* body of a ring_event record: a Ring history row the live poller acted on (live token only) */ {
  id, event_type: "ding"|"on_demand"|"motion"|string, at: ISO, end: ISO|null, device_id,
  source: "ring_history", action: "watch"|"burst watch"
}

Expectation {
  id, kind: "caregiver_visit"|"medication_delivery", title, window_start: ISO, window_end: ISO,
  caregiver?, agency?, planned_minutes?, visit_id?, carrier?, tracking?,
  medication?: { name, store_min_c, store_max_c, excursion_max_c, freeze_c? /* 0.0 */ }
}

Observation {
  id, kind: "package_dropped"|"package_removed"|"person_at_door"|"vehicle_arrived"|"presence_check_in"|"presence_check_out",
  at: ISO, source: "ring_live_view"|"ring_snapshot"|"ring_webhook"|"own_footage"|"simulated",
  confidence: number /* 0..1 */, device_id?, visit_id?, evidence_path?, detail: object
}

Finding {
  id, kind: "on_time"|"late_arrival"|"missed_visit"|"short_visit"|"visit_completed"|"package_exposed"|"package_at_risk"
          |"package_compromised"|"package_retrieved"|"delivery_overdue"|"unexpected_activity",
  severity: "info"|"warning"|"critical", at: ISO, summary: string, expectation_id?, observation_ids: string[], data: object
}

Action {
  id, kind: "notify"|"request_backup"|"export_evv"|"summary", target: string, message: string, at: ISO,
  finding_id?, delivered: boolean, data: object
}
```

## Conventions the UI relies on (optional fields inside the free-form objects)

These are not required, but the UI renders them when present:

- `LedgerRecord.body` is the full `Expectation` / `Observation` / `Finding` / `Action` object; for
  observations, `ref` is the related expectation id.
- `Observation.detail.caregiver` (string) and `detail.backup` (bool) on presence check-in/out — shown
  as the provider name (EVV "individual providing service").
- `Observation.detail.description` — one-line human description (timeline + ledger).
- `Observation.detail.expectation_id` on `package_dropped` / `package_removed`.
- `Observation.detail.in_sun` (bool) on `package_dropped`.
- `Action.target` should be a `people[].name` (e.g. `"Luis Ortega"`) so the UI can say "Called neighbor Luis".
- `Action.data.channel`: `"sms" | "voice" | "push" | "email" | "agency_portal"` → verb ("Texted", "Called", …).
  It is the household's channel for that person (`people[].channel`; Rosa uses no app, so `"sms"`).
- `Action.data.via`: what actually carried the message in this run: `"sms"` (Amazon SNS), `"telegram"`,
  or `"app"` (console only, nothing was sent). When it differs from `channel` the UI explains it, and
  `via: "app"` shows "Demo only" instead of "Delivered".
- `Observation.detail.vision_model` / `vision_ms`: Bedrock model id and latency of the vision call that
  labelled the frame → "Nova 2 Lite · 1.2 s" on the evidence card. `vision_cached: true` = replayed from
  the recorded vision cache ("recorded"); `vision_reused: true` = unchanged frame reused the last label.
  Absent fields are never filled in by the UI.
- `Action.data.status`: `"no_answer" | "answered"`; `Action.data.reply`: string (e.g. `"On my way"`).
- `Action.data.language`: `"es" | "en"` → small language tag on the action (messages to Rosa are Spanish).
- `Action.data.channel` may also be `"telegram"` → "Messaged …".
- Observations with `source: "simulated"` should have no `evidence_path`; the UI shows a "No camera frame"
  panel (never an illustration) and labels `detail.note` as "Note:" instead of "Vision:".
- If an estimate has no `direction` (older backend), the UI derives it: outside < `store_min_c` → cold,
  outside > `store_max_c` → hot.

## Visit status (`lib/derive.ts#visitStatus`)

Backend findings for the visit win when present: `short_visit` → short, `visit_completed` → completed,
`missed_visit` → missed, `late_arrival` (warning) → late. Otherwise derived with the same thresholds as
`core/src/doorledger/reconcile.py`: checked in + out → `short` if on site < 75% of planned, else `completed`;
checked in only → `in_progress`; before window → `scheduled`; > 45 min past start → `missed`;
> 15 min → `late`; otherwise `awaiting`.

Findings are recorded once per (expectation, kind, severity), so a late aide produces a `late_arrival`
warning ("not here yet") and later a `late_arrival` info ("checked in 22 min late"). The UI shows only the
latest finding per (expectation, kind) (`latestFindings`).

## CareAgent (Bedrock, read-only tools)

| Method | Path | Response |
|---|---|---|
| POST | `/api/ask` body `{ "question": string }` | `{ answer, tool_calls: {name, input}[], model, latency_ms, usage }`; 503 if no model |
| GET | `/api/summary` | `{ summary, tool_calls, model, latency_ms, usage }`; 503 if no model |

Both cost money, so the UI only calls them on an explicit click. Mock mode answers from the fixture
day with canned, state-aware text and fake `tool_calls`.

Evidence: `Observation.evidence_path` is e.g. `evidence/captured/20261011T140702_f_x.jpg`; the UI loads
`${API}/api/evidence/${evidence_path}` (the route strips one leading `evidence/`). `detail.note` is the
vision model's description and is shown as "Vision: …".

## EVV CSV columns (mock export; backend should match)

`visit_id, service_type, individual_receiving_service, date, location, individual_providing_service,
time_in, time_out, minutes_on_site, planned_minutes, verification_method, status`
