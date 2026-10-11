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
| POST | `/api/demo/run` body `{ "scenario": "porch_heat" \| "late_short_visit" \| "full_day", "speed": number }` | `{ "ok": boolean }` |
| POST | `/api/demo/reset` | `{ "ok": boolean }` |

## Types

```ts
Household {
  id: string
  patient: { name: string, age: number, address: string, timezone: string }
  people: { name: string, role: "patient"|"family"|"neighbor"|"agency"|"caregiver", escalation_order: number }[]
  device: { id: string, name: string, online: boolean|null, source: "ring_playground"|"ring_api"|"replay" }
  ambient: { celsius: number, source: "open-meteo"|"override"|"fallback" }
}

State {
  now: ISO
  visits: { expectation: Expectation, check_in: Observation|null, check_out: Observation|null, minutes_on_site: number|null }[]
  deliveries: {
    expectation: Expectation, dropped: Observation|null, removed: Observation|null,
    estimate: { minutes_on_porch: number, ambient_c: number, estimated_internal_c: number,
                minutes_until_excursion_max: number|null, status: "safe"|"at_risk"|"compromised" } | null
  }[]
  findings: Finding[]
  actions: Action[]
}

LedgerRecord { id: string, kind: "expectation"|"observation"|"finding"|"action", subtype: string, at: ISO, ref: string|null, body: object }

Expectation {
  id, kind: "caregiver_visit"|"medication_delivery", title, window_start: ISO, window_end: ISO,
  caregiver?, agency?, planned_minutes?, visit_id?, carrier?, tracking?,
  medication?: { name, store_min_c, store_max_c, excursion_max_c }
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
- `Action.data.status`: `"no_answer" | "answered"`; `Action.data.reply`: string (e.g. `"On my way"`).

## Visit status (derived in the UI, `lib/derive.ts#visitStatus`)

checked in + out → `short` if on site < 75% of planned, else `completed`; checked in only → `in_progress`;
before window → `scheduled`; > 30 min past start or past window end → `missed`; > 15 min → `late`;
otherwise `awaiting`.

## EVV CSV columns (mock export; backend should match)

`visit_id, service_type, individual_receiving_service, date, location, individual_providing_service,
time_in, time_out, minutes_on_site, planned_minutes, verification_method, status`
