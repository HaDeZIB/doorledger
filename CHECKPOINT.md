# CHECKPOINT — pause on 11 Oct 2026, 3:30 pm (UTC−6)

> Historical snapshot, kept for the build record. Numbers and open items below are as of that
> afternoon; see [STATUS.md](STATUS.md) and the [README](README.md) for the current state.

## 1. What is built and working
| Piece | Status | Where |
|---|---|---|
| Open-source SDK `ringpartner` (sync/async REST, WHEP, HMAC webhooks, signed simulator, record/replay, CLI) | ✅ 55 tests | `packages/ringpartner/` |
| Presence codes (signed rotating QR + compact + 6 digits) and OpenCV reader | ✅ 26 tests, synthetic eval | `core/.../presence*.py`, `eval/presence/` |
| Caregiver Pass (mobile web, JS↔Python parity tested) | ✅ | `web/caregiver-pass/index.html`, served at `/pass` |
| Bedrock vision (Nova 2 Lite + prompt v2) | ✅ 54/54 synthetic, 10/10 real Ring | `core/.../vision.py`, `eval/vision/` |
| Watcher: Ring frames → vision + codes → k-of-n PorchTracker → Engine | ✅ | `core/.../watcher.py` |
| Engine + deterministic reconciliation + thermal model (heat **and freezing**) | ✅ | `engine.py`, `reconcile.py`, `exposure.py` |
| Responder with guardrails + Bedrock Writer (Claude → Nova → templates) | ✅ | `responder.py` |
| Strands CareAgent (family Q&A + daily summary, Claude → Nova Pro) | ✅ 12 tests | `agent.py`, `docs/agent_spike.md` |
| Live controller: signed Ring webhooks → watch session; watching during care windows | ✅ | `live.py`, `POST /webhooks/ring` |
| FastAPI API + SSE + EVV CSV + demo runner | ✅ | `api.py` |
| Next.js dashboard (Today / Agency / Ledger, Ask, summary, real evidence) | ✅ build OK | `web/dashboard/` |
| Real Ring Playground footage (package, vehicle, motion) | ✅ | `fixtures/ring_playground/` (package clip is CC BY 4.0 → attribute) |
| Friction log | ✅ 8 entries | `FRICTION_LOG.md` |

**Tests:** 93 passed, 1 skipped (`uv run pytest -q`).

**Running the demo:** API on port 8787 (`make api` or `make api-offline`) and dashboard on port
3000 (`make dashboard`) → open the dashboard → press **D** → pick a scenario.

## 2. Demo story (decided 11 Oct)
Winter in Chicago: insulin is left on a porch at −9 °C (the Ring Playground package clip is a snowy doorstep). 14:07 Ring sees the package → alert to Rosa; 14:27 at risk of freezing → neighbor Luis; 14:37 → Ana (daughter); 14:40 picked up → update to Ana. Morning: Maria (the aide) arrives 22 min late and stays 43/120 min → agency and family.

## 3. What was still missing (by priority)
1. **Own footage** (docs/SHOT_LIST.md): aide with the QR (check-in/out) + package picked up → replaces the `SIMULATED` steps. When filming: fix the visit secret in `fixtures/own_footage/visit.json` and `recorded_start` so codes can be verified on replay.
2. **Claude on Bedrock:** model access was pending Anthropic's use-case form. Note: the 5.5 models reject `temperature: 0` (vision.py sends it).
3. **Telegram (S6):** a bot token and chat id in `.env` (`TELEGRAM_BOT_TOKEN`).
4. **Dashboard:** mock mode still said Tampa/heat → switch to Chicago/winter; scenario name `porch_cold` (alias `porch_heat` exists); show "limit: freezing 32 °F" when `estimate.direction == "cold"` (new fields `direction`, `unsafe_c`).
5. **Main README** + architecture diagram + CC BY attribution + run guide.
6. **AWS Builder (multi-service):** deploy the agent on Bedrock AgentCore Runtime (plan in `docs/aws_architecture.md`), mirror the ledger to DynamoDB, webhook receiver on Lambda/API Gateway.
7. **Open Source:** public GitHub repo, publish `ringpartner` to PyPI, CI with GitHub Actions.
8. **Video (<3 min, English)** + Devpost text + per-tool feedback.

## 4. Improvement ideas from the review (for the next round)
- **Bilingual messages:** Rosa gets Spanish, Ana gets English (a Hispanic family; shows we understand the end user). A per-person `language` field → the Writer writes in that language.
- **Privacy by design:** blur faces in stored evidence frames (keep only what is needed to prove the event). Highly valued by a Ring panel.
- **Evidence pack for the pharmacy:** a PDF with the timeline, estimated temperature and Ring frames → a one-click replacement claim.
- **Vision cost:** classify only when there is motion (frame difference) and drop to 1 frame every 3 s when the porch is stable; cheap pre-filter with Nova Lite.
- **Multi-camera** (Ring's creativity criterion): a second camera (garage) for "vehicle arrived" + the door for "package". The Playground has only 1 device, but the SDK already supports `component_id`.
- **Threshold (v2):** "time to open the door" / walking speed as a frailty signal.
- **Rate limit** on presence codes per doorbell press (risk noted in eval/presence).
- **Weekly report** for the agency: % of visits verified, minutes delivered vs. billed.
