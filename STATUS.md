# STATUS — decision log

This is the project's running log of status and decisions, newest first. Earlier sections are kept
as written at the time, so some numbers (for example test counts) are historical. For the current
picture, see the [README](README.md) and the latest review in [docs/reviews/](docs/reviews/).

## Current status (11 Oct 2026, night)
- `ringpartner` 0.1.0 is published on PyPI (https://pypi.org/project/ringpartner/), Apache-2.0.
- Hosted demo (dashboard with built-in mock data): https://doorledger.vercel.app
- The CareAgent runs on Bedrock AgentCore Runtime (see below).
- Open items from [review-03](docs/reviews/review-03.md) are being worked through. The main gap is
  own footage for the aide check-in and the package pickup ([shot list](docs/SHOT_LIST.md)); until
  then those steps are labelled `Simulated`.

## AgentCore ✅ DEPLOYED (11 Oct, 5:25 pm)
Stack `AgentCore-DoorLedgerAgent-dev`, runtime `DoorLedgerAgent_CareAgent-*` (us-east-1). `/api/ask` → AgentCore (Claude Haiku 4.5), ~7.6 s, 5/5 live tests. The ARN lives in `.env` (not in git). AWS pipeline: Bedrock (Nova 2 Lite for vision + Claude Haiku for messages) + Strands + AgentCore Runtime + DynamoDB + SNS (phone number not yet verified).

## Session 2 (11 Oct, afternoon) — after external review #1 (6.9/10)
- ✅ Claude Haiku 4.5 / Sonnet 4.6 enabled in Bedrock (Haiku 5.5 returns "not available for this account").
- ✅ Bilingual messages (Rosa gets Spanish), faces pixelated BEFORE Bedrock, only the event frame is stored, 30-day retention.
- ✅ Vision behind a motion gate (−38% to −60% calls). Burst mode on a doorbell press (presence check on every frame, 12 s). Ring history poller + snapshots.
- ✅ Exposure PDF for the pharmacy. Caregiver pass only with an agency token.
- ✅ Own-footage pipeline ready (ingest + code verification on replay). Critical bug fixed: `visit_id` must match `[A-Z0-9-]`.
- ✅ Root README, architecture (5 Mermaid diagrams), LICENSE/NOTICE, CI, Makefile.
- ✅ DynamoDB `doorledger-ledger` live (mirror). AgentCore packaged and tested locally; deployment was blocked by IAM at the time → steps in deploy/agentcore/README.md (since deployed, see above).
- ✅ +132 engine tests → 239 passed; 4 real bugs found and fixed.
- Hygiene: local tool config (`.claude/`) and unlicensed clips (Vehicle/Motion) removed from git.
- Demo story: winter in Chicago; the vehicle clip (spring) was dropped.

## Gate G1 — ✅ GREEN (11 Oct)
S1, S2, S3 and S5 passed; S4 adjusted (30–50 cm + compact code + 6-digit backup); S6 waits on a Telegram bot (not blocking: the dashboard shows the actions). Architecture frozen: Ring WHEP → Watcher (Nova 2 Lite + code reader) → PorchTracker → Engine (deterministic reconcile) → Responder (guardrails + Bedrock Writer) → Ledger → API/SSE → Dashboard; CareAgent (Strands) for Q&A and the daily summary.

## Phase 1 — Medication on the porch: nearly complete
- ✅ The full flow runs on REAL Ring Playground footage analysed by Bedrock (vehicle 14:05, package 14:07 → Rosa; 15:16 → Luis; 15:26 picked up → Ana).
- ✅ Signed Ring webhooks → watch session (live with a token, or with recorded footage depending on `sub_type`).
- ⏳ Still missing: the "package picked up" scene with own footage (shot list in docs/SHOT_LIST.md); dashboard with real evidence + Q&A (agent in progress).

## Phase 0 — Foundations and spikes (closed)

### Done
- Environment: uv, Python 3.12, AWS CLI (v1 via `uv tool`) installed.
- Repo `doorledger` (uv monorepo). Apache-2.0 license.
- **SDK `ringpartner`** complete: sync/async REST client, WHEP (aiortc), webhooks (HMAC verification), signed webhook simulator, fixture record/replay, CLI. 55 tests green, ruff clean, wheel built. 7 bugs fixed by the review agent (including a `security_token` leak in error messages).
- Core: `domain`, `exposure` (Newton thermal model), `porch` (k-of-n tracker), `ledger` (SQLite), `reconcile` (expected vs. observed), `weather` (Open-Meteo), `vision` (Bedrock Converse + stub). Smoke test OK: detects a late arrival, a short visit and compromised insulin.

### Spikes
| Spike | Status | Notes |
|---|---|---|
| S1 Playground | ✅ | "Playground Device" online, not encrypted. Fixtures recorded (devices, status, capabilities, configurations, location, history, users/me redacted). Snapshots work with `at=` set to the start of a history event (the "latest_in_range" range returns 403). |
| S2 Server-side WHEP | ✅ | aiortc → H264 1280x720, ~4 effective fps. The scene is chosen in the Playground UI (Package/Vehicle/Motion) and also applies to server-side sessions. Opening a new session before the previous one closes returns 500 → retry after a 20 s wait. MediaRecorder MP4 never finalizes (no `moov`) → we use frames + `cv2.VideoWriter`. Package clip: "Thief stealing our package" (YouTube, CC BY 4.0) → ATTRIBUTE in the video and README. |
| S3 Bedrock | ✅ | Nova 2 Lite + prompt v2: 54/54 on the synthetic set (eval/vision) and **10/10 on real Ring Playground frames** (package, vehicle, birds). ~$0.37/1k frames, p50 1.5 s. Claude was unavailable until Anthropic's use-case form was submitted (since enabled). |
| S4 Presence code | 🟡 ADJUSTED | Synthetic: 100% at 30–50 cm, 0% at 1 m (phone QR <2 px/module). Decision: instruct the aide "30–50 cm, hold still 2–3 s", 25-digit compact code (smallest QR, EC M), read every 2–3 frames, keep the 6-digit code as a backup read by vision. Still to validate with real footage (night IR, watermark). |
| S5 Strands | ✅ | `agent.py` (Strands 1.59 + BedrockModel). Family Q&A and daily summary with read-only tools; `notify` with guardrails in code. Claude Haiku 4.5 → fallback Nova Pro (Nova 2 Lite is not strong enough for the agent). ~$0.003/question, ~2 s. An agentic `handle()` exists but is opt-in; rules remain the default. |
| S6 Notifications | pending | |

### Decisions
- **G-S4:** the "≥95% at 1 m" criterion is not met → we adjust the HOW (30–50 cm distance + compact code + 6-digit backup), not the scope.
- Insulin: there is no minute limit above 8 °C (it keeps for weeks at room temperature); the real risk is going above ~30 °C. Stricter profiles (biologics) use `max_minutes_above_store`.
- Reconciliation is deterministic; the LLM only chooses actions and writes messages. The LLM never decides whether a visit happened.
