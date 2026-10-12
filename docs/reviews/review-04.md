# Review 04: independent judging panel (12 Oct 2026, ~00:30 Tampico)

**What was reviewed.** Public GitHub HEAD `ea6bcc1` (cloned fresh, not the working tree), the hosted demo
<https://doorledger.vercel.app>, <https://github.com/HaDeZIB/ringpartner>, <https://pypi.org/project/ringpartner/>,
`docs/VIDEO_SCRIPT.md`, `docs/SHOT_LIST.md`, `~/ring-hackathon/HANDOFF.md`, reviews 01–03 and improvements-04.
- **Tests on the clone:** `uv run pytest -q` → **256 passed, 2 skipped** in 25 s, with AWS credentials blanked.
- **CI:** green on `ea6bcc1`. The previous run (`6a0c9ab`) shows *cancelled*.
- **Secrets scan, all 37 commits:** clean. The real AWS account ID is absent from history (checked against
  `sts get-caller-identity`). The only 12-digit IDs are the AWS docs example `111122223333`. No tokens, phone
  numbers, Connect IDs or e-mails appear. All commits use the noreply author.

**Panel:** Ring Director of Engineering, Ring Appstore/partner PM, AWS Solutions Architect (AWS Builder),
Open Source maintainer, geriatric care and accessibility expert, and a Devpost veteran judge. The real panel
listed on Devpost for this track includes *Roman Alekseenkov (Director of Engineering, Ring)*, *Alex Clausen
(Senior Manager, Ring Appstore)* and *Harish Komaragiri (Principal PM, Ring Developers)*. For AWS it includes
*Brittney Hurst* and *Chris Melissinos*. Write for those five people.

---

## 0. The official rules (fetched 12 Oct from amazonappdev2026.devpost.com: `/rules`, `/`, `/details/faqs`, `/updates`)

### Judging
- **Stage 1 is pass/fail.** The rules: "whether the ideas meet a baseline level of viability, in that the
  Project reasonably fits the theme and reasonably applies the required APIs/SDKs".
- **Stage 2 uses "equally weighted criteria"**, so each counts 25%:
  - **Tech Implementation:** "How well is the project built, and how effectively does it use the required
    tech? Does it effectively leverage the required APIs, SDKs, or device capabilities for the specified
    track … or mini-challenge?"
  - **Design:** "Does the project deliver a complete, coherent product experience? Is the interaction model
    intuitive and well-considered for the target device or platform?"
  - **Potential Impact:** "Does the project make a credible, specific case for solving customer needs? Could
    it realistically serve an audience beyond the hackathon? (Examples: … Ring Appstore)"
  - **Quality of the Idea:** "Is this a creative, imaginative use of the required tools? Does the team
    demonstrate a genuine understanding of the developer ecosystem and the end-user needs…". For Ring,
    "Obvious: motion detection alert, basic doorbell live view. Creative: non-security use case
    (accessibility aid, care-taking monitoring, package/delivery management), business system integration…,
    multi-camera pipeline, event-based triggers".
- **Bonus:** "Amazon's internal review team assesses each submission's friction log entries … and passes a
  recommended bonus — up to 10% — to the Stage 2 judging panel".
- **Tie-break:** "the highest score in the first applicable criterion", which is **Tech Implementation**.
- **Mini challenges are scored on the same four criteria:**
  - **AWS Builder:** "Obvious: single Bedrock call…, S3 for storage. Creative: multi-service pipeline (Bedrock
    + AgentCore + Strands), agentic architecture…, agent orchestration patterns."
  - **Open Source:** "Obvious: README update, typo fix… Creative: meaningful feature addition with tests, bug
    fix that unblocks other developers, new integration pattern".
- **Prize limit:** "A project can only win one (1) track prize and one (1) mini challenge prize."

### Submission requirements (verbatim where it matters)
- **Video:** "should be less than three (3) minutes. Judges are not required to watch beyond three minutes".
  It "should include footage that shows the Project functioning on the device for which it was built", it
  "must be uploaded to and made publicly visible on YouTube or Vimeo", and it "must not include third party
  trademarks, or copyrighted music or other material unless the Entrant has permission". The overview page
  also says "public and in English" and "lead with your best material".
- **Ring:** "The demo video must show the project working through a simulator or an actual Ring device".
  Separately: "The repository must demonstrate use of your track's required technology at runtime in your
  code — imported and actually called… not just named in the README."
