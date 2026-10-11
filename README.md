# DoorLedger

> **Care is delivered through the front door. DoorLedger makes sure it arrived.**

DoorLedger turns a Ring doorbell into a witness for home care. It compares the care that was
**expected** at an older adult's front door with what the doorbell **observed**. Expected care
means caregiver visits and temperature-sensitive medication deliveries. DoorLedger acts only
when the two differ: an aide who never checked in, a 2-hour visit that lasted 43 minutes, or
insulin freezing on the porch.

Built for the Amazon Developer Hackathon **"Build, Ship, Shape"**: Ring track, plus the
**Open Source** and **AWS Builder** mini-challenges.

| | |
|---|---|
| **Ring** | Partner API REST (devices, status, capabilities, configurations, history with `event_types`), server-side **WHEP live view**, snapshots, **signed webhooks**. Developed against the Ring Developer Playground |
| **AWS** | Amazon Bedrock: **Nova 2 Lite** (vision), **Claude Haiku 4.5** with Nova fallback (messages), **Strands Agents** CareAgent (Claude Haiku 4.5 / Nova Pro) |
| **Open source** | [`ringpartner`](packages/ringpartner): the Python SDK for the Ring Partner API that Ring doesn't ship. Apache-2.0 |
| **Demo video** | _link to be added_ |

---

## Contents

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

## The problem

When an older adult lives alone, most of their care arrives through the front door: the home
health aide, the nurse, prescriptions, meals. Families who live far away can't tell whether
the aide came, how long she stayed, or whether the insulin has been sitting on the porch for
two hours. Agencies and payers can't fully tell either.

