# DoorLedger business model (Ring Appstore)

> **Status: hypotheses.** Prices, buyers and volumes below are reasoned assumptions. They have
> **not** been validated with agencies or families yet (next step: 5 agency calls and 5 family calls
> before the next revision). The *costs* are different: they come from our own measurements on
> Amazon Bedrock, and each one says where it comes from.

## 1. Who pays, and for what

| Buyer | What they buy | Why they pay | How they pay (hypothesis) |
|---|---|---|---|
| **Home-care agencies (B2B, primary)** | A door-verified signal for each visit: check-in and check-out from a signed rotating code shown to the client's Ring doorbell, visit length vs. plan, and an EVV-ready export with the verification method and evidence | Visit verification is under payer scrutiny (see §4). A missed or short visit found the same morning is cheaper than a complaint, a lost client or a clawback | **Per active client per month.** Billed to the agency, with the app installed on the client household's Ring account |
| **Families (B2C, add-on)** | Alerts when expected care didn't arrive (aide late, missed or short visit) or when temperature-sensitive medication sits outside; a daily summary; plain-language Q&A ("Did Maria come today?") | Peace of mind from far away, in the parent's language | **Ring Appstore subscription** on the household's Ring account (`subscription_activated` webhooks are already parsed by `ringpartner`) |
| *Later: specialty and mail-order pharmacies* | The medication exposure report (`claims.exposure_report()`: Ring frame, time outside, estimated box temperature, who was notified) | Faster, evidence-backed replacement decisions | Per report or per patient. Not modelled here |

The household needs a Ring doorbell and an active **Ring Protection** plan or trial; Ring's FAQ
requires one for partner-app device access. That cost falls on the household (or an agency that
provisions the doorbell) and is not counted in our COGS below.

## 2. Price hypotheses and reasoning

| Plan | Hypothesis | Reasoning |
|---|---|---|
| **Family** (B2C) | **US$7.99 / month** per household | Families compare it with what they already pay for the camera plan, so it has to read as a small add-on (under US$10). It must still clear COGS with margin, which only works with expectation-guided sensing (§3) |
| **Agency EVV add-on** (B2B) | **US$15 / active client / month** (pilot: free for 60 days) | Small next to what one client bills each month. *Illustration only, not a market figure:* a client receiving 40 h/month at an assumed US$25/h is about US$1,000 billed, so US$15 is about 1.5%. One recovered or defended visit can cover the fee. Per-client pricing scales with the agency's census, which is how agencies already think about software |

What would change these prices: agencies that already pay an EVV vendor per client may only pay
for the *door-verified* layer at a lower price (US$5–10). Families may need a free tier (alerts
only) with paid summaries and Q&A.

## 3. Unit economics (per household per month)

### Measured inputs

| Input | Value | Source |
|---|---|---|
| Vision (Amazon Nova 2 Lite, prompt v2) | **~US$0.37 per 1,000 frames** (≈ US$0.00037/frame), p50 1.5 s | [eval/vision/RESULTS.md](../eval/vision/RESULTS.md), recorded token usage × price list |
| Motion gate (skip the vision call on unchanged frames) | **38–60% fewer vision calls**, depending on scene activity | Our replay runs. In the offline `porch_cold` replay: 3 calls, 5 skipped (62%) |
| CareAgent question (Claude Haiku 4.5) | **~US$0.0045** (Nova Pro fallback: ~US$0.003) | [aws_architecture.md](aws_architecture.md) (3.9k in / 0.13k out tokens); [agent_spike.md](agent_spike.md) |
| Daily summary (Claude Haiku 4.5) | ~US$0.0063 | [aws_architecture.md](aws_architecture.md) |
| AgentCore Runtime compute per question (CareAgent is deployed there) | < US$0.001 | Estimate in [aws_architecture.md](aws_architecture.md): CPU billed only while active, about 0.5 GB of memory for the call plus a 300 s idle timeout |
| One alert message, LLM wording (Claude Haiku 4.5 → Nova Lite → template) | **≤ ~US$0.005** | Our measurements (short prompt plus at most 200 output tokens) |
| SMS delivery (Amazon SNS, US) | ~US$0.01 per message | **Estimate.** Check current SNS SMS pricing and carrier fees |
| Hosting, WHEP decode, DynamoDB, storage | ~US$1.00 per household | **Assumption** at a few hundred households. DynamoDB alone is cents (on demand, TTL-expired rows) |