- **Text description:** it "should explain the features and functionality of your Project".
- **Repository:**
  - It "must contain all necessary source code, assets, and instructions required for the project to be
    functional".
  - For a public repo, the "license should be detectable and visible at the top of the repository page (in
    the About section)". ✅ Apache-2.0 is detected on both repos.
  - "The Project's code repository must include clear setup and run instructions".
- **Testing:** "Judges are not required to test the Project and may choose to judge based solely on the text
  description, images, and video". **In practice the video *is* the submission.**
- **Product feedback**, required "for each tool, API, or SDK used":
  - what you used, what worked well and what needs work;
  - onboarding;
  - "Would you build with these devices and services again? Yes/No and why";
  - for AWS Builder, the AWS services must be described *in this answer*.
- **Open Source fields:** "contribution URL, project repository URL, GitHub username, and a description of
  what you did, how it works, and why it matters."
- **Language:** "All Submission materials (demo video, written description, and code documentation) must be in
  English" or come with an English translation. Spanish call audio with English subtitles complies.
- **Third-party integrations:** "Entrant must be authorized to use them in accordance with any terms and
  conditions or licensing requirements".
- **FAQ on licensed or CC footage:** "Properly-attributed, brief supporting or background footage is
  typically fine - check with us on the specifics … before finalizing."
- **Deadline:** "Friday, October 23, 2026 (12:00 pm Pacific Time)". HANDOFF.md §1 says "jueves" (Thursday);
  it is a **Friday**. Judging runs 9–20 Nov and winners are announced around 3 Dec.
- **Office Hours #2:** Monday 19 Oct, 9:00 am PT. Use it (see §5).

### Eligibility: can a resident of Mexico enter and be paid? **Yes.**
- **Who may enter:** "Individuals who are at least the age of majority where they reside as of the time of
  entry".
