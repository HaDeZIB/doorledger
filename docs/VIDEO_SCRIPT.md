# DoorLedger — demo video script (target 2:45, English)

Rules from the hackathon: < 3 min, public on YouTube/Vimeo, English, no copyrighted music,
best material first. Label footage: **Ring Playground** vs **Own footage** vs **Simulated**.
Credit the Ring Playground package clip (CC BY 4.0) in the description and an end card.

| Time | Picture | Narration (voice-over) |
|---|---|---|
| 0:00–0:12 | Snowy Ring doorstep frame (Ring Playground) with a parcel; overlay "-9 °C · insulin · 14:07" | "Rosa is 81 and lives alone in Chicago. Her insulin just arrived — and it's nine below zero on her porch." |
| 0:12–0:25 | Phone buzzes: Spanish message to Rosa; dashboard exposure clock starts | "DoorLedger saw it through her Ring doorbell, and texted her in Spanish to bring it inside before it freezes." |
| 0:25–0:40 | Timeline: 14:27 at risk → Luis notified; 14:37 → Ana; 14:40 inside | "Twenty minutes later it's still outside. DoorLedger climbs a ladder the family set up: the neighbor, then her daughter. At 2:40 it's inside — 0.7 degrees in the box, safe." |
| 0:40–0:55 | Title card: "Care is delivered through the front door. DoorLedger makes sure it arrived." + 3 facts | "Aides, nurses, medication, meals — care for older adults arrives at the front door. Medicaid paid $14.5 billion for New York home-care visits with no electronic verification record. Mail-order medication spends most of its trip outside safe temperatures." |
| 0:55–1:20 | Caregiver Pass on a phone → shown to the door camera (Own footage) → "Checked in 09:22 · verified" | "So DoorLedger compares the care that was expected with what the camera actually saw. Aides check in by showing a rotating, signed code to the doorbell — cryptographic proof they were at the door, with no face recognition." |
| 1:20–1:35 | Late + short visit findings; agency notified; EVV CSV export | "Maria arrived 22 minutes late and stayed 42 of 120 minutes. The agency gets a backup request and an EVV record with all six fields the Cures Act requires." |
| 1:35–1:55 | Architecture diagram animating: Ring WHEP → Bedrock vision → tracker → reconcile → guardrailed agent | "Under the hood: our server opens Ring live view over WHEP only when care is expected, Amazon Bedrock Nova reads the frames, and a deterministic engine decides what happened. Claude on Bedrock only writes the messages — inside hard guardrails." |
| 1:55–2:10 | Ask box: "Is mom's insulin OK?" → grounded answer | "Families can just ask. A Strands agent answers from the ledger — and says 'I don't know' when the data isn't there." |
| 2:10–2:25 | Signed webhook simulator → watch session; faces pixelated in evidence; PDF claim | "Ring webhooks trigger a watch session. Evidence frames are stored with faces pixelated, and a one-click exposure report goes to the pharmacy." |
| 2:25–2:40 | GitHub: `ringpartner` SDK, tests, friction log | "Ring has no official partner SDK, so we built and open-sourced one: typed REST, server-side WHEP, webhook verification and a signed webhook simulator." |
| 2:40–2:45 | End card: DoorLedger · github link · credits | "DoorLedger. Care, verified at the door." |

## Capture checklist
- Dashboard at 1920×1080, mock off, live backend, scenario `full_day` at 60×.
- Phone screen recording of Telegram messages (Rosa ES, Luis/Ana EN).
- Own footage clips (docs/SHOT_LIST.md).
- Terminal: `ringpartner simulate motion_detected --sub-type package_delivery ...` → API log.
- Voice: Brandon's voice or Amazon Polly (neural, en-US) — decide with Brandon.
