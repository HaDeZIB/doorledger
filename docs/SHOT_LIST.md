# Shot list — own footage (aide check-in/out and "package picked up")

**Why:** the Ring Developer Playground has only 3 scenes (package, vehicle, birds). What it does not
cover (an aide showing her code, and someone picking up the package) we film ourselves. There is no
Ring device: a phone camera stands in for the doorbell, and nobody presses a real Ring button. In
the video and the README this footage is always labelled exactly:

> **Own footage: phone camera standing in for the doorbell; button press simulated**

We never pass it off as Ring video.

## Equipment
- **"Doorbell camera":** a phone recording video, **landscape**, **0.5x** lens (ultra-wide, close
  to the Ring's fisheye). Tape it to the door frame at ~1.2–1.4 m, pointing outward and slightly
  down. A laptop webcam on a chair works as a fallback.
- **"Aide's phone":** a second phone with the **Caregiver Pass** open. The pass link is issued by
  the API with the visit's secret (`GET /api/visits/V-MORNING/pass`, agency-only: send the
  `X-Admin-Token` header set to `DOORLEDGER_ADMIN_TOKEN`). For a phone on the same network, serve
  the API on the LAN (`uvicorn --host 0.0.0.0`).
- **A package:** a box, a pharmacy bag or a small cooler.
- **Actors:** one person as the "aide" and one as the "neighbor/patient".
- Daylight, no strong backlight.

## Before filming (2 min)
1. Open the pass link on the aide's phone; set brightness to 100%.
2. Check the **phone's clock** (automatic time); the code changes every 15 s.
3. Film **each scene in one long take** (longer is better than cut short).
4. Note the **exact time** each take starts (or say it aloud at the start).

## Takes
| # | Scene | What happens | Length | Key point |
|---|---|---|---|---|
| 1 | **Aide check-in** | Walks up to the door, stops, **mimes pressing a doorbell button** next to the camera phone (simulated: on a real Ring this press starts burst mode), **holds the phone with the pass on "Check-in" 30–50 cm from the camera**, keeps it **still for 3 s**, lowers it and "goes in" | 20 s | Screen facing the lens, no glare |
| 2 | **Check-out** | Comes out of the door, switches the pass to **"Check-out"**, mimes the button press again, shows it the same way (30–50 cm, 3 s) and walks away | 20 s | Same as take 1 |
| 3 | **Package on the porch** | Empty porch 3 s → someone leaves the package on the mat and leaves → porch with package 10 s | 25 s | Keep the whole package in frame |
| 4 | **Package picked up** | Porch with package 5 s → "Rosa" (or the neighbor) opens the door, picks it up and takes it inside → empty porch 5 s. This one carries "the doorbell is her reply" (the `porch_early_pickup` scenario, 2:15 PM) | 20 s | End on the empty porch |
| 5 | **(Optional) 6-digit backup** | Like take 1, but at ~80 cm (to show the large numeric code) | 15 s | |

## After filming
Copy the videos to `fixtures/raw/own/` with these names:

| Take | File name |
|---|---|
| 1 Check-in | `checkin.mov` |
| 2 Check-out | `checkout.mov` |
| 3 Package dropped off | `drop.mov` |
| 4 Package picked up | `pickup.mov` |

Then run `uv run python scripts/ingest_own_footage.py`. It extracts frames, reads the recording
time from the video, verifies the codes against the visit secret (`fixtures/own_footage/visit.json`),
and the demo scenario then uses them automatically instead of the "Simulated" steps.

## The phone call and SMS take (Rosa's phone ringing)

The call and the SMS must come from **DoorLedger's own code path**, not a hand-run AWS command.
`scripts/place_patient_alert.py` builds Rosa's minute-0 alert from the fixed templates
(`core/src/doorledger/wording.py`) and sends it through the engine's `Responder` with the same
notifiers (`ConnectVoiceNotifier` for the Amazon Connect call, `SNSNotifier` for the SMS). It sends
**one** contact only: no +5 min re-call and no texts to Luis or Ana during the take.

```bash
uv run --package doorledger python scripts/place_patient_alert.py --dry-run   # exact SSML + SMS, sends nothing
uv run --package doorledger python scripts/place_patient_alert.py             # call + SMS together (3 s countdown)
uv run --package doorledger python scripts/place_patient_alert.py --call      # call only;  --sms for SMS only
```

It reads `.env`, refuses to run unless `DOORLEDGER_VOICE_TO` / `DOORLEDGER_SMS_TO` (and the
Connect settings) are set, prints the Amazon Connect contact id, then polls for about 60 s and
prints `answered` or `no_answer`. Phone numbers are masked (last 2 digits). Do **not** use
`make api` with a porch scenario for this take: that runs the whole ladder and also places the
+5 re-call and texts "Luis" and "Ana" (all on the same test phone).

- Shoot between 2:05 and 2:15 pm local so the status bar matches "2:07 PM".
- Phone on a table, ringer on, speaker on after answering; record room audio (iOS screen recording
  does not capture call audio). Never show the phone number on screen.
- The English subtitles for the call are in [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md).
