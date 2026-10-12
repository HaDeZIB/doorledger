# DoorLedger

> **Care is delivered through the front door. DoorLedger makes sure it arrived.**

DoorLedger turns a Ring doorbell into a witness for home care. It compares the care that was
**expected** at an older adult's front door with what the doorbell **observed**. Expected care
means caregiver visits and temperature-sensitive medication deliveries. DoorLedger acts only
when the two differ: an aide who never checked in, a 2-hour visit that lasted 43 minutes, or
insulin left on a freezing porch.

Built for the Amazon Developer Hackathon **"Build, Ship, Shape"**: Ring track, plus the
**Open Source** and **AWS Builder** mini-challenges.

| | |
|---|---|
| **Demo video** | **TODO:** _YouTube/Vimeo link, under 3 min_ |
| **Hosted demo** | **[doorledger.vercel.app](https://doorledger.vercel.app)**: replays a recorded winter day for a fictional household (no backend, no login). Press **D** for demo controls |
| **Ring** | Partner API REST (devices, status, capabilities, configurations, history, snapshots), server-side **WHEP live view**, **signed webhooks**. Developed against the Ring Developer Playground |
| **AWS** | Amazon Bedrock: **Nova 2 Lite** (vision) and **Claude Haiku 4.5** (messages, agent; Nova fallback). **Strands Agents** CareAgent. **DynamoDB** ledger mirror (live). **Amazon SNS** SMS (sandbox). **AgentCore Runtime** (deployed; `/api/ask` and `/api/summary` run there) |
| **Open source** | [`ringpartner`](https://github.com/HaDeZIB/ringpartner) ([PyPI](https://pypi.org/project/ringpartner/): `pip install ringpartner`): the Python SDK for the Ring Partner API that Ring doesn't ship. Apache-2.0, with [examples](packages/ringpartner/examples) |
| **Business model** | [docs/BUSINESS.md](docs/BUSINESS.md): Ring Appstore pricing, measured unit economics, agency EVV value |
| **Tests** | `uv run pytest -q`: **244 passed**, 2 skipped (live AWS tests are opt-in). No AWS credentials or network needed |

> **Built with Claude Code** (Anthropic Claude via Amazon Bedrock) during the hackathon window.

---

## Contents

- [What's real vs. simulated in the demo](#whats-real-vs-simulated-in-the-demo)
- [The problem](#the-problem)
- [How it works](#how-it-works)
- [Ring integration](#ring-integration)
- [AWS usage](#aws-usage)
- [Open-source SDK: ringpartner](#open-source-sdk-ringpartner)
- [Quickstart](#quickstart)
- [Evaluation results](#evaluation-results)
- [Privacy and safety](#privacy-and-safety)
- [Limitations and what's next](#limitations-and-whats-next)
- [Repository map](#repository-map)
- [Attribution and licensing](#attribution-and-licensing)

## What's real vs. simulated in the demo

Every observation carries its source, and the dashboard shows it as a badge.

| Piece | In the demo | Notes |
|---|---|---|
| **Package left at 14:07** | **Real Ring footage.** Frames captured from the Ring Developer Playground over WHEP on 2026-10-11 (`fixtures/ring_playground/package/`), re-timed into the scenario | With AWS, Nova 2 Lite re-detects the package live. Offline (`make api-offline`), the same frames go through the same pipeline using the labels Bedrock produced for them (`fixtures/ring_playground/vision_cache.json`). A cache miss returns an empty scene, never an invented detection |
| **Aide check-in 09:22, check-out 10:05** | **Simulated** (`simulated` badge) | The Playground has no scene of an aide with a phone. Own footage is planned ([shot list](docs/SHOT_LIST.md)). The presence-code path is covered by unit tests and a synthetic camera eval |
| **Package brought inside 14:40** | **Simulated** | No Playground scene for a pickup. Own footage planned |
| **Ring webhooks** | **Simulated delivery** through the real handler | The Playground sends no webhooks. `ringpartner simulate` signs documented v1.1 payloads with your HMAC key, and `/webhooks/ring` verifies them unchanged |
| **Ring history poller + event-time snapshots** | Real code path, not part of the offline demo | Needs a live Playground token (`POST /api/live/watch`) |
| **Vision labels** | Real Amazon Bedrock (Nova 2 Lite), or Bedrock's recorded labels offline | |
| **Message wording** | Claude Haiku 4.5 on Bedrock (live), then Nova Lite, then a template | The offline demo uses templates (`DOORLEDGER_WRITER=template`) |
| **CareAgent Q&A and daily summary** | Real Strands agent on Bedrock (Claude Haiku 4.5, Nova Pro fallback) | Needs AWS credentials |
| **SMS** | Amazon SNS, implemented; sandbox | Delivered only to the one verified demo phone in `DOORLEDGER_SMS_TO`. Without it, messages appear in the dashboard only |
| **DynamoDB ledger mirror** | Live (table `doorledger-ledger`) | Off unless `DOORLEDGER_DYNAMO=1` |
| **AgentCore Runtime** | **Deployed** (us-east-1, CloudFormation stack `AgentCore-DoorLedgerAgent-dev`); live tests 5/5 | `/api/ask` returns `"runtime": "agentcore"` (Claude Haiku 4.5, ~7.6 s round trip); falls back to the in-process agent on any error ([details](deploy/agentcore/README.md)) |
| **Temperature inside the box** | **Model estimate**, never a measurement | Newton's-law model with documented assumptions. The scenario fixes ambient at −9 °C |
| **People and household** | Fictional (Rosa, Maria, Luis, Ana, "BrightPath" agency) | |
| **6-digit fallback code, privacy zones, E2EE skip** | Implemented, not exercised in the demo | No own footage yet. The Playground device has no privacy zones and E2EE off |

## The problem

When an older adult lives alone, most of their care arrives through the front door: the home
health aide, the nurse, prescriptions, meals. Families who live far away can't tell whether
the aide came, how long she stayed, or whether the insulin has been sitting on the porch for
two hours. Agencies and payers can't fully tell either.

- **Visits go unverified.** The New York State Comptroller's audit **2022-S-31** (issued November
  2024) found about **US$14.5 billion** in Medicaid personal care claims, about 82 million
  services with service dates from January 2021 to March 2023, that had **no matching Electronic
  Visit Verification (EVV) record**.
  ([report](https://www.osc.ny.gov/files/state-agencies/audits/pdf/sga-2025-22s31.pdf),
  [summary](https://osc.ny.gov/state-agencies/audits/2024/11/13/medicaid-program-provider-compliance-electronic-visit-verification-program))
  *Caveats:* the Department of Health disputed about US$2.7 billion of that tally, and the audit
  measures missing verification, not proven fraud. Texas OIG describes the patterns that
  verification is meant to catch, including aides clocking in without showing up and
  aide-patient collusion.
  ([Texas OIG](https://oig.hhs.texas.gov/about-us/news/oig-educates-home-health-care-providers-about-visit-documentation))
- **Mail-order medication sits outside.** A 2023 study in the *Journal of the American
  Pharmacists Association* found that **simulated** mail-order shipments spent **68% of the
  time outside the labeled temperature range**.
  ([summary](https://www.beckershospitalreview.com/pharmacy/heat-spells-trouble-for-mail-order-medications/))
  *Caveat: these were simulated shipments in hot conditions, reported through a secondary
  source. They are not a measured national rate.*
- **Insulin users are the people at risk.** About **8.4 million Americans use insulin**, an
  American Diabetes Association figure cited in a December 2024 congressional letter to USPS
  and the Postal Regulatory Commission about mail-order medications.
  ([letter](https://sylviagarcia.house.gov/sites/evo-subsites/sylviagarcia.house.gov/files/evo-media-document/Congressional_Letter_USPS_PRC_Mail_Order_Medications_20241216.pdf))
  Insulin that has frozen must be discarded, and sustained heat above about 30 °C degrades
  it. *Caveat: not every insulin user receives it by mail.*

The Ring doorbell is the one device in the home that sees all of this. Until now, nobody has
used it to check that the care actually arrived.

## How it works

```
 Day plan (EXPECTED)                    Ring doorbell (OBSERVED)
 visits · deliveries                    history · snapshots · live view · webhooks
        │                                        │
        │       Watcher: privacy zones masked → faces pixelated → Nova 2 Lite vision
        │                + signed-code reader (QR, or 6-digit code read by vision)
        │                                        │  (k-of-n debounced)
        └──────────────► reconcile (deterministic) ◄───┘
                                 │ Findings: late · missed · short · package at risk …
                                 ▼
                 Responder: escalation ladder + guardrails
                 Writer (Claude Haiku 4.5 → Nova Lite → template)
                                 │
          Ledger (append-only) ──► Dashboard (SSE) · EVV CSV · CareAgent Q&A · SMS (SNS)
                     └──► DynamoDB mirror (optional)
```

Full component and sequence diagrams: **[docs/architecture.md](docs/architecture.md)**.

1. **Expected vs. observed.** The day plan holds expectations, such as "Maria, morning personal
   care, 09:00–11:00, 120 min" or "Insulin refill, UPS, 13:00–17:00". Perception turns doorbell
   frames into observations: `package_dropped`, `package_removed`, `vehicle_arrived`,
   `presence_check_in/out`. `reconcile()` is a pure, unit-tested function that compares the two
   and produces findings.
2. **Expectation-guided sensing.** DoorLedger doesn't record the door all day. It looks only
   while care is expected (±30 min around a window):
   - **With a live Ring token, it is event-driven.** It polls Ring event history every 15 s.
     For each new Ring event it fetches a **snapshot at the event's start time** and
     classifies it (source `ring_snapshot`), then opens a short live view.
   - **A doorbell press switches to burst mode.** Live view samples at 4 fps for about 12 s,
     and the code reader runs on every frame, so an aide holding her pass for 2–3 s gets
     about 10 read attempts. The intended aide flow is "press the doorbell, then show your
     pass".
   - **Signed Ring webhooks** (`motion_detected`, `button_press`) trigger the same sessions.
   - **A motion gate** skips the vision call when the scene hasn't changed. That cut vision
     calls by **38–60%** in our replay runs.
3. **A verifiable check-in signal instead of face recognition.**
   - Each visit gets a 32-byte secret. The aide's **Caregiver Pass** is a static web page, and
     the secret travels in the URL fragment, so it never reaches a server.
   - The pass shows a QR code that changes every 15 s. The code is an HMAC over the visit, the
     time step and the role (check-in or check-out). The aide holds the phone 30–50 cm from
     the doorbell for 2–3 seconds.
   - The backend verifies the MAC and the time step, and rejects replays.
   - **Fallback:** if the QR is too small to decode, the vision model reads the pass's 6-digit
     code (`phone_code_digits`). It is verified the same way and rate-limited to 10 attempts an
     hour per door.

   What this establishes: **a device showing the visit's current signed code was at the door.**
   It does not identify the person holding it, and nobody's face is recognised.
4. **Thermal exposure model.** A package on the porch is modelled as a lumped body moving
   toward ambient temperature (Newton's law). Ambient comes from Open-Meteo, and the time
   constant changes with sun or shade. The model estimates the temperature inside the box and
   the time left until the heat limit (30 °C) or freezing (0 °C) for insulin. These are
   **estimates, labelled as estimates**, meant as an early warning with evidence, not a lab
   measurement.
5. **Deterministic decisions, LLMs for words.**
   - **Code decides what happened:** whether a visit happened, whether it was late or short,
     and whether a package is at risk.
   - **Code decides who may be contacted:** patient → neighbor → family, with at least 10 min
     between rungs and at most 5 messages per incident. Caregivers are never contacted
     directly.
   - **LLMs only do three things:** **perceive** frames (Nova 2 Lite), **phrase** messages in
     each person's language (Claude Haiku 4.5, then Nova Lite, then a template, so an alert is
     never blocked), and **answer questions** (CareAgent).
   - **The agent is fenced in.** Its Q&A mode gets read-only tools. Its optional action mode
     goes through the same guardrail code, and refusals come back to the model as tool results.
6. **Bilingual by person.** Each household member has a language. Rosa gets Spanish, and her
   daughter Ana and the neighbor get English.
7. **One ledger.** Every expectation, observation, finding and action is appended to the
   ledger. The dashboard, the family summary, the EVV export and the pharmacy exposure report
   all read from it.
   - **EVV export:** the six 21st Century Cures Act fields plus the verification method and
     evidence.
   - **Exposure report** (`claims.exposure_report()`): a one-page PDF with the Ring frame, the
     time outside, the estimated box temperature and who was notified.

**Demo story (Chicago, winter).** Rosa, 81, lives alone.
- **Morning.** Her aide Maria arrives 22 minutes late and stays 43 of 120 planned minutes.
  DoorLedger alerts the agency and her daughter Ana.
- **14:07.** The Ring doorbell sees an insulin package left on a snowy step at −9 °C.
  DoorLedger texts Rosa in Spanish.
- **14:27 and 14:37.** The model estimates the box will freeze, so DoorLedger asks the neighbor
  Luis, then tells Ana.
- **14:40.** The box is brought inside (estimated 0.7 °C in the box), and Ana gets a summary
  she can question in plain language.

## Ring integration

| Ring capability | How DoorLedger uses it | Where |
|---|---|---|
| `GET /v1/devices?include=status,capabilities,configurations,location` | Discover the doorbell to watch. Before any video is touched, DoorLedger reads its **privacy zones** (`configurations.image_enhancements.privacy_zones`) and its **E2EE flag** (`configurations.e2e_encryption`). E2EE devices are skipped | `ringpartner.RingClient.devices()`, `live._prepare_device` |
| `status`, `capabilities`, `configurations`, `location` | Device detail. Recorded from the Playground as fixtures | `fixtures/playground/` |
| **History** (`/v1/history/devices/{id}/events`) | A poller during care windows: each new Ring event (motion, ding, Playground `on_demand`) triggers a snapshot and a live view. The SDK supports `event_types` filters (plural, comma-separated, e.g. `motion.human`) and `links.next` pagination. The poller currently reads the newest page unfiltered | `live._poll_history_loop`, `ringpartner.iter_history()` |
| **Snapshots** at a history event timestamp (`at=`) | Classified through the same perception pipeline (source `ring_snapshot`). The Playground rejects range requests with 403, while `at=<event start>` works (friction log F7) | `live._classify_snapshot`, `ringpartner.snapshot()` |
| **WHEP live view, server-side** | The main sensor. `aiortc` negotiates a `recvonly` session from Python and decodes H.264 to NumPy frames for vision and code reading. Sessions are capped at 30–60 s, so DoorLedger opens short sessions per event (25 s at 1 fps, or a 12 s, 4 fps burst after a doorbell press) | `ringpartner.whep.WhepSession`, `watcher.RingLiveSource`, `live.py` |
| **Signed webhooks** (`motion_detected`, `button_press`, `device_online/offline`) | `POST /webhooks/ring` verifies `X-Signature` (HMAC-SHA256 over the raw body), dedupes on `request_id`, answers within 5 s, and starts a watch session in the background. `button_press` starts burst mode | `api.py`, `live.py`, `ringpartner.verify_and_parse` |

**The Ring Developer Playground is the simulator.** It provides one doorbell, a WHEP live view
with three scenes (Package, Vehicle, Motion/bird feeder), snapshots, history and status.
DoorLedger uses only the **Package** scene; the other two clips carry no redistribution license
and are not in this repository. The Playground **does not deliver webhooks**, so
`ringpartner simulate` builds documented v1.1 payloads, signs them with your HMAC key and posts
them. The production handler runs unchanged, signature check included. Our
[friction log](FRICTION_LOG.md) has 17 entries for the Ring and AWS teams, ordered by severity.

The Playground's Package scene is a clip credited by Ring as *"Thief stealing our package"*
(CC BY 4.0, clipped). See [Attribution](#attribution-and-licensing).

## AWS usage

| Service | What it does in DoorLedger | Model / status |
|---|---|---|
| **Amazon Bedrock, Converse API, image input** (`vision.py`) | Labels each sampled doorbell frame as strict JSON (`package_visible`, `person_present`, `person_carrying_package`, `vehicle_present`, `phone_screen_shown`, `phone_code_digits`). It reports facts only and makes no judgement about the visit. Frames are privacy-masked and face-pixelated first | **Amazon Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`), prompt v2. In our eval it tied Nova Pro on accuracy at about **1/7 of the cost** (about $0.37 per 1k frames, p50 1.5 s). See [eval/vision](eval/vision/RESULTS.md) |
| **Amazon Bedrock, Converse API, text** (`responder.BedrockWriter`) | Rewrites each templated alert into a short, warm SMS in the recipient's language, using only the facts it is given | **Claude Haiku 4.5** (live), then **Nova Lite**, then a template |
| **Strands Agents SDK on Bedrock** (`agent.py`) | **CareAgent**: family Q&A ("Did Maria come today?") and the end-of-day summary, grounded in ledger tools. An optional `handle()` mode chooses actions through guarded tools | **Claude Haiku 4.5** (live; about 2.7 s and $0.0045 per question, measured), then **Nova Pro** (about 2 s and $0.003 per question; [agent spike](docs/agent_spike.md)). Nova 2 Lite was rejected for the agent: it over-called tools and made one false claim |
| **Amazon DynamoDB** (`aws/dynamo.py`) | Durable mirror of the append-only ledger. One partition per household, sorted by UTC time, TTL expiry | **Live**, table `doorledger-ledger` (on demand). Env-gated: `DOORLEDGER_DYNAMO=1` |
| **Amazon SNS** (`notify.SNSNotifier`) | SMS for alerts. A message counts as `delivered` only when a real channel (SMS or Telegram) succeeded | **Implemented, sandbox.** One verified demo phone in `DOORLEDGER_SMS_TO` |
| **Amazon Bedrock AgentCore Runtime** (`deploy/agentcore/`, `aws/agentcore.py`) | The same CareAgent, invoked with `InvokeAgentRuntime`, receiving a read-only household snapshot so the runtime can never message anyone | **Deployed and live** (5/5 live tests). `DOORLEDGER_AGENTCORE_ARN` switches `/api/ask` and `/api/summary` to it, with fallback to the local agent ([details](deploy/agentcore/README.md)) |
| IAM, AWS Budgets | Least-privilege dev user and a US$30/month budget with alerts | Total Bedrock spend during development: about US$2.5 |

**Model choice is backed by measurement.** The Nova vs. Claude split comes from
[eval/vision](eval/vision/RESULTS.md) (11 runs × 54 frames) and the
[agent spike](docs/agent_spike.md). The vision eval covers Nova models only, because the
account's Anthropic use-case approval was still pending when it ran
([friction log A1](FRICTION_LOG.md#a1--claude-on-bedrock-is-gated-by-the-anthropic-use-case-form-with-a-resourcenotfoundexception)).
Claude Haiku 4.5 has since become available and now writes the messages and answers CareAgent
questions. A **Lambda** webhook receiver is designed but not deployed. See
[docs/aws_architecture.md](docs/aws_architecture.md).

**Cost per household.** With event-driven sensing during expected windows, vision costs about
**US$1.1–1.8 per household per month**. Always-on would cost US$384–595. The full cost model and
margins are in [docs/BUSINESS.md](docs/BUSINESS.md).

## Open-source SDK: ringpartner

Ring's docs say it plainly: *there is no official Ring Partner SDK*. Every partner rebuilds
JSON:API parsing, the 303 pre-signed media flow, WHEP negotiation and HMAC verification.
[`ringpartner`](packages/ringpartner) packages those pieces (Python ≥3.10, Apache-2.0, 55
tests):

- **REST client, sync and async.** Typed models, `included` resolution, typed errors, 429
  back-off that honours `Retry-After`, `event_types` history filters with pagination, and
  two-step media downloads (the pre-signed URL is fetched *without* the `Authorization`
  header).
- **Server-side WHEP live video** (`[whep]` extra, aiortc + PyAV). It finishes ICE gathering
  before the POST, which avoids the undocumented HTTP 500. It reads the codec from the SDP
  answer and yields NumPy frames.
- **Webhook verification** (`X-Signature: sha256=…`, constant-time compare) and v1.1 parsing
  with a dedupe key.
- **Signed webhook simulator** for all 10 event types, because the Playground sends none.
- **Record/replay transports**, so you can keep developing after the 30-minute Playground
  token expires. Fixtures never contain the bearer token or the pre-signed `security_token`.
- **CLI:** `ringpartner devices | history | snapshot | record | capture-fixtures | simulate | verify`.
- **[Examples](packages/ringpartner/examples):**
  - devices and history with `event_types`;
  - WHEP frames into OpenCV;
  - a stdlib webhook receiver tested with the simulator (`python webhook_receiver.py --self-test`).

```bash
pip install ringpartner            # on PyPI: https://pypi.org/project/ringpartner/
pip install 'ringpartner[whep]'    # adds live video
```

See [packages/ringpartner/README.md](packages/ringpartner/README.md) and its
[CHANGELOG](packages/ringpartner/CHANGELOG.md).

## Quickstart

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node 20+ (CI uses Node 24).
`make help` lists every target.

```bash
git clone https://github.com/HaDeZIB/doorledger && cd doorledger   # TODO: repo goes public at submission
uv sync --all-packages                 # core + ringpartner + dev tools
cp .env.example .env                   # all values optional for the offline demo
(cd web/dashboard && npm ci)
```

**Run the demo with no AWS and no network.** It uses template messages, plus real Ring frames
with Bedrock's recorded labels:

```bash
make api-offline      # DOORLEDGER_PERCEPTION=cache DOORLEDGER_WRITER=template uvicorn doorledger.api:app --port 8787
make dashboard        # http://localhost:3000   (in a second terminal)
make demo             # POST /api/demo/run {"scenario":"full_day","speed":60}
```

In the dashboard, press **D** to open the demo strip and choose a scenario (`full_day`,
`porch_cold` or `late_short_visit`). Then watch the Today, Agency and Ledger views.
- **Offline (`cache`):** the 14:07 package drop comes from the real Ring Playground frames, with
  the Ring evidence frame. The check-ins and the pickup are labelled `simulated`.
- **`DOORLEDGER_PERCEPTION=off`:** skips perception entirely and injects every step as
  `simulated`.

**Run with Amazon Bedrock.** This re-detects the Ring Playground footage with Nova 2 Lite and
writes the messages with Claude Haiku 4.5:

```bash
# AWS credentials from your usual chain (AWS_PROFILE, env vars, SSO); region defaults to us-east-1
make api              # uv run --env-file .env uvicorn doorledger.api:app --port 8787
make dashboard
make demo SCENARIO=porch_cold
curl -s localhost:8787/api/ask -H 'content-type: application/json' \
     -d '{"question":"Is mom'\''s insulin OK?"}'
```

Optional AWS integrations:
- `DOORLEDGER_DYNAMO=1` mirrors the ledger to DynamoDB (create the table with
  `deploy/create_dynamo.py`).
- `DOORLEDGER_SMS_TO=+1…` sends SMS through SNS. The number must be verified in the SNS sandbox.
- `DOORLEDGER_AGENTCORE_ARN=…` uses a deployed AgentCore runtime.

**Live Ring (optional).**
- Put a Developer Playground token in `RING_ACCESS_TOKEN` (it lasts about 30 minutes). Start a
  scenario so care windows are open, then call `POST /api/live/watch`. DoorLedger polls Ring
  history and reacts to new events.
- To exercise the webhook path, set `RING_HMAC_KEY` and run `make webhook`. It sends a signed
  simulated `motion_detected` event to `/webhooks/ring`.

**Tests and checks:**

```bash
uv run pytest -q                       # 244 passed, 2 skipped; live AWS tests are opt-in
uv run ruff check packages/ringpartner
make sdk-check                         # build ringpartner + twine check
```

The test suite needs no AWS credentials and no network. CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the tests, ruff, the dashboard
build, and the ringpartner wheel tests on Python 3.10 and 3.13.

## Evaluation results

Both evaluations can be reproduced from `eval/`. **Both rely mainly on synthetic data, so read
the caveats.**

### Vision: which Bedrock model labels doorbell frames ([full results](eval/vision/RESULTS.md))

54 frames: 44 generated with Stable Image Core, 4 PIL composites and 6 night-IR variants. Each
was post-processed to Ring resolution with barrel distortion and JPEG compression, and labelled
by hand.

| Model (prompt v2) | Mean acc. (5 fields) | `package_visible` | `phone_screen_shown` | p50 latency | $/1k frames |
|---|---|---|---|---|---|
| **Nova 2 Lite** (chosen) | **100%** (54/54 on all fields) | 100% | 100% | 1.5 s | **$0.37** |
| Nova Pro | 99% | 98% | 96% | 1.5 s | $2.48 |
| Nova Lite @768 px (fallback) | 98% | 100% | 91% | 1.1 s | $0.11 |

**Real Ring Playground frames:** a 10-frame spot check (package, vehicle, birds) with Nova 2
Lite and prompt v2 got every frame right. It was a manual check, not a committed, labelled
eval set.

*Caveats:*
- The synthetic frames are cleaner than real Ring video: no H.264 blocking, no real IR, no
  glare.
- With n=54, one error moves a field by about 2 points, so the top three models are
  statistically tied.
- `vehicle_present` has only 3 positives.
- The phone-screen positives are clean composites, so 100% recall there is optimistic.
- Claude models were not part of this eval (see above).

### Presence codes: can a doorbell read a phone QR? ([full results](eval/presence/RESULTS.md))

9,880 rendered frames with a 150° fisheye, 1080p sensor model, blur, motion, low light, glare
and JPEG. A trial succeeds only if the payload decodes **and** the MAC verifies. Recommended
compact code, EC level M:

| Distance | 0.3 m | 0.4 m | 0.5 m | 0.6 m | 0.75 m | 1.0 m |
|---|---|---|---|---|---|---|
| Per frame, "mixed" (realistic) condition | 100% | 100% | 100% | 85% | 50% | 0% |
| 8-frame burst (one 2–3 s hold), mixed | 100% | 100% | 100% | 100% | 60% | 10% |

**Verdict:** the original goal of 1 m with a phone **fails**. It is a geometry limit (under 2 px
per QR module), not a decoder problem. We changed the method rather than the scope: the aide
holds the phone at 30–50 cm, we use a compact 25-digit code and burst decoding after a doorbell
press, and the 6-digit code is the fallback. *Caveat:* this is a synthetic camera model. Real
Ring frames (H.264, IR, watermark, auto-exposure) still need validation with own footage.

### Agent ([spike](docs/agent_spike.md))

- **Nova Pro:** 4 family questions and the daily summary each made one tool call, cited times
  and sources, and correctly said "I don't know" for data that wasn't in the ledger. Across 6
  `handle()` runs, no guardrail was bypassed.
- **Claude Haiku 4.5:** grounded answers that cite tools. Run locally under the AgentCore
  SDK, it took 2.7 s per question and 4.3 s per summary. On the deployed AgentCore runtime,
  `/api/ask` took about 7.6 s round trip on a cold-ish session; warm latency is not measured
  yet.

## Privacy and safety

- **No face recognition, anywhere.** Aides are identified only by the signed rotating code they
  choose to show.
- **Ring privacy zones are respected.** The zones in the device's `configurations`
  (`image_enhancements.privacy_zones`) are blacked out on every frame **before** any analysis
  or storage.
- **E2EE devices are skipped.** Devices with end-to-end encryption on are not analysed.
- **Faces are pixelated before the cloud.** Faces are pixelated on-device (OpenCV YuNet)
  **before** a frame is sent to Amazon Bedrock. The unredacted frame is used only in memory by
  the on-device code reader. *Limitation:* if YuNet misses a face (an unusual angle, IR), that
  frame is sent unredacted. A real-face test set is still to do.
- **Only event-tied frames are stored.** A frame is written to disk only when it backs a
  confirmed observation (a package left, a check-in). All other sampled frames are discarded.
- **Retention.** On API startup, stored evidence frames older than
  `DOORLEDGER_RETENTION_DAYS` (default 30) are purged. DynamoDB rows expire through TTL
  (default 30 days).
- **Minimal capture.** DoorLedger looks only during expected care windows or on a Ring event,
  in short sessions, never around the clock.
- **Secrets stay out of servers and logs.** The visit secret lives in the Caregiver Pass URL
  fragment. Issuing a pass link requires the agency admin token (`X-Admin-Token`). The SDK
  never prints tokens or writes them to fixtures, and pre-signed media tokens are stripped.
- **Authenticated inputs.**
  - Ring webhooks are HMAC-verified over the raw body and deduplicated.
  - QR presence codes are MAC-verified, bound to a role and a time step, and single-use.
  - 6-digit code attempts are rate-limited per door.
- **LLMs can't act on their own.**
  - Family Q&A uses read-only tools.
  - Every outbound message, whether from rules or the agent, passes code guardrails: household
    members only, an open incident, ladder order and a 10-minute gap, per-incident caps, no
    repeats.
  - Pharmacy replacement requests are **drafts** and are never sent automatically.
- **Not a medical device.** Temperatures are model estimates, and messages advise confirming
  with the pharmacist. DoorLedger supports caregivers. It doesn't replace clinical judgement.

## Limitations and what's next

**Known limitations (honest list)**

- **Simulated steps.** The aide check-in and check-out and the package pickup in the demo are
  simulated. Own footage is planned ([shot list](docs/SHOT_LIST.md)), and presence codes have
  not yet been read off real Ring video.
- **Mostly synthetic evals.** The evaluations rely mainly on synthetic data, and the real Ring
  check was a 10-frame spot check.
- **Unvalidated thermal model.** It uses documented, conservative assumptions (a 90 min time
  constant in shade, halved in sun). It has not been validated against real shipments.
- **Playground limits.** The Playground has one device, three scenes, no webhooks and no way
  to set privacy zones. Privacy-zone masking and E2EE skipping are implemented but not yet
  covered by tests. Multi-camera support exists in the SDK (`component_id`) but has not been
  exercised.
- **Poller gaps.** The history poller reads the newest page without an `event_types` filter.
  Only observations derived from Ring events reach the dashboard timeline; the raw Ring event
  list ("Ring recorded a ding at 14:06") is not shown yet.
- **No API authentication.** Apart from pass issuing (admin token) and webhooks (HMAC), the
  demo API has **no authentication**. `/api/ask`, `/api/demo/run` and `/api/live/watch` spend
  Bedrock credit and are meant for localhost only.
- **AWS gaps.** The Lambda webhook receiver is design only. SMS goes only to the
  sandbox-verified demo phone. The AgentCore runtime is read-only by design, so guarded actions
  still run in the API process.
- **Unvalidated business.** Pricing is a hypothesis with no customer interviews yet
  ([docs/BUSINESS.md](docs/BUSINESS.md)).

**What's next**

- Record own footage and validate presence codes on real Ring video.
- Show the raw Ring events and snapshots in the timeline.
- Add a one-click exposure report (`claims.exposure_report()`, already tested) to the dashboard.
- Add a weekly agency report (verified visits, minutes delivered vs. billed) and Ring
  Appstore shell screens (onboarding, notification settings, data deletion).
- Add a TypeScript port of `ringpartner`.
- As a v2 module, use "time to open the door" as a frailty signal.

## Repository map

```
packages/ringpartner/   Open-source Ring Partner API SDK (REST, WHEP, webhooks, simulator, fixtures, CLI, examples/)
core/src/doorledger/    Engine, reconcile, exposure, presence codes + reader, watcher, vision,
                        privacy, responder, notify, CareAgent, claims PDF, ledger, EVV, FastAPI app
core/src/doorledger/aws DynamoDB mirror, read-only snapshot, AgentCore client
core/tests/             Unit tests (engine, reconcile, exposure, porch, responder, watcher, live,
                        presence, privacy, claims, agent, AWS, JS parity)
web/dashboard/          Next.js dashboard (Today / Agency / Ledger / Ask)
web/caregiver-pass/     Static Caregiver Pass page (rotating signed QR + 6-digit backup code)
eval/vision/            Bedrock vision model eval (scripts, labels, results)
eval/presence/          Presence-code readability eval (synthetic camera model)
fixtures/               Ring Playground Package frames, recorded API responses, vision label cache
deploy/                 AgentCore Runtime app (CareAgent) and DynamoDB table setup
docs/                   Architecture, AWS architecture, business model, agent spike, shot list, video script
scripts/                Live capture, own-footage ingest and agent spike scripts
FRICTION_LOG.md         Developer-experience feedback for Ring and AWS
```

## Attribution and licensing

- **License:** [Apache License 2.0](LICENSE), Copyright 2026 Brandon Garcia. See [NOTICE](NOTICE)
  for third-party attributions.
- **Ring Playground package clip:** *"Thief stealing our package"*, by **TODO: creator name and
  source link, copied from the credit shown in the Ring Developer Playground**. Licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It was clipped from the original,
  as credited by Ring in the Developer Playground. DoorLedger re-encoded and sampled frames from
  it (`fixtures/ring_playground/package/`). The Playground's Vehicle and Motion scenes are not
  used and not redistributed here.
- **YuNet face detector:** OpenCV Model Zoo, MIT License.
- **Trademarks:** DoorLedger and ringpartner are independent projects. They are not affiliated
  with or endorsed by Ring LLC or Amazon. "Ring", "Amazon", "AWS", "Amazon Bedrock" and "Amazon
  Nova" are trademarks of their owners. "Claude" and "Claude Code" are trademarks of Anthropic.
- **Built during the hackathon.**
  - All code in this repository was written between **October 11 and October 23, 2026**,
    during the hackathon's submission window. The git history begins on 2026-10-11.
  - It was written with **Claude Code** (Anthropic Claude via Amazon Bedrock) as the coding
    assistant.
  - Third-party dependencies, the YuNet model and the Ring Playground footage are the only
    pre-existing materials.

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
