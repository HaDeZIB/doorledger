# Improvements 04: what would most increase the odds of winning (11 Oct 2026, night)

**What this review is.** It is not a score. An independent panel (none of us built this)
looked for the changes that most raise the odds of winning, and checked honestly whether
DoorLedger would work for **Rosa** (81, Spanish-speaking, no apps, maybe a basic phone, maybe
weaker sight, hearing or memory).

**The panel:**
- Ring Director of Engineering
- Ring Appstore / partner PM
- AWS Solutions Architect (AWS Builder judge)
- Open Source maintainer
- **Geriatric care and accessibility specialist** (new): has worked with adults 80+, including
  Spanish-speaking immigrants

**What we checked.**
- HEAD `1de5d98` plus the other agents' uncommitted edits, without touching them.
- The live URLs: [doorledger.vercel.app](https://doorledger.vercel.app),
  [pypi.org/project/ringpartner](https://pypi.org/project/ringpartner/), and both GitHub repos
  (CI green on both).
- The Ring Partner API reference in `.ref/`.

**What we left out.** Items other agents are fixing now are not repeated here: AgentCore
warm-up, error sanitising, Caregiver Pass copy, Rosa's SMS-vs-app wording, vision model and
latency on the evidence card, the poller's `event_types`, docs translation, NOTICE.

---

## 0. Verdict in one paragraph

**Today DoorLedger is built for Ana, not for Rosa.** Rosa gets a single text message, from a
number she doesn't recognise, telling her to go out onto an icy step at −9 °C. Then the system
waits 20 minutes.
- **Why that fails:** for an 81-year-old, an unknown text is the channel she is least likely to
  read, and the one scammers use most. And "go outside on the ice" is the instruction a
  geriatric specialist would stop first: falls are the leading cause of injury death in adults
  65+ (CDC).
- **The fix is small and very visible to judges:**
  - Rosa's wording is fixed, short and fall-safe, and no LLM writes it.
  - **The doorbell is the reply.** Rosa never has to answer, because Ring sees the box picked up.
  - Add an in-home cue through **Ring Chime playback**, a documented Partner API endpoint nobody
    else will use.
  - Add a **Spanish voice call** (Amazon Polly through AWS End User Messaging) at +5 min if Ring
    hasn't seen the pickup.
  - Squeeze the ladder so the person who can physically help (Luis) is asked while there is
    still time.
- **Payoff:** the demo becomes "it works for the person at the door", which no other Ring
  entry will have.

---

## 1. Accessibility reality check for Rosa

### 1.1 What Rosa actually receives today (verified in code)

| Step | Code | What happens | Specialist's problem with it |
|---|---|---|---|
| 14:07, package seen | `responder.py:213` → `TemplateWriter._spanish` `responder.py:98-101` | One SMS: *"Hola Rosa, le dejaron su medicina en la puerta y afuera está helando (-9°C). Por favor métala a la casa y guárdela en el refrigerador."* | (a) It tells her to go out onto a snowy step with no "only if it's safe" clause. **Fall risk.** (b) "−9 °C" is a number she has to process. If she has lived in Chicago for decades she may think in °F, so either way it is noise. (c) It doesn't say who is writing or why, so it reads like a scam text. (d) It doesn't say what happens if she can't go out. |
| SMS envelope | `notify.py:89` | Prefixed with `DoorLedger → Rosa Martínez:` | An English brand name, an arrow and her full name read as a robot or a scam. With the arrow (→), "°" and á/í the message can't use the GSM-7 alphabet. It is sent as UCS-2, with 70-character segments (67 when split), so it arrives as 3 segments. |
| LLM path (live mode) | `responder.py:114-120,156` | Claude rewrites Rosa's message, up to 300 characters, truncated at 480 | 300 Spanish characters is 5 UCS-2 segments. A cut at 480 can drop the end of a safety instruction. An LLM also varies the wording every time. Older adults, especially with mild cognitive impairment, recognise a message by its **fixed shape and sender**. |
| 14:07 → 14:27 | `exposure.py:73,102` (at-risk = ≤20 min to unsafe), `responder.py:221,271` (fixed 10 min `LADDER_GAP`) | Nothing more reaches Rosa. Luis is asked at 14:27 with about 20 min left, and Ana at 14:37 with about 10 min left | The first 20 of roughly 40 minutes are spent waiting on a channel Rosa may never open. Ana is in another city, so 10 minutes is too late for her to act. |
| If it was too late | `responder.py:102-105` | *"…puede que ya no sirva. **No la use todavía**: preparamos una solicitud de reposición…"* | A **clinical safety issue.** It tells a person with diabetes not to use her insulin without telling her what to do instead; missed doses carry real risk. "Solicitud de reposición" is jargon. |
| Box brought inside | `responder.py:242-247` | Only **family** is told | Rosa is never told it's resolved. If Luis brought it in, she doesn't know where it is. |
| Message to the neighbour (hosted demo) | `web/dashboard/lib/mock/script.ts:167` | *"Rosa's insulin has been on her porch…"* | It tells a neighbour about a health condition without Rosa's consent. The backend template already says "refrigerated medication" (`responder.py:69`), so the mock is the one to fix. |
| Per-person preferences | `domain.py:70-76` (`Person`), `notify.py:120` | No channel, consent, mobility or "can read texts" field. The channel is global | So the product can't express "Rosa: voice call, not text", "Rosa: walker, don't send her out in snow", or "Luis agreed on date X". |

### 1.2 Is SMS the right first channel?

**SMS is the right *first, cheap, silent* touch, and the wrong *only* touch.** Keep it; it costs
nothing to Rosa. Add channels in this order:

1. **The Ring camera as the reply mechanism (zero effort for Rosa).** DoorLedger already sees
   `package_removed`. Say so in the message: *"No tiene que contestar."* ("You don't need to
   reply.") Then cancel every pending rung the moment Ring sees the pickup.
   - This is the most elder-appropriate "reply" there is: Rosa does nothing extra.
   - It is also the most **Ring-native** answer: the doorbell closes the loop.
2. **In-home cue: Ring Chime playback** (`POST /v1/devices/{id}/media/audio/playback`,
   `.ref/ring-api.md:404,5672-5734`).
   - Most Ring doorbell homes have a Chime or an Echo. A chime sound inside the house reaches
     Rosa with no phone at all.
   - **Limits, stated honestly:**
     - Partners play one of their **fixed audio slots** (for example "Ring Alert 3"), not a
       custom spoken message (`ring-api.md:5571-5583`).
     - Chimes are **Early Access** (dynamic scopes, Aug 24, 2026), so a public app can't ship
       chime playback until GA.
     - The Playground has no chime.
   - So it is a cue, not the content: "the chime sounds → Rosa looks at the door / phone".
3. **Automated voice call in Spanish** (Amazon Polly voice, AWS End User Messaging SMS & Voice
   v2 `SendVoiceMessage`), at **+5 min** if Ring hasn't seen the pickup. A call:
   - reaches **landlines**. Many adults 80+ still keep one; a text to a landline goes nowhere.
   - needs **no reading**. Low literacy is common among older Mexican-born adults, and so is
     low vision.
   - gives a **signal back**: answered, no answer or busy, through event destinations.
   - **Hearing loss works against it.** About two-thirds of adults 70+ have measurable hearing
     loss (Lin et al., 2011). So: speak slowly (SSML `prosody rate="85%"`), repeat the message
     once, keep it short, no background music.
   - **Additive, not a replacement:** the SMS stays as something she can re-read or show
     Luis.
4. **Do NOT build "reply 1 if you picked it up" by SMS.**
   - Two-way SMS to US numbers needs a registered toll-free or 10DLC number, which takes weeks.
   - Pressing a key during a call (DTMF) needs Amazon Connect: contact flows, number claiming,
     outbound quotas. That is 2+ days and would dilute the story.
   - The camera already gives the answer. Keep "reply by SMS" in *What's next*.

### 1.3 Rewritten messages (use as fixed templates; no LLM for the patient)

Rules for anything sent to Rosa:
- At most about 150 characters.
- One action, plus a safe way out.
- No numbers, links or brand names.
- Always the same sender, and the family member who set it up is named.
- "Usted", with simple Mexican Spanish.
- Never ask for information. That is the anti-scam signal.

| Purpose | Current (`responder.py`) | Rewrite (Spanish, as sent) | English gloss (for the README / video subtitle) |
|---|---|---|---|
| `porch_patient` (cold) | `:100-101` (above) | **"Rosa: su insulina está en la puerta y hace mucho frío. Métala al refri. Si hay hielo, no salga: Luis le ayuda. No tiene que contestar. —Aviso de Ana"** | "Rosa: your insulin is at the door and it's very cold. Put it in the fridge. If there's ice, don't go out: Luis will help. You don't need to reply. —Ana's alert" |
| `porch_patient` (heat) | same | "Rosa: su insulina está en la puerta y hace mucho calor. Métala al refri. Si no puede, no se preocupe: Luis le ayuda. No tiene que contestar. —Aviso de Ana" | |
| Voice call (+5 min, SSML, said twice) | none | `<speak><prosody rate="85%">Hola, Rosa. Le habla el aviso del timbre que puso su hija Ana. Su insulina está afuera, en la puerta. Hace mucho frío. Por favor, métala y póngala en el refrigerador. Si hay hielo, no salga. Luis le va a ayudar. No tiene que hacer nada más.<break time="1s"/>Repito. …</prosody></speak>` | "Hello Rosa, this is the doorbell alert your daughter Ana set up…" |
| `porch_compromised` (to Rosa) | `:103-105` "No la use todavía…" | **"Rosa: su insulina estuvo mucho tiempo afuera con el frío. Antes de usarla, pregunte en su farmacia. Ana ya sabe y le va a llamar."** | "Before using it, ask your pharmacy. Ana knows and will call you." Not "don't use it". |
| `porch_retrieved` (send to Rosa too) | `:106-107`, family only (`:246`) | "Listo, Rosa: su insulina ya está adentro. Póngala en el refri. Gracias." | Closure lowers anxiety. |
| `porch_helper` (Luis) | `:69-71` (good) | Keep the backend wording, "refrigerated medication", and fix the mock (`script.ts:167`) that says "insulin". | Least health information needed. |
| SMS envelope | `notify.py:89` | For the patient: **no prefix**. For the single demo phone, use `[Demo · para Rosa]` so the video stays honest. | |
| Temperatures | `:65-66,:100` | Never send a number to the patient. Family gets °F in the US (the dashboard already toggles °F/°C; the English template uses °C). | |

### 1.4 Escalation ladder if Rosa never reads it

Proposed ladder, with the package seen at T. The engine already estimates time to unsafe
(`exposure.py`).

| When | Who / channel | Skipped if |
|---|---|---|
| T+0 | Rosa: SMS + Chime cue (if a chime is online and not snoozed) | n/a |
| T+0 | **Luis in parallel** when the household flag `mobility_limited` is set **and** it's freezing (ice) | Rosa is not mobility-limited |
| T+5 | Rosa: voice call (es-US) | Ring saw the pickup |
| T+10, or at-risk (whichever is first) | Luis: SMS, then call | Pickup seen |
| T+20 | Ana: call + SMS | Pickup seen |
| Deadline rule | Every rung fires **at least 15 min before the estimated unsafe time**. Squeeze the gaps (`gap = min(10 min, minutes_left / (rungs_left + 1))`) instead of the fixed `LADDER_GAP` (`responder.py:30,221,271`) | |
| No answer / busy (voice event) | Climb the next rung **now**, not after the gap | |

**Implementation sketch.**
- Add `contact_plan` (a list of rungs: person, channels, minutes after T) to `Household`.
- Add `channels`, `mobility_limited`, `consent_at` and `quiet_hours` to `Person`.
- `Responder.followup` reads the plan, and the `package_removed` observation closes the incident
  and cancels pending rungs. Log each cancelled rung as a ledger Action
  ("Call to Luis not needed: Ring saw the box picked up 14:40"). On camera, that line is the
  whole product in one sentence.

### 1.5 Consent (family, neighbour, Rosa)

- **Rosa must consent.** She is an adult with capacity, and a family member wiring her
  doorbell to an AI is a dignity issue.
  - Onboarding (in Ana's setup screen): *"Rosa agreed to these alerts on ⟨date⟩"*, a required
    checkbox stored as `consent_at`.
  - The first message to Rosa is an introduction, not an alert: *"Hola Rosa, soy el aviso del
    timbre que puso Ana. Le escribiré solo si su medicina se queda afuera."*
- **Helpers (Luis, Ana).**
  - Each gets a one-time introduction SMS with STOP language. Carriers and CTIA expect opt-out
    wording on the first message of any SMS program.
  - Store the opt-in time.
  - Pre-recorded voice calls to mobile numbers need documented prior express consent under the
    TCPA. Record it and say so in the README; don't argue exemptions.
- **Minimal disclosure:** helpers get "a medicine that needs to stay cold", not the diagnosis.
- **Production reality to state honestly:**
  - Real US recipients need a **registered** origination number (toll-free verification or
    10DLC), which takes weeks.
  - The demo goes to one sandbox-verified phone. The README already says "sandbox"; add a
    sentence on registration.

### 1.6 What one founder plus AI can build in about 10 days (honest)

| Item | Effort | Realistic? |
|---|---|---|
| Template rewrite, no LLM for the patient, no-prefix rule, retrieved message to Rosa, mock wording fix | 1.5 h | Yes |
| `contact_plan` + deadline-aware gaps + cancel-on-pickup ledger entries + tests | 3 h | Yes |
| Ring Chime cue (SDK + rung, tested against fixtures shaped like the docs) | 3–4 h | Yes, spec only |
| Voice call through End User Messaging v2 + Polly SSML + answer events | 6–8 h code, plus a **30 min account spike first** | Probably. It depends on getting a voice-capable origination number and on the destination (+52) being supported for voice in your account. If the spike fails, see the fallback in §2 #5 |
| Two-way SMS or DTMF replies | 2+ days plus number registration | **No.** Put it in *What's next* |
| Alexa announcements on Echo | Needs an Alexa skill plus certification | **No** |

---

## 2. Top 5 changes, ranked by (impact on winning) ÷ (effort)

Impact is on a 1–10 scale across the five personas. "Ratio" = impact ÷ hours.

| # | Change | Impact | Hours | Ratio | Risk |
|---|---|---|---|---|---|
| 1 | Rosa-first patient rung (templates, fall-safe wording, deadline ladder, cancel on pickup) | 8 | 4.5 | 1.8 | Low |
| 2 | 15-minute wording test with 3 Spanish-speaking adults aged 75+ | 6 | 2 | 3.0 | Low (consent) |
| 3 | Ring Chime in-home cue, shipped as `ringpartner` 0.2.0 | 7 | 4 | 1.75 | Low–med |
| 4 | SDK adoption pack (`py.typed`, mypy, badge, release, coverage matrix, Trusted Publishing) | 5 | 2.5 | 2.0 | Low |
| 5 | Spanish voice call with answer events closing the loop | 9 | 8 | 1.1 | Medium |

**Order of work:**
- #2 has the best ratio, but run it after #1 so you test the new wording.
- Do #1, #2 and #4 regardless.
- Do #3 next.
- Start #5 with the 30-minute account spike on **day 1**, so you know by Oct 15 whether the
  phone will ring on camera.

### #1 Rosa-first patient rung (4.5 h)

- **Why judges care.**
  - Appstore PM and the specialist: this turns "an alert system" into "a system that works
    for the person at the door".
  - Ring Eng: it is deterministic, testable safety logic, and the LLM is kept away from the
    vulnerable user.
- **Sketch.**
  - `responder.py`:
    - Make `TemplateWriter` the only writer for `role == "patient"`.
    - Rewrite the templates as in §1.3.
    - Send `porch_retrieved` to the patient too.
    - Replace the fixed `LADDER_GAP` with the deadline rule.
  - `domain.py` (`Person`): add `channels: list[str]`, `mobility_limited: bool`,
    `consent_at: str | None`.
  - `household.py`: add `contact_plan`.
  - `notify.py`:
    - Route per person (`person.channels`) instead of one global channel (`:120`).
    - Drop the prefix for the patient.
  - Dashboard:
    - In the "Who we've contacted" card, show "Call not needed: Ring saw the pickup".
    - Fix `script.ts:166-169` (wording, channel, "insulin" sent to Luis).
  - Tests:
    - Ladder squeeze when 25 min are left.
    - Parallel Luis when `mobility_limited` and freezing.
    - Cancel on pickup.
    - The patient message is ≤160 characters and has no digits.
- **Video line:** "Rosa never has to reply. Her Ring doorbell sees when the box goes inside, and
  everyone else stands down."

### #2 Test the wording with three real older adults (2 h, no code)

- **Why judges care.** `docs/BUSINESS.md` says *zero* customer conversations. A real reaction
  from the target user is the strongest proof of impact you can add in two hours.
- **Who.** Brandon is in Tampico, surrounded by Spanish-speaking older adults (family,
  neighbours, patients met through JUN0Care).
- **Protocol.**
  - Show the current SMS, then the rewrite, on a basic phone at the person's normal text size.
  - Play the Polly audio (generated locally with `SynthesizeSpeech`; it costs a fraction of a
    cent).
  - Ask three questions:
    - "¿Qué le está pidiendo?" (What is it asking you to do?)
    - "¿Quién cree que se lo manda?" (Who do you think sent it?)
    - "¿Qué haría si hay hielo?" (What would you do if there's ice?)
  - Write down the answers word for word.
- **Output.**
  - A 6-line "Wording test" section in the README: n=3, ages, the single change it caused.
  - One anonymised quote (voice only, or a subtitle) in the video.
- **Risk.** Get verbal consent. Don't show faces or names. Be honest that n=3 is a hallway test,
  not research.

### #3 Ring Chime as Rosa's in-home cue, shipped as `ringpartner` 0.2.0 (4 h)

- **Why judges care.**
  - **Ring Eng and PM:** it uses the newest Partner API surface (Chimes; dynamic scopes, Aug 24,
    2026) and follows the documented best practices to the letter:
    - detect a chime by capability `audio.supported_actions ∋ "chime.play"`, not by
      `image_url`;
    - check `status.online` and **respect `audio.snooze.active`** (best practice 7);
    - read `audio_ref` from the configurations slots;
    - play only as a **clearly disclosed automation** (best practice 6).
  - Nobody else will touch it.
  - **Open Source judge:** a 0.2.0 release with new API coverage, a CHANGELOG entry and tests
    is an "alive project" signal.
- **Sketch.**
  - `ringpartner/src/ringpartner/client.py`:
    - Add `play_chime(device_id, *, event="ring-appstore-event-1")`. It runs the documented
      4-step flow: capabilities → status → configurations → `POST …/media/audio/playback` with
      the JSON:API `{"data":{"type":"audio","attributes":{"audio_ref":…}}}`.
    - Raise typed `ChimeSnoozed` / `ChimeOffline` errors.
    - Add the async twin.
  - `models.py` already has `Device.is_chime` (CHANGELOG). Add `Device.chime_volume` and
    `chime_slots`.
  - Fixtures copied from the documented response shapes (`ring-api.md:5492-5734`), plus
    respx tests.
  - CLI: `ringpartner chime play <id>`.
  - DoorLedger:
    - A `ChimeNotifier` with `channel = "chime"`.
    - Setup check: "Rosa's chime volume is 2. Consider raising it in the Ring app" (volume is
      read-only to partners). That is a real accessibility touch built only from the API.
- **Risk and honesty.**
  - Early Access, not in the Playground, not exercised on hardware.
  - Label it "built to the documented spec; tested against doc-shaped fixtures". In the
    dashboard, the cue row says "Chime: not linked in demo".
  - The scope is for development only and can't ship publicly before GA. Say that in the
    README.

### #4 SDK adoption pack (2.5 h)

What the OSS judge checks in 60 seconds, and what is missing today:

| Gap (verified) | Fix |
|---|---|
| README and PyPI say "typed", but there is **no `py.typed`** (`ringpartner/src/ringpartner/`), so mypy users get "missing library stubs" | Add `py.typed`, run `mypy --strict src` in CI, fix what it finds |
| CI is green on both repos (`gh run list`), but **no CI badge** | Add a badge to both READMEs |
| No **git tag or GitHub Release** for 0.1.0, though it's on PyPI | Tag `v0.1.0`, publish release notes from the CHANGELOG |
| PyPI shows the upload came from a laptop, without **Trusted Publishing** | Add a `release.yml` that publishes on tag through PyPI Trusted Publishing, and use it for 0.2.0. The provenance badge shows on PyPI, and you never handle a token again |
| No repo **topics**; Discussions off | Add topics `ring`, `ring-appstore`, `whep`, `webrtc`, `webhooks`, `python-sdk`; turn on Discussions |
| No **API coverage matrix** | A table in the README, one row per endpoint, with columns *method · sync/async · tested · verified on Playground*. Include the gaps honestly (sensors, chime until #3, app-integrations PATCH, `DELETE /v1/accounts/me/app-integrations`). It is the single most persuasive OSS artifact |
| The doorledger repo vendors a copy at `packages/ringpartner` (identical today, `diff -rq` clean) | Say in both READMEs which copy is canonical, or pin `ringpartner==0.2.0` from PyPI in `core/pyproject.toml`, so the flagship app visibly consumes the published package |

### #5 Spanish voice call with answer events (8 h, plus a 30 min spike)

- **Why judges care.**
  - **AWS Builder:** a service used for a real reason: landline, low literacy, low vision. It
    adds End User Messaging SMS & Voice v2, Amazon Polly voices, and event destinations that
    feed back into the engine.
  - **Everyone:** the first 20 seconds of the video get a **phone ringing and a calm Spanish
    voice**, which beats a silent SMS screenshot.
  - It also fixes a truth problem: today "Delivered" means "SNS accepted the publish"
    (`notify.py:93`), not "the handset got it".
- **Spike first (30 min).** In the End User Messaging console (us-east-1):
  1. Request a phone number with **VOICE** capability (US toll-free, about US$2/month), or check
     what can call +52 from your account.
  2. Add Brandon's phone as a **verified destination**. The sandbox allows only verified
     destinations.
  3. Send one `SendVoiceMessage` by hand.
  4. If any step is blocked, use the fallback below.

  Before trusting this sketch, check these in the boto3 docs: the `VoiceId` enum (for example
  `LUPE` for US Spanish) and whether `TimeToLive` and `DryRun` exist on `send_voice_message`.
- **Sketch.**
  ```python
  class VoiceNotifier:               # core/src/doorledger/notify.py
      channel = "voice"
      def send(self, person, message):           # message = the fixed patient template
          ssml = f'<speak><prosody rate="85%">{escape(message)}<break time="1s"/>Repito. {escape(message)}</prosody></speak>'
          r = boto3.client("pinpoint-sms-voice-v2").send_voice_message(
              DestinationPhoneNumber=person.phone,
              OriginationIdentity=os.environ["DOORLEDGER_VOICE_FROM"],
              MessageBody=ssml, MessageBodyTextType="SSML", VoiceId="LUPE",
              ConfigurationSetName="doorledger")
          return r["MessageId"]                  # "placed", not "delivered"
  ```
  - **Configuration set** `doorledger`, with an event destination → SNS topic → **SQS queue**.
    The local API long-polls SQS, so it needs no public endpoint.
  - Map the events (check exact names: `VOICE_ANSWERED`, `VOICE_NO_ANSWER`, `VOICE_BUSY`,
    `VOICE_COMPLETED`, `TEXT_DELIVERED`) to ledger updates:
    - **No answer or busy:** climb the next rung immediately.
    - **Answered:** "Rosa answered the call (14:12)". The voice still says "you don't need to do
      anything else"; answering is not the same as understanding, and the camera is still the
      proof.
  - **Move SMS onto the same v2 API**, with the same configuration set. Then "Delivered" only
    appears after a `TEXT_DELIVERED` event, and Rosa always gets the same sender number. That
    alone is an accessibility gain: Ana saves it in Rosa's phone as *"Timbre de la puerta"*.
  - **Tests:** botocore `Stubber` for the send; a fake SQS event that drives the ladder.
- **Fallback if the account blocks voice.**
  - Generate the exact SSML with Polly `SynthesizeSpeech` (es-US neural voice), commit the MP3,
    and play it in the dashboard as **"What Rosa hears (call not placed in this demo)"**.
  - Implement the `VoiceNotifier` with Stubber tests anyway.
  - Honest, still valuable, about 3 h.
- **Cost.** Number about US$2/month plus about US$0.01–0.02/min US (check pricing). Inside the
  US$30 budget.

### Next, if time remains: durable escalation on AWS (6–8 h, medium risk)

- **The problem.** Open incidents live in `Responder.incidents`, an in-memory dict
  (`responder.py:170`). If the API restarts at 14:20, Rosa's escalation is silently forgotten.
  A Ring Eng judge will ask "what if your server restarts?". An AWS judge will ask why
  safety-critical timers live in a laptop process.
- **Sketch.**
  - When a porch incident opens, create one-time **EventBridge Scheduler** schedules, one per
    remaining rung. Each one invokes a small Lambda (or posts to the API) that re-checks the
    ledger in DynamoDB and fires the rung.
  - `package_removed` deletes the remaining schedules.
  - Pair it with the already-designed Lambda webhook receiver (`docs/aws_architecture.md:149`).
- **Do this only if #1–#5 are done by Oct 18.** Otherwise one honest README line ("timers are
  in-process in the demo; production uses EventBridge Scheduler") is enough.

### The first 20 seconds of the video (adjusting review-03 §6, not repeating it)

- **Lead with sound.**
  - 0–5 s: the Ring Playground frame of the snowy step, then the **phone rings**.
  - 5–14 s: Polly's slow Spanish ("Hola, Rosa. Le habla el aviso del timbre que puso su hija
    Ana…") with large English subtitles.
  - 14–20 s: split screen. The Ring frame shows the box gone (own footage `pickup.mov`), and the
    dashboard shows "Call to Luis not needed: Ring saw it go inside".
- **Narration (one sentence):** "Rosa is 81, doesn't use apps, and shouldn't walk on ice. So
  DoorLedger calls her in Spanish, and her Ring doorbell tells it when she's done."
- **If the voice spike fails:** the same shot with the Polly MP3, captioned "Voice call (audio
  generated by Amazon Polly; call not placed in demo)".

---

## 3. Red flags a skeptical judge finds in 5 minutes (new; not in reviews 01–03)

1. **Hosted demo: fabricated weather source and an implausible date.**
   - The header says **"Monday, October 12 · 16°F (−9°C) outside · Open-Meteo"**, but the
     temperature is scripted (`web/dashboard/lib/mock/script.ts:83`, `source: "open-meteo"`).
   - The mock uses today's date (`lib/mock/engine.ts`; `scenarios.py:130` does the same in the
     backend).
   - On judging day, Chicago will be about 10 °C. A judge who checks the weather catches a false
     data attribution in the first screen.
   - **Fix (15 min):** source `"scenario"` labelled "scenario: Chicago, January", and pin the
     replay to a January date.
2. **Everything says "Delivered" in the hosted demo**, where nothing is sent
   (`script.ts:163-169`, `delivered: true`). In the backend, "delivered" means SNS accepted the
   publish (`notify.py:93`). **Fix:** show "Sent (demo)" in mock mode, and "Delivered" only
   after a real delivery event (§2 #5).
3. **Ana gets "app alerts"** (`script.ts:164,168,169`, `channel: "push"`). There is no
   DoorLedger app, and Ring partner apps have no push API. Make sure the in-flight SMS-vs-app fix
   covers **Ana**, not only Rosa.
4. **The mock's wording doesn't match the backend.** The mock says "su insulina" (`script.ts:166`);
   the backend says "su medicina" (`responder.py:100`). The mock tells Luis "Rosa's insulin"
   (`:167`); the backend says "refrigerated medication" (`responder.py:69`). A judge who runs both
   sees two products. Generate the mock's messages from the same template strings (export them as
   JSON), or at least copy them over.
5. **The "don't use your insulin" message** (`responder.py:104`). A clinician on the panel will
   flag it at once. Fix it as in §1.3.
6. **README TODOs visible on the front page:** `README.md:16` (video), `:272` (`# TODO: repo goes
   public at submission`, but the repo is already public, so it looks unmaintained), `:484` (CC BY
   creator). Remove `:272` now.
7. **PyPI and GitHub provenance gaps:**
   - "typed" without `py.typed`;
   - no tag or release;
   - no Trusted Publishing;
   - no CI badge, no topics;
   - the PyPI maintainer handle differs from the GitHub owner `HaDeZIB`. Harmless, but add an
     "Author: Brandon Garcia (@HaDeZIB)" line in the PyPI README so the link is obvious.

   See §2 #4.
8. **The LLM can lengthen and cut safety messages** (`responder.py:116` allows 300 characters;
   `:156` slices at 480). Patient messages from templates only (§2 #1). For family, cut at a
   sentence boundary, not a character index.
9. **The escalation is not durable** (`responder.py:170`). Either fix it (§2, next item) or
   disclose it.

---

## 4. Cut or simplify (things that dilute the story)

- **The LLM writing alerts to the patient: cut it.** Keep Claude for the daily summary, the
  Q&A and (optionally) family wording.
  - The story gets stronger: "we deliberately keep the LLM away from the 81-year-old".
  - AWS depth doesn't suffer: AgentCore, Nova vision and voice carry it.
- **Numbers in patient messages:** temperatures and minutes go to family only.
- **Video time sinks:**
  - Drop the terminal `ringpartner simulate` shot (2:08–2:22, a simulated webhook in a
    terminal).
  - Turn the statistics title card (0:38–0:52) into a 4-second lower-third overlay.
  - Keep the aide/EVV act at **≤20 s**.
  - That frees about 30 s for Rosa's call, the chime and the cancel-on-pickup moment.
- **Don't add Amazon Connect, Alexa or two-way SMS.** Each is 2+ days or a registration process,
  and each would show as half-built.
- **Telegram:** keep the code as a developer channel, but drop it from judge-facing text. Rosa
  will never use it, and it competes with the SMS/voice story.
- **The vision-read 6-digit fallback and the pharmacy PDF:** keep in the repo, keep out of the
  video. Both are implemented-but-unexercised side quests.
- **The vendored SDK copy:** consume the PyPI package, or explicitly mirror it (§2 #4). Don't
  maintain two silently.

---

## 5. If you do only three things

1. §2 #1, the Rosa-first rung with the §1.3 templates (4.5 h).
2. §3 items 1–4, hosted-demo truth (1 h).
3. The §2 #5 **30-minute voice spike on day 1**. Its result decides the video opening.

Everything else is upside. The non-negotiable is still Brandon's own footage and the video:
without `pickup.mov`, "the doorbell is the reply" stays `Simulated`.