- **Who is excluded:** "Individuals who are residents of … a country … where the laws of the United States or
  local law prohibits participating or receiving a prize in the Hackathon (including, but not limited to,
  Brazil, Quebec, Russia, Crimea, Cuba, Iran, and North Korea and any other country which is comprehensively
  sanctioned by the U.S. Treasury's Office of Foreign Assets Control)". **Mexico is not named and is not under
  comprehensive OFAC sanctions.** The overview page says "All countries/territories, excluding standard
  exceptions".
- **Payment:** "residents of other countries may be required to provide a completed W-8BEN form", and the
  Sponsor "reserves the right to withhold a portion of the prize amount to comply with the tax laws". Winners
  pay wiring and FX fees and must report the prize locally (to the SAT). Prizes are paid "within 60 days" of
  the forms being received, and the forms are due "ten (10) business days" after they are sent.
- **Caveat:** prizes are "subject to verification of the identity, qualifications and role of the potential
  winner in the creation of the Submission". Keep the git history and this review trail.

**Not found:** the Devpost pages give no per-track submission counts, and the project gallery is
unpublished. The placement estimate below is therefore a judgement.

---

## 1. Scores (official criteria, 25% each)

**State A** is the public repo and hosted demo as they are tonight, plus a video made exactly from today's
`VIDEO_SCRIPT.md`. (With no video at all, the entry fails Stage 1.)

| Criterion (25% each) | Ring Eng | Appstore PM | AWS SA | OSS | Geriatric | Devpost vet | **Mean** |
|---|---|---|---|---|---|---|---|
| Tech Implementation | 7.5 | 7 | 8 | 8 | 7 | 7.5 | **7.5** |
| Design | 6 | 6.5 | 7 | 6 | 5.5 | 6.5 | **6.3** |
| Potential Impact | 6 | 6.5 | 6 | 6.5 | 6 | 6.5 | **6.3** |
| Quality of the Idea | 8 | 8 | 7 | 7.5 | 7.5 | 8 | **7.7** |

- **State A overall:** **6.95**. With a realistic **+5–7%** friction-log bonus (17 good entries, minus the F1
  credibility issue in finding 7), that is about **7.3**.
- **State B** adds four things: (1) the live Playground → phone-rings take, (2) the Rosa ladder with fixed
  templates, (3) own footage and (4) the §2 truth fixes. Projected: Tech 8.3 · Design 7.6 · Impact 7.0 ·
  Idea 8.3 = **7.8**, or **≈8.3** with the bonus.

**Placement estimate, Ring track (honest).** The rules page shows 53,611 registrants. At typical Devpost
completion rates, expect roughly 250–500 Ring submissions, most of them motion alerts or live-view wrappers.
- **State A:** top 10 is likely. 1st place ≈ **20%**, 2nd ≈ 20%.
- **State B:** top 5 is likely. 1st ≈ **30–35%**, 2nd ≈ 25%.
- **The main threat** is a polished caretaking or accessibility entry with *real-time* Ring footage. A known
  rival in the same niche, *Care Handoff* (github.com/blucca/care-handoff), already connects to the Playground
  over WHEP.
- **Mini challenges** (only one can pay; they are judged against entries from all four tracks):
  - **Open Source** ≈ 30%. A real PyPI SDK that fills a gap Ring documents is strong. Zero releases, no
    topics, a CLI default that fails on the official simulator, and a name built on Ring's trademark pull it
    down.
  - **AWS Builder** ≈ 25–30%. Bedrock, Strands, AgentCore, DynamoDB, SNS and **Connect** is a genuine
    multi-service story, but Alexa+ teams will bring AgentCore-heavy MCP agents.
  - **Lead the Devpost text with Open Source and still fill in the AWS fields.**

---

## 2. The 10 harshest findings a real judge hits in 5 minutes

Ordered by how fast a judge sees them. None repeats a still-correct item from reviews 01–03 or
improvements-04 unless it is still live on the public surface; those are marked *(still live)*.

| # | Finding | Evidence | Fix |
|---|---|---|---|
| 1 | **The Ring integration is never shown live.** Every Ring pixel in the demo is 12 JPEGs replayed and "re-timed". Webhooks are simulated, and the live poller is "not part of the offline demo". For a Director of Engineering, "your Ring app has never reacted to Ring in real time on camera" is the gap that decides Tech Implementation, and Tech Implementation breaks ties. | `README.md:49-53`, `fixtures/ring_playground/package/frames/` (12 files), `VIDEO_SCRIPT.md:16` "re-timed" | Build a **live mode**: real clock, insulin window = now, a Playground token, the history poller (`live.py:181`). Record **one unbroken take**: press *Package* in the Playground console, the dashboard flags it (Nova live, with latency), and a phone on the desk rings. See §4 #1. |
| 2 | **A false claim on the front page:** "Built with Claude Code (Anthropic Claude **via Amazon Bedrock**)". The 27 commit trailers say *Claude Opus 5.5*. Your own friction log says 5.5 models are "not available for this account" on Bedrock, and this Claude Code session runs on an Anthropic OAuth login (`CLAUDE_CODE_USE_BEDROCK` is unset). An AWS judge who reads A3 next to the trailers catches it. | `README.md:24,497`, `VIDEO_SCRIPT.md:26`, `FRICTION_LOG.md` A3 | Say "Built with Claude Code (Anthropic)". Drop "via Amazon Bedrock" everywhere, including the video end card. AWS Builder doesn't need it: the runtime services carry it. |
| 3 | **Unfinished front page.** The demo video is a TODO; the clone line says "TODO: repo goes public at submission" though the repo is public; the CC BY author is a TODO. Stale numbers: **244** tests (actual 256); "privacy-zone masking and E2EE skipping … not yet covered by tests" (they are); "poller reads the newest page without an `event_types` filter" (fixed in `6a0c9ab`). *(Partly still live from improvements-04 §3.6.)* | `README.md:16,22,272,322,435-436,438-439,484-485`; `fixtures/ring_playground/README.md:9-10` lists `vehicle/` and `default/` folders that don't exist | One 20-minute doc pass, then a CI check that greps for `TODO` and for the test count. |
| 4 | **A CC BY 4.0 work redistributed without its author.** The frames, the evidence JPEG and the hosted demo's frame credit only "package clip CC BY 4.0". CC BY *requires* the creator's name. The rules require authorisation for third-party data, and the FAQ asks you to *check with them* about CC footage. The author is known (HANDOFF §6.5: YouTube user *frollard*) but isn't committed. | `NOTICE:33-34`, `README.md:484`, `VIDEO_SCRIPT.md:30`, hosted-demo PROOF caption | Commit the credit today: title, author, link, license, "clipped; frames re-encoded". Put it on the evidence frame caption and the end card. Ask in the Devpost forum or at Office Hours #2 whether Playground footage needs anything more. |
| 5 | **The hosted demo still misstates its sources** *(still live)*. It shows "16°F … · Open-Meteo" on a scripted temperature, "Delivered" on 4 messages nothing sent, "Sent an **app alert** to Ana" (there is no app), and today's date. **New:** "**94% confidence**" is typed by hand into the mock (`script.ts:138`). It is not in the Bedrock cache (0.9 / 0.95), and Nova's "confidence" is the model's self-report, not a calibrated probability. | `web/dashboard/lib/mock/script.ts:79,84,138,163-170`; live at doorledger.vercel.app | In flight. Add: drop the % or label it "model-reported", and take it from `vision_cache.json`. |
| 6 | **The SDK's CLI default fails on the official simulator.** The README says the CLI's default snapshot ("latest in the last 10 min") returns 403 on the Playground. The Quickstart also *leads* with `between=`, the form that 403s. On PyPI, the relative links (`examples/`, `examples/*.py`) resolve to pypi.org and 404. The vendored copy has drifted from the standalone repo (`examples/README.md` and `list_devices_history.py` differ; `examples/fixtures` exists only in the standalone repo). | `packages/ringpartner/README.md:32-35,49,204-206`; PyPI long description; `diff -rq` | Ship **0.1.1**: CLI default `at=<latest history event start>`, absolute GitHub URLs in the README, `py.typed`, a `v0.1.1` tag and Release (both repos have **0 releases and 0 topics**). Then make the vendored copy a pinned PyPI dependency, or a byte-identical mirror checked in CI. |
| 7 | **The friction log's only "Critical" entry is your own browser's fault.** F1 is "Resolved (incognito). The likely root cause is a browser extension in the regular profile". A Ring PM will discount the whole log if the top item isn't Ring's bug, and the log is worth up to 10%. | `FRICTION_LOG.md` F1 | Downgrade F1 to Medium ("the registration flow fails silently with a 404 instead of an error"; the actionable ask is an error message). Add the **voice findings** as new High entries: End User Messaging voice can't call +52 (`INVALID_IDENTITY_FOR_DESTINATION_COUNTRY`, a support case is needed), and Amazon Connect was the only path that reached Mexico. |
| 8 | **The README is 502 lines; judges read about 60.** The first screen has 9 table rows of service names. There is no screenshot or GIF above the fold. Root holds `CHECKPOINT.md` and `STATUS.md` (internal logs, one titled "pause on 11 Oct, 3:30 pm"), which reads as an agent's scratchpad. Every commit is dated 2026-10-11, so "37 commits in one day + 256 tests" invites the "AI-generated dump" reflex. | `README.md` (502 lines), repo root | A 120–150 line judge README: hero GIF (10 s), 3-line problem, "what's real" in 5 bullets, 60-second offline run, links. Move the deep sections to `docs/`. Move `CHECKPOINT.md`/`STATUS.md` to `docs/log/`. Over the next days, commit in small dated steps; that is your proof of work. |
| 9 | **The hero feature is still a grey box** *(still live)*: "No camera frame · Simulated event · footage not filmed yet". The README pitches aide check-in as the differentiator, and the presence code has **never been read off any real camera**; it is only a synthetic model. If tomorrow's ingest fails, the core claim has zero real evidence. | hosted demo VisitCard; `README.md:375-376,427-429` | Tomorrow's shoot (§3) must include a **verify-on-set** step: ingest take 1 and confirm a valid check-in before moving on. |
| 10 | **The impact case has a channel gap a Ring Appstore PM will spot.** The *primary* buyer is agencies (B2B, US$15 per client), but distribution is a Ring Appstore app installed on each client's own Ring account, which also needs a Ring Protection plan. How does an agency get 200 Medicaid clients to own a Ring, subscribe and link a partner app? There are still zero customer conversations. **New cost:** voice calls change COGS, and the unit economics don't include Connect yet. | `docs/BUSINESS.md:3-4,10-14,36-41` | One honest paragraph: the wedge is **family-installed** (B2C, the household that already owns a Ring), and the agency EVV layer comes later. Add Connect per-minute and number costs to COGS. Add the n=3 older-adult wording test (improvements-04 #2), which you can film tomorrow, audio only. |

**Also seen; lower priority but real:**
- `README.md:120` names "UPS", a third-party trademark, in the example plan. Use "courier".
- "BrightPath Home Care" may collide with real agencies. Check before you put it on video, or use an obviously
  fictional name.
- The hosted demo strip opens over the content on mobile (375 px).
- The `ringpartner` name builds on Ring's mark (review-03 §3.8). Keep a fallback name ready, but don't rename
  before submission.

---

## 3. Video: critique of `VIDEO_SCRIPT.md` and `SHOT_LIST.md`, and tomorrow's shoot

### 3.1 What is wrong with the current script
1. **It is out of date with the product.** The call to Rosa doesn't appear anywhere. The 0:10–0:22 beat is a
   silent SMS ("Rosa got a text"), and improvements-04 already moved the opening to a ringing phone.
2. **Nothing in it proves "live".** Every Ring shot is a replay, and the one live-integration shot is a
   *simulated* webhook in a terminal (2:08–2:22). Cut the terminal shot. Replace it with the live Playground
   take (§2 #1).
3. **0:38–0:52 spends 14 s on a statistics card.** Make it a 4 s lower-third in the first 20 s ("US$14.5B in
   NY home-care claims had no matching visit record, NY Comptroller 2024").
4. **The architecture diagram (22 s) and the GitHub/README scroll (15 s) are dead air** for a 5-minute judge.
   Use 10 s for the diagram and 8 s for the SDK, with `pip install ringpartner` plus one runnable snippet.
5. **The Ask shot shows 7.6 s of latency on camera.** Cut the wait with a visible "⏱ 7 s" jump, or show the
   warmed-up call.
6. **"Ring webhooks and doorbell presses start a short watch session"** implies something the demo never
   shows. Say it only over the live take.
7. **The end card says "Claude via Amazon Bedrock"** (finding #2). Remove it.
8. **SHOT_LIST says "presses the doorbell"**, but there is no Ring device: a phone taped to the frame stands
   in for the camera. On screen it must read **"Own footage: phone camera standing in for the doorbell; button
   press simulated"**, or a Ring judge will think you're passing it off.
9. **A continuity problem nobody has flagged.** The Ring scene is a snowy Chicago step at −9 °C; the own
   footage will be a Tampico porch in October (sun, ~30 °C, maybe plants). Cutting from one to the other looks
   like two different houses, because it is. Handle it with framing and costume (checklist below) and the
   "Own footage" label. Don't pretend it's the same door.

### 3.2 The first 20 seconds (must show all of this)

| t | Picture | Sound |
|---|---|---|
| 0–4 s | Real Ring Playground frame of the snowy step, watermark visible. Lower-third: "Ring Developer Playground · official simulator". Overlay "−9 °C · insulin · 2:07 PM" | VO: "Rosa is 81, lives alone in Chicago, and her insulin was just left outside at nine below." |
| 4–7 s | Dashboard flash: "Package on porch · Amazon Nova 2 Lite · 1.4 s" (only if from a live call; otherwise "recorded Bedrock label") | n/a |
| 7–16 s | **The physical phone on a kitchen table rings.** Caller name: "Timbre · aviso de Ana". A hand answers on speaker. The calm Spanish voice plays; the SMS banner lands at the same moment | Real call audio, **burned-in English subtitles** |
| 16–20 s | Split: own-footage pickup (labelled) plus the dashboard line "Call to Luis not needed: Ring saw it go inside" | VO: "She never has to reply. Her Ring doorbell tells DoorLedger when it's inside." |

Name **Ring** and **Amazon** tools on screen in the first 20 s. The Devpost tips say: "Make the required tool
impossible to miss … call it out clearly in your demo video".

### 3.3 Tomorrow is ALL physical footage. Screen recordings will be redone after the 19 Oct freeze.
"Never re-shoot" is only realistic for **physical** footage: actors, the porch, phones ringing. The dashboard
will change four times before the 19th (Rosa ladder, honesty fixes, live mode), so tomorrow's screen captures
are a safety net only. **Re-capture screens on 19–20 Oct; it needs no props or people.**
- **The one physical shot that may legitimately be redone later** is the desk take where the laptop shows the
  live Playground and the phone rings next to it (§2 #1). Its setup is a laptop, a phone and a tripod in 15
  minutes.
- **To make tomorrow's call and SMS footage final, freeze the patient wording TONIGHT:**
  - the SSML of the call;
  - the SMS text.

  If either changes after tomorrow, the audio won't match the subtitles and the scene has to be shot again.

### 3.4 Recording checklist, ordered to minimise setup changes

**Block 0: tonight (no camera)**
1. Lock Rosa's call SSML and SMS text in code (fixed templates). Print the English subtitle lines.
2. Make sure the call is placed **by DoorLedger's code path** (`notify` voice channel →
   `start_outbound_voice_contact`), not a hand-run AWS CLI command. A call "the app didn't place" is a
   credibility problem if a judge asks. If the integration isn't merged by the shoot, trigger the code path
   from a script that calls the same notifier and say so in the README.
3. Open the Ring Playground and **copy the CC BY credit text** for the Package clip into a note (blocker
   #4).
4. Prepare the Caregiver Pass link (`/api/visits/V-MORNING/pass`, `X-Admin-Token`, API on the LAN with
   `--host 0.0.0.0`).
5. **Dry-run the ingest:** record a 10-s test clip of the Pass on the phone, AirDrop it, run
   `scripts/ingest_own_footage.py`, and confirm `valid check-in` hits. If the reader fails on real H.264/HEVC,
   you learn it tonight, not after the actors leave.
6. Charge everything, free 20 GB on the phones, and put a tripod or tape, a second tripod or a stack of
   books, and a clip-on mic or a third phone as the audio recorder within reach.
7. Get a one-line written release from each actor. Amazon gets publicity rights to "name, likeness, voice"
   (rules §7 and §10).

**Phone settings, applied once at the start**

| Phone | Settings |
|---|---|
| **"Doorbell" camera phone** | Landscape, **0.5×**, 1080p 30 fps; **HDR video OFF** (matches Ring's look, and avoids HDR metadata quirks in PyAV); AE/AF lock (long-press); **Airplane mode ON** so no call interrupts a take (the clock keeps time); automatic date and time was ON before going to airplane mode; Grid ON for level |
| **Aide's phone (Caregiver Pass)** | Brightness 100%, Auto-Lock **Never**, True Tone and Night Shift OFF, **Do Not Disturb ON** (no banner over the QR), automatic time ON, Pass page open in the browser with the **"Press the doorbell"** line visible |
| **"Rosa's" phone (receives the Connect call and the SNS SMS, i.e. Brandon's verified +52 number)** | **Do Not Disturb and every Focus OFF**. Ringer ON, volume max, a **default system ringtone** (no song). For the session, **silence WhatsApp, Instagram, Gmail, Slack and JUN0Care notifications** (Settings → Notifications) so no lead or personal message appears. Save **the Connect caller number** as contact **"Timbre · aviso de Ana"** so caller ID shows a name (this matches the onboarding design). Notification previews **Always**. **Larger Text ON** (an accessibility cue for an 81-year-old; it looks right). Neutral wallpaper, no personal photos. Spanish UI is fine and in character. **Never show your own number on screen.** **Date and time:** shoot the call between **2:05 and 2:15 pm local**. Tampico is UTC−6, the same as Chicago in winter (CST), so the status-bar clock matches "2:07 PM" with no editing. Keep the lock-screen date out of frame (it says October) |
| **Mac for screen captures (safety net)** | Clean user or incognito profile without extensions, bookmarks bar hidden, Focus ON (no notifications), 1920×1080 (the dashboard scales to the 1280×720 layout, `globals.css:151`), cursor highlight ON. **AWS console:** crop the account ID, ARNs and the account menu. **Ring Playground:** blur the token and the account e-mail |

**Block 1: porch exterior with actors (daylight; overcast or full shade, no direct sun)**
- **Continuity dressing:**
  - Frame tight on the door, the mat and the step; no plants, palms, house number or street.
  - Actors in jackets, beanies and gloves.
  - A **plain brown cardboard box** about the size of the Playground one, with a blank white label. No
    Amazon, UPS or pharmacy logos, and no real insulin brand. Third-party trademarks are banned in the
    video.
- Mount the doorbell phone at 1.2–1.4 m, pointing outward and slightly down. Clap on camera at the start of
  every take (sync), and say the take number aloud.
1. **Take 1, check-in** (SHOT_LIST #1), **×3**. After the first good one, **AirDrop the original (Options →
   All Photos Data, not edited, not trimmed) and run the ingest on set.** Continue only if it shows a valid
   check-in. Trimming or editing in Photos can drop the `creationdate` metadata the time-step check depends on.
2. **Take 2, check-out** ×3.
3. **Take 5, 6-digit fallback at ~80 cm** ×1 (cheap now, impossible later).
4. **Take 3, package drop** ×2.
5. **Take 4, package pickup** ×3. This one carries "the doorbell is the reply", so it is the most important
   own shot. End on the empty step for 5 s.
6. **B-roll, 20 s:** a hand pressing the button; the box on the mat; the door closing. Use it to cover cuts.

**Block 2: kitchen table, phone call and SMS (start at 2:05 pm)**

Second camera on a tripod, framed on the physical phone on a table, with a fridge edge in shot. The audio
recorder sits 20 cm from the phone. **iOS screen recording does not capture call audio**, so you must film
the phone and record room audio; don't rely on a screen recording.
1. **Call take:** trigger the real Connect call through DoorLedger. Let it ring 3–4 times, answer on
   **speaker**, and let the full message play. ×2 takes (the second at about 2:12).
2. **SMS take:** the same framing, with the SNS SMS arriving and its banner readable. Then a close-up of the
   message opened at large text.
3. **Optional, high value:** with consent, play the call to 1–3 Spanish-speaking older adults. Record
   **audio only, or hands only**, and ask "¿Qué le está pidiendo?" (What is it asking you to do?). One 4-s
   quote is the strongest Potential Impact evidence you can add.

**Block 3: desk, live integration (laptop + phone + tripod)**
- Generate a fresh Playground token, which lasts about 30 min. Do this block right after generating it.
- One unbroken take, with a wall clock or phone stopwatch in frame:
  1. Click **Package** in the Playground console.
  2. The DoorLedger dashboard reacts.
  3. The phone next to the laptop rings.
- If live mode isn't ready tomorrow, skip this block. It is the one take you are allowed to do after
  19 Oct.

**Block 4: screen captures (safety net; redo after the freeze)**
1. Dashboard `porch_cold` at 60× (Today), then Agency, then the Ledger with the EVV export.
2. Ask: "Is mom's insulin OK?" after an AgentCore warm-up. Capture the response showing
   `runtime: agentcore`.
3. AWS console: the AgentCore runtime page and CloudWatch for that call, 3 s, cropped. Then the Amazon
   Connect flow designer showing "DoorLedger patient alert (es)" (this is AWS Builder evidence).
4. `pip install ringpartner` in a clean terminal, then `ringpartner devices` against the live Playground.

**Block 5: voice-over last** (after picture lock, around 20 Oct)
- English, about 150 wpm, a quiet room, the same mic as the room audio.
- Brandon's own voice beats Polly for a founder story. His accent is fine; clarity matters more than polish.

**Cut entirely:** the terminal webhook simulation, the 6-digit fallback, the pharmacy PDF, the GitHub README
scroll, any Telegram, the Playground Vehicle and Motion scenes, and music of any kind (silence or room tone
is fine).

---

## 4. Top 5 improvements before the 19 Oct feature freeze (impact on winning ÷ effort)

| # | Improvement | Why it wins points | Effort | Ratio |
|---|---|---|---|---|
| 1 | **Live end-to-end mode + the one-take video:** Playground button → history poller → event-time snapshot or WHEP → Nova live → Rosa's call and SMS through Connect/SNS. Show the measured latency on screen. This is the single proof that DoorLedger is a Ring app, not a replay. It hits Tech (the tie-breaker), Idea ("event-based triggers") and AWS. | Ring Eng +1.0 Tech; the money shot for the video | 4–6 h | **Highest** |
| 2 | **Truth pass**: README counts and claims, drop "via Amazon Bedrock", the CC BY author everywhere, fix the fixtures README, F1 severity, mock confidence / Open-Meteo / Delivered / app alert, a `TODO` grep in CI. Cheap, and it removes every "gotcha" a skeptical judge finds in 5 minutes. | Credibility across all criteria; protects the friction-log bonus | 1.5 h | Very high |
| 3 | **Finish the Rosa ladder** (in flight). Fixed templates; call + SMS at T+0; re-call at +5 if Ring hasn't seen the pickup; cancel on pickup, with the ledger line "Call to Luis not needed: Ring saw it go inside". Read the Connect contact outcome (`DescribeContact` disconnect reason, or Connect contact events through EventBridge) so the dashboard says **"Call answered 14:07"**, not "Delivered". | Design + Impact; the geriatric expert's whole critique | 4 h | High |
| 4 | **README diet + hero GIF + root cleanup** (§2 #8). Write the Devpost text from the slimmed README; also include the required per-tool feedback, with the Connect/End User Messaging story. | Design + the Devpost veteran's first impression | 1.5–2 h | High |
| 5 | **`ringpartner` 0.1.1 credibility release:** CLI snapshot default fixed, absolute links on PyPI, `py.typed`, a tag and Release, topics, Trusted Publishing, and a pinned PyPI dependency in DoorLedger. Plus the 2 new voice friction entries. | Open Source mini (≈30% → ≈40%), and the bonus | 2 h | High |

**Explicitly do NOT do before the freeze:**
- **Ring Chime cue** (improvements-04 #3). It is Early Access, the Playground has no chime, and you can't show
  it working. Time spent on something invisible in the video is time lost.
- DTMF or "press 1" in Connect, two-way SMS, Alexa announcements: "the doorbell is the reply" is the better
  story.
- EventBridge durable timers, the hash-chained ledger, Appstore shell screens, a TypeScript SDK port, new
  scenarios.
- More AWS services for the logo count. Connect is the last one; explain it well instead.
- Renaming `ringpartner` now. Keep a fallback name in a note.
- Re-filming actors after tomorrow. Plan so that only desk or screen shots can change.

---

## 5. Disqualification and credibility risks

| Risk | Severity | Status / action |
|---|---|---|
| **No video, or a video ≥3:00, not public, or not in English** | **Disqualifying** | Target 2:40. YouTube, *Public* (not Unlisted, to be safe). Burned-in English subtitles for every Spanish line. Check it in a logged-out browser |
| **CC BY attribution missing** (finding #4) | High (IP rule, and the third-party-terms rule) | Fix in the repo, the hosted demo, the video end card and the YouTube description. Ask Devpost about Playground clips at **Office Hours #2 (Mon 19 Oct, 9 am PT)** or in the forum this week |
| **False "via Amazon Bedrock" claim** (finding #2) | High credibility risk with the AWS judges | Remove it today |
| **Third-party trademarks in the video** (box logos, insulin brands, UPS, a song ringtone, phone app icons in frame) | Medium; explicitly prohibited | Props and phone settings per §3.4 |
| **Actors' and older adults' likeness and voice** | Medium | Written one-line releases; audio only or no faces for the older adults |
| **Overstated claims:** "Delivered" when no handset delivery was confirmed; "94% confidence"; "live" vision on cache hits; "Open-Meteo" on scripted weather; "presses the doorbell" in own footage | Medium; each one alone is minor, together they read as a pattern | §4 #2; label own footage precisely |
| **TCPA and consent for automated calls** | Low for the hackathon; real in production | One README sentence: prerecorded calls to US mobiles need prior express consent; the demo calls only the founder's verified phone |
| **Illinois BIPA** (the story is set in Chicago) | An *opportunity*, not a risk | Add one line: "no biometric identifiers (no face geometry) by design, which matters under Illinois BIPA". Ring and Amazon judges know this law well |
| **`ringpartner` uses the Ring mark** | Low–medium | The disclaimer is present. Keep a fallback name |
| **Secrets in the repo or history** | Clean | Verified: no account ID, tokens, phone numbers, Connect IDs or e-mails. The committed visit secret is intentional and documented. Keep the +52 number, the Connect instance and contact-flow IDs, and any per-deployment `*.vercel.app` URLs that carry the account slug out of the repo, the video and the Devpost text |
| **AWS cost after submission** | Low | Judging is 9–20 Nov; the hosted demo is mock-only. Release the Connect number after the video is final (it isn't needed for judging), or budget for it to the 20th |
| **Wrong weekday in HANDOFF** ("jueves 23-oct") | Process risk | The deadline is **Friday** 23 Oct, 12:00 PT (1:00 pm Tampico). Keep the 10:00 am internal target |

---

*Sources:* [Official rules](https://amazonappdev2026.devpost.com/rules) ·
[Overview](https://amazonappdev2026.devpost.com/) · [FAQs](https://amazonappdev2026.devpost.com/details/faqs) ·
[Strong Submission Tips](https://amazonappdev2026.devpost.com/updates/46538-strong-submission-tips) ·
[Updates](https://amazonappdev2026.devpost.com/updates) · [PyPI ringpartner](https://pypi.org/project/ringpartner/) ·
[Hosted demo](https://doorledger.vercel.app). Third-party listings that were searched but not relied on:
[startupgrantsindia](https://www.startupgrantsindia.com/competitions/build-ship-shape-amazon-developer-hackathon),
[internshala](https://internshala.com/competitions/?p=11209).
