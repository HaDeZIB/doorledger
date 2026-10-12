# Shot list — own footage (aide check-in/out and "package picked up")

**Why:** the Ring Developer Playground has only 3 scenes (package, vehicle, birds). What it does not
cover (an aide showing her code, and someone picking up the package) we film ourselves. In the video
and the README this footage is labelled **"Own footage"**; we never pass it off as Ring video.

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
| 1 | **Aide check-in** | Walks up to the door, stops, **presses the doorbell** (this starts burst mode), **holds the phone with the pass on "Check-in" 30–50 cm from the camera**, keeps it **still for 3 s**, lowers it and "goes in" | 20 s | Screen facing the lens, no glare |
| 2 | **Check-out** | Comes out of the door, switches the pass to **"Check-out"**, presses the doorbell, shows it the same way (30–50 cm, 3 s) and walks away | 20 s | Same as take 1 |
| 3 | **Package on the porch** | Empty porch 3 s → someone leaves the package on the mat and leaves → porch with package 10 s | 25 s | Keep the whole package in frame |
| 4 | **Package picked up** | Porch with package 5 s → the "neighbor" arrives, picks it up and takes it away → empty porch 5 s | 20 s | End on the empty porch |
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
