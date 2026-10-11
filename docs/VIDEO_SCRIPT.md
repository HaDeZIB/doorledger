# DoorLedger: demo video script (target 2:45, English)

**Hackathon rules:**
- Under 3 minutes, public on YouTube or Vimeo, in English.
- No copyrighted music. Best material first.

**Our rules:**
- **Persistent corner label on every shot:** `Ring Playground` / `Own footage` / `Simulated` /
  `Dashboard`.
- Every temperature on screen and in the voice-over is an **estimate**.
- Shots marked **[OWN]** need footage we film ourselves ([SHOT_LIST.md](SHOT_LIST.md)). If it is
  not recorded, use the fallback in the same row and keep the `Simulated` label.

| Time | Picture (label) | Narration (voice-over) |
|---|---|---|
| 0:00–0:10 | **Real Ring frame first:** the snowy doorstep with the parcel, from the Ring Developer Playground live view, with the `Partner: RingDeveloperPortalPlayground` watermark visible. Caption: "Ring Developer Playground · live view over WHEP · re-timed for the scenario". Overlay: "−9 °C · insulin · 14:07" (`Ring Playground`) | "This is a Ring doorbell's live view. Rosa is 81 and lives alone in Chicago. Her insulin was just left on the step, and it's nine below zero." |
| 0:10–0:22 | Bedrock label pops: "package_visible ✓ · Nova 2 Lite · 1.5 s". The exposure clock starts. **The phone buzzes** with Rosa's SMS in Spanish via Amazon SNS. Fallback: the message in the dashboard (`Dashboard`) | "DoorLedger saw it through her doorbell. Amazon Nova on Bedrock labelled the frame, and Rosa got a text in Spanish to bring it inside before it freezes." |
| 0:22–0:38 | Timeline at a "60× time" badge: 14:27 at risk → Luis notified; 14:37 → Ana; 14:40 brought inside, "est. 0.7 °C in the box" (`Dashboard`; the 14:40 pickup step is `Simulated`) | "Twenty minutes later it's still outside. DoorLedger climbs the ladder the family set up, ten minutes apart: first the neighbor, then her daughter. At 2:40 it's inside, an estimated 0.7 degrees in the box, so likely still usable." |
| 0:38–0:52 | Title card: "Care is delivered through the front door. DoorLedger makes sure it arrived." Two sourced facts with on-screen citations: "NY State Comptroller audit 2022-S-31 (2024): US$14.5B in personal care claims with no matching EVV record. Measures missing verification, not proven fraud." / "Simulated mail-order shipments: 68% of the time outside the labeled range (JAPhA 2023)." | "Aides, nurses, medication, meals: care for older adults arrives at the front door. In New York, an audit found fourteen and a half billion dollars of home-care claims with no matching visit-verification record." |
| 0:52–1:15 | **[OWN]** Aide presses the doorbell, then holds the Caregiver Pass 30–50 cm from the camera → "Checked in 09:22 · signed code verified" (`Own footage`). Fallback: the Pass page on a phone, plus the dashboard check-in row with its `Simulated` badge | "So DoorLedger compares the care that was expected with what the doorbell actually saw. The aide presses the doorbell and shows a rotating, signed code. That's a verifiable check-in signal: a device showing this visit's current code was at the door. No face recognition." |
| 1:15–1:30 | Late and short visit findings; agency notified; EVV CSV export open (`Dashboard`; check-in and check-out `Simulated` unless [OWN] is recorded) | "Maria arrived 22 minutes late and stayed 43 of 120 minutes. The agency gets a backup request, and an EVV record with the six fields the Cures Act requires, plus how the visit was verified." |
| 1:30–1:52 | Architecture diagram animating: Ring history and snapshot → short WHEP live view → privacy-zone mask → face pixelation → Bedrock vision → tracker → deterministic reconcile → guardrailed messages (`Diagram`) | "Under the hood, our server only looks while care is expected or when Ring records an event. Privacy zones are blacked out and faces are pixelated before any frame reaches the cloud. A deterministic engine decides what happened. Claude Haiku on Amazon Bedrock only writes the messages, inside hard guardrails." |
| 1:52–2:08 | Ask box: "Is mom's insulin OK?" → grounded answer with times and "estimated", response showing `runtime: agentcore` (`Dashboard`). Then 3 s of the AgentCore trace or CloudWatch log for that call (`AWS console`) | "Families can just ask. A Strands agent running on Amazon Bedrock AgentCore answers from a read-only copy of the ledger, says temperatures are estimates, and says 'I don't know' when the data isn't there." |
| 2:08–2:22 | Terminal: `ringpartner simulate button_press …` → API log "watch session (webhook:button_press…)" → evidence frame with faces pixelated → exposure report PDF (`Simulated webhook` / `Dashboard`) | "Ring webhooks and doorbell presses start a short watch session. Only the frames that back an event are kept, and the family gets a one-page exposure report for the pharmacy." |
| 2:22–2:37 | GitHub: `ringpartner` README, `examples/`, tests passing, FRICTION_LOG summary table (`Screen`) | "Ring has no official partner SDK, so we built and open-sourced one: typed REST, server-side WHEP, webhook verification and a signed webhook simulator." |
| 2:37–2:45 | End card: DoorLedger · GitHub link · "Built with Claude Code (Claude via Amazon Bedrock)" · **credit line** (below) | "DoorLedger. Care, verified at the door." |

## Credits (end card and video description)

- **Ring Developer Playground package clip:** *"Thief stealing our package"* by **TODO: creator
  name and link, copied from the Playground credit**, licensed CC BY 4.0
  (https://creativecommons.org/licenses/by/4.0/). Clipped and re-timed. Shown through the Ring
  Developer Playground live view.
- Fictional household and agency. Temperatures are model estimates. Scenes marked "Simulated"
  are scripted events with no video.
- Not affiliated with or endorsed by Ring LLC or Amazon.

## Wording guardrails (keep these exact)

- Say "**verifiable check-in signal**" or "a device showing the visit's current signed code was
  at the door". Never say "cryptographic proof" or "proves she was there".
- Say "**estimated** 0.7 degrees", "likely still usable" and "confirm with the pharmacist".
  Never say "safe" on its own.
- Real Ring footage is the 14:07 package scene only. The aide and pickup scenes are own footage
  or `Simulated`.
- Don't show the Playground's Vehicle or Motion scenes (no license; spring scenery).
- AgentCore is deployed, so naming it is accurate. Record the trace shot from a call that
  actually returned `"runtime": "agentcore"`, not from a local fallback. Crop out the account ID
  and ARNs.

## Capture checklist

- Dashboard at 1920×1080. Live backend, or `make api-offline` (real Ring frames, recorded
  Bedrock labels). Scenario `full_day` at 60×.
- Phone screen recording of the SNS SMS (Rosa in Spanish; Luis and Ana in English). Fallback:
  Telegram or the dashboard.
- Own footage clips ([SHOT_LIST.md](SHOT_LIST.md)): aide check-in and check-out with the Pass,
  and the package pickup.
- Terminal: `ringpartner simulate button_press --device … --url http://localhost:8787/webhooks/ring --key "$RING_HMAC_KEY"` → API log.
- Voice: Brandon's voice or Amazon Polly (neural, en-US). Decide with Brandon.
