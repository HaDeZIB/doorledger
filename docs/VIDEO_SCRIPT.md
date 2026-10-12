# DoorLedger: demo video script (target 2:40, English)

**Hackathon rules:**
- Under 3 minutes, public on YouTube or Vimeo, in English (Spanish audio needs English
  subtitles). No copyrighted music, no third-party trademarks. Best material first.
- It must show the project working through the Ring simulator (Developer Playground) or a Ring
  device.

**Our rules:**
- **Persistent corner label on every shot**, one of:
  - `Ring Developer Playground` (real Ring frames, simulator);
  - `Own footage: phone camera standing in for the doorbell; button press simulated`;
  - `Real call · Amazon Connect` / `Real SMS · Amazon SNS` (the founder's own verified test phone);
  - `Dashboard` (and `Simulated` on any step that has no footage);
  - `AWS console`, `Diagram`, `Terminal`.
- Every temperature on screen and in the voice-over is an **estimate**.
- The Spanish call and SMS get **burned-in English subtitles** (exact text below).
- Name **Ring** and **Amazon** on screen in the first 20 seconds.
- Times come from the code: Rosa is called and texted at **14:07**, called again at **14:12**,
  Luis is texted at **14:17**, Ana at **14:27**, and the box is brought inside at **14:40**
  (`porch_cold`). In `porch_early_pickup`, Rosa brings it in at **14:15** and the text to Luis is
  cancelled.

## Timeline

| Time | Picture (label) | Sound |
|---|---|---|
| 0:00–0:04 | Real Ring Playground frame of the snowy step, `Partner: RingDeveloperPortalPlayground` watermark visible. Lower-third: "Ring Developer Playground · official simulator". Overlay: "−9 °C · insulin · 2:07 PM" (`Ring Developer Playground`) | VO: "Rosa is 81, lives alone in Chicago, and her insulin was just left outside at nine below." |
| 0:04–0:07 | Dashboard flash: "Package on porch · Amazon Nova 2 Lite · 1.4 s" **only if captured from a live Bedrock call**; otherwise "Amazon Nova 2 Lite · recorded Bedrock label". Lower-third (4 s): "NY Comptroller audit 2022-S-31 (2024): US$14.5B in home-care claims had no matching visit record" (`Dashboard`) | Room tone |
| 0:07–0:16 | **The physical phone on a kitchen table rings.** Caller name: "Timbre · aviso de Ana". A hand answers on speaker; the calm Spanish voice plays (subtitle lines 1–3 below). The SMS banner lands at the same moment (`Real call · Amazon Connect` + `Real SMS · Amazon SNS`) | Real call audio, **burned-in English subtitles** |
| 0:16–0:20 | Split screen: own-footage pickup at the door (`Own footage: phone camera standing in for the doorbell; button press simulated`) + the dashboard ledger line **"Text to Luis not needed: Ring saw the box picked up at 2:15 PM. The doorbell is Rosa's reply."** (scenario `porch_early_pickup`; the card headline reads "Text to neighbor Luis not needed") | VO: "She never has to reply. Her Ring doorbell tells DoorLedger when the box has been picked up." |
| 0:20–0:34 | Dashboard at 60×, scenario `porch_cold`: 14:12 "Called again Rosa" → 14:17 "Texted neighbor Luis" (his message on screen: no mention of insulin) → 14:27 "Texted Ana (family)" → 14:40 brought inside, "est. 0.7 °C in the box" (`Dashboard`; the 14:40 pickup step is `Simulated` unless own footage is ingested) | VO: "If the box stays out, DoorLedger calls her again, then texts the neighbor, then her daughter, sooner when the estimate says time is short. The neighbor is never told what's in the box. At 2:40 it's inside, an estimated 0.7 degrees, so likely still usable." |
| 0:34–0:54 | **[OWN]** The aide holds the Caregiver Pass 30–50 cm from the camera phone → dashboard "Checked in 09:22 · signed code verified" (`Own footage: phone camera standing in for the doorbell; button press simulated`). Fallback: the Pass page on a phone plus the dashboard check-in row with its `Simulated` badge | VO: "The same doorbell checks the care that was expected against what it actually saw. The aide shows a rotating, signed code: a verifiable check-in signal that a device showing this visit's current code was at the door. No face recognition." |
| 0:54–1:08 | Late and short visit findings; agency alerted; EVV CSV export open (`Dashboard`) | VO: "Maria arrived 22 minutes late and stayed 43 of 120 minutes. The agency gets a backup request and an EVV record with the six fields the Cures Act requires, plus how the visit was verified." |
| 1:08–1:28 | **Live take, one unbroken shot** (desk: laptop + phone + clock in frame): click **Package** in the Ring Developer Playground console → the DoorLedger dashboard reacts (Ring event, Nova label with measured latency) → the phone next to the laptop rings (`Ring Developer Playground` + `Real call · Amazon Connect`). **If live mode is not ready, cut this row** and give the time to 0:20–0:34 and 1:28–1:38 | VO (only over the live take): "This is live. When Ring records an event, DoorLedger reads it from Ring's history API, looks at that moment, and Rosa's phone rings." |
| 1:28–1:38 | Architecture diagram, 10 s: Ring history + snapshot + short WHEP live view → privacy-zone mask → face pixelation → Nova vision → deterministic reconcile → guardrailed ladder → Connect / SNS (`Diagram`) | VO: "Privacy zones are blacked out and faces pixelated before any frame reaches the cloud. Code decides what happened and who may be contacted. Rosa's words are fixed templates, never an LLM." |
| 1:38–1:56 | Ask box: "Is mom's insulin OK?" → visible "⏱ 7 s" jump cut → grounded answer with times and "estimated", response showing `runtime: agentcore` (`Dashboard`) | VO: "Families can just ask. A Strands agent on Amazon Bedrock AgentCore answers from a read-only copy of the ledger, and says 'I don't know' when the data isn't there." |
| 1:56–2:08 | AWS console, cropped (no account ID, ARNs or phone numbers): the Amazon Connect flow "DoorLedger patient alert (es)", then the AgentCore runtime page (`AWS console`) | VO: "On AWS: Bedrock with Nova and Claude Haiku, AgentCore, Strands, DynamoDB, SNS, and Amazon Connect for the call." |
| 2:08–2:16 | Clean terminal: `pip install ringpartner`, then one short snippet listing devices and history from the Playground (`Terminal`) | VO: "Ring has no official partner SDK, so we built one and published it: ringpartner, on PyPI." |
| 2:16–2:28 | Evidence frame with faces pixelated + "model-reported confidence" + retention note (`Dashboard`) | VO: "No biometric data is stored. Only the frames that back an event are kept, for thirty days." |
| 2:28–2:40 | End card (below) | VO: "DoorLedger. Care, verified at the door." |

**Cut from earlier drafts:** the terminal webhook simulation, the statistics title card (now the
0:04 lower-third), the GitHub README scroll, the 6-digit fallback, the pharmacy PDF, Telegram,
and the Playground Vehicle and Motion scenes.

## Burned-in subtitles: Rosa's call (Spanish → English)

Spanish is verbatim from `core/src/doorledger/wording.py` (`patient_call("porch_patient", …,
cold=True, "es")`, the text spoken by Amazon Connect); `core/tests/test_wording.py` fails if this
table drifts from the code. One subtitle per pause in the SSML. The 0:07–0:16 beat shows lines
1–3; use the whole table for the YouTube captions.

| # | Spanish (audio) | English subtitle |
|---|---|---|
| 1 | Hola, señora Rosa. Le llamamos de parte de su hija Ana. | Hello, Mrs. Rosa. We're calling on behalf of your daughter Ana. |
| 2 | Su insulina está afuera, en la puerta. Hace mucho frío. | Your insulin is outside, at the door. It's very cold. |
| 3 | Por favor, métala a la casa y póngala en el refri. | Please bring it into the house and put it in the fridge. |
| 4 | Si hay hielo en el escalón, no salga sola. Le vamos a avisar a Luis para que le ayude. | If there's ice on the step, don't go out alone. We'll let Luis know so he can help you. |
| 5 | No tiene que contestar. | You don't need to answer. |
| 6 | Repito: su insulina está en la puerta. Por favor, métala a la casa y póngala en el refri. | Again: your insulin is at the door. Please bring it into the house and put it in the fridge. |
| 7 | Gracias, señora Rosa. | Thank you, Mrs. Rosa. |

**The SMS (on screen at 0:07–0:16), exactly as SNS delivers it:**

> [Demo · para Rosa] Señora Rosa, de parte de su hija Ana: su insulina está en la puerta. Hace mucho frío. Métala a la casa y póngala en el refri. Si hay hielo en el escalón, no salga sola: le avisamos a Luis. No tiene que contestar.

English subtitle: *"[Demo · for Rosa] Mrs. Rosa, from your daughter Ana: your insulin is at the
door. It's very cold. Bring it inside and put it in the fridge. If there's ice on the step,
don't go out alone: we're letting Luis know. You don't need to answer."*

## End card

- **DoorLedger** · github.com/HaDeZIB/doorledger · `pip install ringpartner`
- "Built with Claude Code (Anthropic)." (Do **not** add "via Amazon Bedrock": the code was not
  written through Bedrock. At runtime the app calls Claude Haiku 4.5 and Amazon Nova on Bedrock;
  the AWS shots already show that.)
- **Credit line:** Ring Developer Playground package clip: *"Thief stealing our package"* by
  YouTube user **frollard**, licensed CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/),
  clipped, as credited by Ring; frames re-encoded by DoorLedger.