- **Visits go unverified.** A 2025 audit by the New York State Comptroller found that NY
  Medicaid paid about **US$14.5 billion** for some 82 million home-care services over 26 months
  that had **no matching Electronic Visit Verification (EVV) record**.
  ([audit](https://www.osc.ny.gov/files/state-agencies/audits/pdf/sga-2025-22s31.pdf))
  *Caveat: this measures missing verification, not proven fraud.* Texas OIG describes the
  patterns that verification is meant to catch, including aides clocking in without showing up
  and aide-patient collusion.
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
 visits · deliveries                    live view · snapshots · webhooks
        │                                        │
        │                       Watcher: Nova 2 Lite vision + signed-code reader
        │                                        │  (k-of-n debounced)
        └──────────────► reconcile (deterministic) ◄───┘
                                 │ Findings: late · missed · short · package at risk …
                                 ▼
                 Responder: escalation ladder + guardrails
                 Writer (Claude Haiku 4.5 → Nova → template)
                                 │
          Ledger (append-only) ──► Dashboard (SSE) · EVV CSV · CareAgent Q&A
```

Full component and sequence diagrams: **[docs/architecture.md](docs/architecture.md)**.

1. **Expected vs. observed.** The day plan holds expectations, such as "Maria, morning personal
   care, 09:00–11:00, 120 min" or "Insulin refill, UPS, 13:00–17:00". Perception turns doorbell
   frames into observations: `package_dropped`, `package_removed`, `vehicle_arrived`,
   `presence_check_in/out`. `reconcile()` is a pure, unit-tested function that compares the two
   and produces findings.
2. **Expectation-guided sensing.** DoorLedger doesn't record the door all day. It opens a Ring
   live view only while care is expected (±30 min around a window) or when a signed Ring
   webhook arrives. It samples about 1 frame/s. A motion gate skips the vision call when the
   scene hasn't changed, which saved about 38% of calls in our runs.
3. **Signed rotating presence codes instead of face recognition.** Each visit gets a 32-byte
   secret. The aide's **Caregiver Pass** is a static web page, and the secret travels in the
   URL fragment, so it never reaches a server. The pass shows a QR code that changes every 15
   s. The code is an HMAC over the visit, the time step and the role (check-in or check-out).
   The aide holds the phone 30–50 cm from the doorbell for 2–3 seconds. The backend verifies
   the MAC and the time step, and rejects replays. A 6-digit TOTP is the fallback. This
   proves the aide was **at the door**, not in the parking lot, without identifying anyone's
   face.
4. **Thermal exposure model.** A package on the porch is modelled as a lumped body moving
   toward ambient temperature (Newton's law). Ambient comes from Open-Meteo, and the time
   constant changes with sun or shade. The model estimates the temperature inside the box and
   the time left until the heat limit (30 °C) or freezing (0 °C) for insulin. These are
   **estimates, labelled as estimates**, meant as an early warning with evidence, not a lab
   measurement.
5. **Deterministic decisions, LLMs for words.** Code decides whether a visit happened, whether
   it was late or short, and whether a package is at risk. Code also decides who may be
   contacted: patient → neighbor → family, with at least 10 min between rungs and at most 5
   messages per incident. Caregivers are never contacted directly. LLMs only **perceive**
   frames (Nova 2 Lite), **phrase** messages in each person's language (Claude Haiku 4.5,
   falling back to Nova Lite, then a template, so an alert is never blocked), and **answer
   questions** (CareAgent). The agent's Q&A mode gets read-only tools. Its optional action mode
   goes through the same guardrail code, and refusals come back to the model as tool results.
6. **One ledger.** Every expectation, observation, finding and action is appended to the
   ledger. The dashboard, the family summary, and the EVV export all read from it. The EVV
   export has the six 21st Century Cures Act fields plus the verification method and
   evidence.

**Demo story (Chicago, winter).** Rosa, 81, lives alone. Her aide Maria arrives 22 minutes late
and stays 43 of 120 planned minutes, and DoorLedger alerts the agency and her daughter Ana. At
14:07 the Ring doorbell sees an insulin package left on a snowy step at −9 °C. DoorLedger texts
Rosa in Spanish. When the box is projected to freeze, it asks the neighbor Luis (14:27), then
tells Ana (14:37). The box is brought inside at 14:40, and Ana gets a summary she can question
in plain language.

## Ring integration

| Ring capability | How DoorLedger uses it | Where |
|---|---|---|
| `GET /v1/devices?include=status,capabilities,configurations,location` | Discover the doorbell to watch. The SDK also parses online state and the E2EE flag (`configurations.e2e_encryption`, `Device.is_encrypted`) | `ringpartner.RingClient.devices()`, `live.py` |
| `status`, `capabilities`, `configurations`, `location` | Device detail. Recorded from the Playground as fixtures | `fixtures/playground/` |
| `history` with **`event_types`** (plural, comma-separated, e.g. `motion.human`) and `links.next` pagination | Find Playground events and their timestamps | `ringpartner.iter_history()` |
| **Snapshots** at a history event timestamp (`at=`) | Evidence frames. The Playground rejects `latest_in_range` with 403, while `at=<event start>` works (friction log F7) | `ringpartner.snapshot()`, `fixtures/evidence/ring_snapshot.jpg` |
| **WHEP live view, server-side** | The main sensor. `aiortc` negotiates a `recvonly` session from Python and decodes H.264 to NumPy frames for vision and QR decoding. Sessions are capped at 30–60 s, so the controller re-opens them while a care window is open | `ringpartner.whep.WhepSession`, `watcher.RingLiveSource`, `live.py` |
| **Signed webhooks** (`motion_detected`, `button_press`, `device_online/offline`) | `POST /webhooks/ring` verifies `X-Signature` (HMAC-SHA256 over the raw body), dedupes on `request_id`, answers within 5 s, and starts a watch session in the background | `api.py`, `live.py`, `ringpartner.verify_and_parse` |

**The Ring Developer Playground is the simulator.** It provides one doorbell, a WHEP live view
with three scenes (Package, Vehicle, Motion/bird feeder), snapshots, history and status. It
**does not deliver webhooks**, so `ringpartner simulate` builds documented v1.1 payloads, signs
them with your HMAC key and posts them. The production handler runs unchanged, signature check
included. Our [friction log](FRICTION_LOG.md) has 8 entries for the Ring team.

### Which footage is what

Every observation carries its source, and the dashboard shows it as a badge.

| Label | What it is | Used for |
|---|---|---|
| **Ring live view** (`ring_live_view`) | Frames captured from the Ring Developer Playground over WHEP on 2026-10-11 (`fixtures/ring_playground/`) | Vehicle arrival (14:05) and package drop (14:07). Replayed through the real Bedrock vision pipeline |
| **Ring snapshot** (`ring_snapshot`) | A snapshot fetched from the Playground through the API | Evidence frame |
| **Own footage** (`own_footage`) | Video we film ourselves of an aide showing the Caregiver Pass, and of a pickup ([shot list](docs/SHOT_LIST.md)) | **Not recorded yet.** It will replace the simulated steps below |
| **Simulated** (`simulated`) | Scripted observations with no video | Aide check-in (09:22) and check-out (10:05), package pickup (14:40). The Playground has no scene for these |
| *Synthetic (eval only)* | AI-generated and rendered images | `eval/vision`, `eval/presence`. Never shown as Ring footage |

The Playground's Package scene is a clip credited by Ring as *"Thief stealing our package"* (a
YouTube user, CC BY 4.0, clipped). See [Attribution](#attribution-and-licensing).

## AWS usage

| Service | What it does in DoorLedger | Model and why |
|---|---|---|
| **Amazon Bedrock, Converse API, image input** (`vision.py`) | Labels each sampled doorbell frame as strict JSON (`package_visible`, `person_present`, `person_carrying_package`, `vehicle_present`, `phone_screen_shown`). It reports facts only and makes no judgement about the visit | **Amazon Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`), prompt v2. In our eval it tied Nova Pro on accuracy at about **1/7 of the cost** (about $0.37 per 1k frames, p50 1.5 s). See [eval/vision](eval/vision/RESULTS.md) |
| **Amazon Bedrock, Converse API, text** (`responder.BedrockWriter`) | Rewrites each templated alert into a short, warm SMS in the recipient's language, using only the facts it is given | **Claude Haiku 4.5** first, then **Nova Lite**, then a template. Claude is preferred for tone and instruction-following |
| **Strands Agents SDK on Bedrock** (`agent.py`) | **CareAgent**: family Q&A ("Did Maria come today?") and the end-of-day summary, grounded in ledger tools. An optional `handle()` mode chooses actions through guarded tools | **Claude Haiku 4.5**, then **Nova Pro**. Nova 2 Lite was tested and rejected for the agent: it over-called tools and made one false claim. Nova Pro answered with no grounding errors in about 2 s for about $0.003 per question ([agent spike](docs/agent_spike.md)) |
| IAM, AWS Budgets | Least-privilege dev user (`bedrock:InvokeModel*` on the model ids above) and a US$30/month budget with alerts | Total Bedrock spend during development: about US$2.5 |

**Model choice is backed by measurement.** The Nova vs. Claude split comes from
[eval/vision](eval/vision/RESULTS.md) (11 runs × 54 frames) and the
[agent spike](docs/agent_spike.md). *Status note:* during development the account's Anthropic
use-case approval was still pending. The measured vision and agent runs therefore cover Nova
models only, and the Claude-first chains fell back to Nova automatically. Claude needs no code
change: it takes over once the account has access.

**In progress, not yet deployed at the time of writing:** CareAgent on **Amazon Bedrock
AgentCore Runtime**, which receives a read-only household snapshot so the runtime can never
message anyone (`deploy/agentcore/`, `core/src/doorledger/aws/`), and an optional **DynamoDB**
mirror of the ledger (`DOORLEDGER_DYNAMO=1`). A **Lambda / API Gateway** webhook receiver is
planned. See [docs/aws_architecture.md](docs/aws_architecture.md).

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

```bash
pip install ringpartner            # once published; for now: pip install ./packages/ringpartner
pip install 'ringpartner[whep]'    # adds live video
```

See [packages/ringpartner/README.md](packages/ringpartner/README.md) and its
[CHANGELOG](packages/ringpartner/CHANGELOG.md).

## Quickstart

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node 20+ (CI uses Node 24).
`make help` lists every target.

```bash
git clone https://github.com/HaDeZIB/doorledger && cd doorledger
uv sync --all-packages                 # core + ringpartner + dev tools
cp .env.example .env                   # all values optional for the offline demo
(cd web/dashboard && npm ci)
```

**Run the demo with no AWS and no network**, using template messages and scripted perception:

```bash
make api-offline      # DOORLEDGER_PERCEPTION=off DOORLEDGER_WRITER=template uv run uvicorn doorledger.api:app --port 8787
make dashboard        # http://localhost:3000   (in a second terminal)
make demo             # POST /api/demo/run {"scenario":"full_day","speed":60}
```

In the dashboard, press **D** to open the demo strip, choose a scenario (`full_day`,
`porch_cold`, `late_short_visit`), and watch the Today, Agency and Ledger views. In offline mode
the vehicle and package events are injected at the times the Ring footage shows them, with
their Ring evidence frames, instead of being re-detected.

**Run with Amazon Bedrock**, which re-detects the Ring Playground footage with Nova 2 Lite and
writes the messages with an LLM:

```bash
# AWS credentials from your usual chain (AWS_PROFILE, env vars, SSO); region defaults to us-east-1
make api              # uv run --env-file .env uvicorn doorledger.api:app --port 8787
make dashboard
make demo SCENARIO=porch_cold
curl -s localhost:8787/api/ask -H 'content-type: application/json' \
     -d '{"question":"Is mom'\''s insulin OK?"}'
```

**Live Ring (optional).** Put a Developer Playground token in `RING_ACCESS_TOKEN` (it lasts
about 30 minutes) and call `POST /api/live/watch` to watch during care windows. To exercise the
webhook path, set `RING_HMAC_KEY` and run `make webhook`, which sends a signed simulated
`motion_detected` event to `/webhooks/ring`.

**Tests and checks:**

```bash
uv run pytest -q                       # offline; live AWS tests are skipped unless opted in
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

**Real Ring Playground frames:** Nova 2 Lite with prompt v2 labelled **10/10** spot-checked
frames correctly (package, vehicle, birds). This was a manual check, not yet a committed,
labelled eval set.

*Caveats:* the synthetic frames are cleaner than real Ring video (no H.264 blocking, no real IR,
no glare). With n=54, one error moves a field by about 2 points, so the top three models are
statistically tied. `vehicle_present` has only 3 positives. The phone-screen positives are
clean composites, so 100% recall there is optimistic. Claude models could not be tested because
of the pending account access.

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
holds the phone at 30–50 cm, we use a compact 25-digit code and burst decoding, and we keep a
6-digit fallback. *Caveat:* this is a synthetic camera model. Real Ring frames (H.264, IR,
watermark, auto-exposure) still need validation with own footage.

### Agent ([spike](docs/agent_spike.md))

On Nova Pro, 4 family questions and the daily summary each made one tool call, cited times and
sources, and correctly said "I don't know" for data that wasn't in the ledger. Across 6
`handle()` runs, no guardrail was bypassed.

## Privacy and safety

- **No face recognition, anywhere.** Aides are identified only by the signed rotating code they
  choose to show. Faces are **pixelated on-device** (OpenCV YuNet) before any evidence frame is
  written to disk. Raw frames stay in memory and are sent to Amazon Bedrock only to be
  classified.
- **Minimal capture.** Live view is opened only during expected care windows or on a Ring
  webhook, not around the clock. Frames sampled during a watch session (about 1/s) are stored
  face-pixelated as evidence. Pruning storage down to the frames that prove an event is on the
  roadmap.
- **Secrets stay out of servers and logs.** The visit secret lives in the Caregiver Pass URL
  fragment. The SDK never prints tokens or writes them to fixtures, and pre-signed media tokens
  are stripped.
- **Authenticated inputs.** Ring webhooks are HMAC-verified over the raw body and deduplicated.
  Presence codes are MAC-verified, bound to a role and a time step, and single-use.
- **LLMs can't act on their own.** Family Q&A uses read-only tools. Every outbound message,
  whether from rules or the agent, passes code guardrails: household members only, an open
  incident, ladder order and gap, per-incident caps, no repeats. Pharmacy replacement requests
  are **drafts** and are never sent automatically.
- **Not a medical device.** Temperatures are model estimates, and messages advise confirming
  with the pharmacist. DoorLedger supports caregivers. It doesn't replace clinical judgement.
- **E2EE devices.** Ring devices with end-to-end encryption return media that can't be
  analysed. The SDK exposes `Device.is_encrypted` so integrations can detect this.

## Limitations and what's next

**Known limitations (honest list)**

- The aide check-in and check-out and the package pickup in the demo are **simulated**. Own
  footage is planned ([shot list](docs/SHOT_LIST.md)).
- The evaluations rely mainly on synthetic data, and the real Ring check was a 10-frame spot
  check.
- The thermal model uses documented, conservative assumptions (a 90 min time constant in
  shade, halved in sun). It has not been validated against real shipments.
- The Playground has one device, three scenes and no webhooks. Multi-camera support exists in
  the SDK (`component_id`) but has not been exercised.
- At naive sampling, vision costs about **$20–40 per patient per month** for 1 h of care windows
  per day. Motion gating already cuts calls by about 38%. Next steps are a cheap Nova Lite
  pre-filter and slower sampling when the porch is stable.
- The demo API has **no authentication** and is meant for localhost. Rate limiting of 6-digit
  fallback attempts per door is designed but not implemented.
- The AgentCore and DynamoDB integrations are in progress, and the Lambda webhook receiver is
  planned. Claude models were not measured because account access was pending.

**What's next:** record the own footage and validate presence codes on real Ring video. Deploy
CareAgent to AgentCore Runtime with server-side guardrails. Surface the pharmacy exposure report
(`claims.py`: a one-page PDF with the Ring frame, timeline, temperature estimate and notifications)
in the dashboard for one-click replacement claims.
Add a weekly agency report (verified visits, minutes delivered vs. billed), multi-camera support
(garage camera for "vehicle arrived"), a TypeScript port of `ringpartner`, and, as a v2 module,
"time to open the door" as a frailty signal.

## Repository map

```
packages/ringpartner/   Open-source Ring Partner API SDK (REST, WHEP, webhooks, simulator, fixtures, CLI)
core/src/doorledger/    Engine, reconcile, exposure, presence codes + reader, watcher, vision,
                        privacy, responder, CareAgent, ledger, EVV, FastAPI app
core/tests/             Engine, presence, agent and JS-parity tests
web/dashboard/          Next.js dashboard (Today / Agency / Ledger / Ask)
web/caregiver-pass/     Static Caregiver Pass page (rotating signed QR)
eval/vision/            Bedrock vision model eval (scripts, labels, results)
eval/presence/          Presence-code readability eval (synthetic camera model)
fixtures/               Ring Playground frames and recorded API responses
deploy/                 AgentCore Runtime app (CareAgent) and DynamoDB setup (in progress)
docs/                   Architecture, AWS plan, agent spike, shot list, video script
scripts/                Live capture, own-footage ingest and agent spike scripts
FRICTION_LOG.md         Developer-experience feedback for Ring
```

## Attribution and licensing

- **License:** [Apache License 2.0](LICENSE), Copyright 2026 Brandon Garcia. See [NOTICE](NOTICE)
  for third-party attributions.
- **Ring Playground package clip:** *"Thief stealing our package"*, by a YouTube user, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It was clipped from the original,
  as credited by Ring in the Developer Playground. DoorLedger re-encoded and sampled frames from
  it (`fixtures/ring_playground/package/`). The Vehicle and Motion scenes remain the property of
  their owners.
- **YuNet face detector:** OpenCV Model Zoo, MIT License.
- **Trademarks:** DoorLedger and ringpartner are independent projects. They are not affiliated
  with or endorsed by Ring LLC or Amazon. "Ring", "Amazon", "AWS", "Amazon Bedrock" and "Amazon
  Nova" are trademarks of their owners. "Claude" is a trademark of Anthropic.
- **Built during the hackathon.** All code in this repository was written between **October 11
  and October 23, 2026**, during the hackathon's submission window. The git history begins on
  2026-10-11. Third-party dependencies, the YuNet model and the Ring Playground footage are the
  only pre-existing materials.

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
