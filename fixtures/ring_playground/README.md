# Ring Developer Playground captures

Frames captured by DoorLedger from the **Ring Developer Playground** simulated live view
(WHEP, H.264 1280x720) on 2026-10-11, sampled at 1 frame/s:

- `package/` — Playground "Package" event. Source clip credited by Ring as *"Thief stealing our package"* (by YouTube user *frollard*, **CC BY 4.0**, clipped from original; see [NOTICE](../../NOTICE)).

The Playground's "Vehicle" and "Motion" (bird feeder) scenes carry no license statement, so they
are **not** in this repository. Capture them locally with your own Playground token:
`uv run python scripts/capture_live.py vehicle` writes to `fixtures/raw/vehicle/` (git-ignored).

The package frames are replayed through DoorLedger's perception pipeline (Bedrock vision + porch tracker)
so the demo runs on real Ring footage without a live token.