### Usage assumptions (one home-care client)

- One aide visit a day (2 h window). Medication deliveries a few times a month.
- **Expectation-guided sensing, event-driven** (the default with a live Ring token, `live.py`).
  During care windows, DoorLedger polls Ring event history. For each new Ring event it
  classifies the event-time snapshot, then opens one short live view: 25 s at 1 fps, or a
  12 s, 4 fps burst after a doorbell press. Outside expected windows, nothing is watched.
- About **8 Ring events a day** inside windows (6 ordinary, 2 doorbell presses for check-in and
  check-out).
- About 10 alert messages a month (DoorLedger only acts on a difference), one daily summary
  and about 15 family questions.

### Vision frames per month: three sensing strategies

| Strategy | Raw frames / day | After motion gate (38–60% skipped) | Vision cost / month |
|---|---|---|---|
| **Expectation-guided, event-driven** (6 × (1 + 25) + 2 × (1 + 48)) | 254 | 102–157 | **US$1.13–1.75** |
| Care-window watching (continuous 25 s sessions with 20 s gaps for 3 h/day: the 2 h visit ± 30 min) | ~6,000 | 2,400–3,720 | US$27–41 |
| Naive always-on (1 fps, 24 h) | 86,400 | 34,560–53,568 | US$384–595 |

This is why sensing strategy is the business model. Always-on vision costs more than any
plausible price. Watching whole care windows (DoorLedger's fallback without a live token, and the
basis of the older "US$20–40 per patient per month" figure in earlier docs) only fits a premium
agency price. Event-driven sensing during expected windows brings vision under US$2.

### Monthly COGS and margin (event-driven)

| Line | US$ / month |
|---|---|
| Vision (midpoint) | 1.40 |
| Alert messages: 10 × (0.005 LLM + 0.01 SMS) | 0.15 |
| Daily summaries: 30 × 0.0063 | 0.19 |
| Family questions: 15 × 0.0045 | 0.07 |
| Hosting, decode, storage (assumption) | 1.00 |
| **COGS** | **≈ 2.81** |

| Plan | Price | Platform share (assumed 30%, see risks) | Net revenue | COGS | **Gross margin** |
|---|---|---|---|---|---|
| Family | 7.99 | 2.40 | 5.59 | 2.81 | **2.78 (50% of net)** |
| Agency, billed through the Appstore | 15.00 | 4.50 | 10.50 | 2.81 | **7.69 (73% of net)** |
| Agency, invoiced directly (if permitted) | 15.00 | 0 | 15.00 | 2.81 | **12.19 (81%)** |
| *Family with care-window watching instead* | 7.99 | 2.40 | 5.59 | ~36 | *negative* |

**Sensitivity.** Doubling Ring events to 16 a day adds about US$1.40. Doubling messages and
questions adds about US$0.40. The Family plan breaks even at roughly 3× our event
assumption. The agency plan stays positive in every event-driven case. The platform share is an
**assumption**: the Ring developer docs we used describe subscription webhooks and weekly revenue
reports, but not the revenue split.

## 4. EVV compliance value for agencies

- **Why agencies care.** Under the 21st Century Cures Act, states require Electronic Visit
  Verification (EVV) for Medicaid personal care and home health visits. The six required data
  points are service type, member, date, location, worker, and start and end times. Payers are
  starting to act on mismatches.