- "Own footage: phone camera standing in for the doorbell; button press simulated. Calls and
  texts went only to the founder's own verified test phone. Fictional household and agency.
  Temperatures are model estimates."
- "Not affiliated with or endorsed by Ring LLC or Amazon."

Put the same credit line in the YouTube description.

## Wording guardrails (keep these exact)

- Say "**verifiable check-in signal**" or "a device showing the visit's current signed code was
  at the door". Never say "cryptographic proof" or "proves she was there".
- Say "**estimated** 0.7 degrees", "likely still usable" and "confirm with the pharmacist".
  Never say "safe" on its own.
- Real Ring footage is the 14:07 package scene (and the live take). The aide and pickup scenes
  are own footage, labelled as above, or `Simulated`.
- Never say the aide "presses the doorbell" over own footage: there is no Ring device in it.
- "Sent" means a gateway accepted the message. Say "Answered" for the call only when the
  dashboard shows it (from Amazon Connect `DescribeContact`).
- Show "confidence" only as **model-reported**, never as a probability.
- Don't show the Playground's Vehicle or Motion scenes (no license; spring scenery).
- AgentCore is deployed, so naming it is accurate. Record the trace shot from a call that
  actually returned `"runtime": "agentcore"`. Crop the account ID and ARNs.

## Capture checklist

- **Call and SMS take:** trigger it with `scripts/place_patient_alert.py` (DoorLedger's own
  `Responder` and notifiers; one contact, no re-call, no texts to Luis or Ana). Run `--dry-run`
  first. Shoot between 2:05 and 2:15 pm so the status bar reads "2:07 PM". See
  [SHOT_LIST.md](SHOT_LIST.md). Film the phone and record room audio: iOS screen recording does
  not capture call audio.
- **Dashboard** at 1920×1080: `porch_early_pickup` for 0:16–0:20, `porch_cold` and `full_day`
  at 60× for the rest. Live backend, or `make api-offline` (real Ring frames, recorded Bedrock
  labels; say "recorded Bedrock label" on screen in that case).
- **Own footage** ([SHOT_LIST.md](SHOT_LIST.md)): aide check-in and check-out with the Pass,
  and the package pickup.
- **Voice-over:** Brandon's own voice, recorded last, after picture lock.