- **The evidence, cited carefully.** The New York State Comptroller's audit **2022-S-31**
  (issued November 2024) found about **US$14.5 billion** in Medicaid personal care claims, about
  82 million services with service dates from January 2021 to March 2023, with **no matching EVV
  record**.
  ([report](https://www.osc.ny.gov/files/state-agencies/audits/pdf/sga-2025-22s31.pdf),
  [Comptroller summary](https://osc.ny.gov/state-agencies/audits/2024/11/13/medicaid-program-provider-compliance-electronic-visit-verification-program))
  - The Department of Health disputed about **US$2.7 billion** of that tally.
  - The audit measures **missing verification, not proven fraud**. We use it to show payer
    scrutiny, not to claim agencies are committing fraud.
- **What DoorLedger adds.** Today's EVV is mostly app GPS or telephony at clock-in. DoorLedger
  adds a second, independent signal from the client's own door:
  - A device showing the visit's current signed code was at the door, within a 15 s time
    step, with no face recognition.
  - Visit length measured from check-in to check-out at the door, compared with the plan.
  - An evidence frame (faces pixelated) and a CSV export with the six Cures Act fields plus the
    verification method.

  It is a *verifiable check-in signal*, not proof of identity: a relative holding the aide's
  phone would pass.
- **What it does not do (yet).** It doesn't submit to state EVV aggregators. Agencies keep
  their state-mandated EVV system, and DoorLedger is a corroborating layer.

## 5. Go-to-market

1. **Ring Appstore listing (Family plan).** Families discover it where they already manage
   the doorbell. The listing copy leads with medication left outside and "did the aide come
   today?". Bilingual messages (Spanish/English) are a differentiator for Hispanic families
   caring across distance.
2. **Agency pilots through a Ring private app.**
   - A private app skips certification and allowlists a small number of Ring accounts (the FAQ
     says up to 10; older release notes say 5).
   - Run 60-day free pilots with 1–2 agencies, about 10 clients each.
   - Pilot metrics: share of visits verified at the door, delivered vs. scheduled minutes,
     alerts per client per week, false-alert rate, and agency staff time per alert.
3. **Convert pilots to per-client contracts.** In parallel, file a public app for
   certification (privacy-zone masking and E2EE skipping are implemented, see the README; tests for both are pending).
4. **Later:** pharmacy partnerships for the exposure report, and an agency weekly report
   (verified visits, minutes delivered vs. billed).

**Constraint:** the Ring Appstore and the Test phase are US-only today
([friction log R1](../FRICTION_LOG.md#r1--ring-appstore-and-the-test-phase-are-us-only)), so
pilots must run with US households.

## 6. Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Demand is unvalidated | No agency or family interviews yet | 10 discovery calls before building more. Price tests in the pilot |
| Agencies already pay an EVV vendor | DoorLedger may look redundant | Position it as corroboration plus family alerts, priced below the EVV vendor. Integrate exports, don't replace |
| Aide consent and labour concerns | A camera-based check-in can feel like surveillance | Opt-in signed codes, no face recognition, faces pixelated before the cloud, privacy zones honoured, short retention (`DOORLEDGER_RETENTION_DAYS`), aide-visible pass page |
| Health data (HIPAA) when selling to agencies | Agencies are covered entities, so DoorLedger would be a business associate | BAA-ready architecture on HIPAA-eligible AWS services (verify per service). Minimal data: no diagnoses, only visit and delivery events |
| Platform terms (revenue share, off-platform billing) | Unknown share; direct agency invoicing may not be allowed | Margins hold at an assumed 30% share. Confirm with the Ring partner team before pricing |
| Ring Protection plan and device ownership | The household must own a Ring doorbell and keep a plan | Families who already have Ring first. Agencies can provision a doorbell for high-risk clients |
| Model or price drift | Vision cost dominates COGS | Model choice is measured (`eval/vision`). Cheaper Nova Lite pre-filter (US$0.11/1k frames in our eval). Event-driven sensing keeps volume low |
| False alerts or misses | Trust erodes quickly | Deterministic rules, k-of-n debouncing, alerts only on a difference, a ladder with gaps and caps. Temperatures labelled as model estimates |
| Signal limits | The code shows a device with the current signed code was at the door, not who held it | Say so in the product and the contract. Combine with the agency's own EVV |
