"""Turn our own filmed clips into replayable fixtures (labelled "own footage").

For each video in fixtures/raw/own/:
  * read the recording start time from the container metadata (iPhone .MOV `creation_time`),
    or take it from the CLI (`--start 2026-10-12T15:04:05-05:00`) if the metadata is missing;
  * extract frames at 4 fps into fixtures/own_footage/<clip>/frames/;
  * run the presence reader on every frame and verify codes against the demo visit secret at
    the frame's wall-clock time, reporting which frames carry a valid check-in / check-out;
  * write fixtures/own_footage/<clip>/clip.json with `recorded_start` (epoch) so the watcher
    can verify the time-based codes again when the clip is replayed inside the simulated day.

usage: uv run python scripts/ingest_own_footage.py [--start ISO] [clip ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import av
import cv2

from doorledger import presence
from doorledger.presence_reader import PresenceReader

RAW = Path("fixtures/raw/own")
OUT = Path("fixtures/own_footage")
FPS = 4.0


def recording_start(path: Path, override: str | None) -> float:
    if override:
        return datetime.fromisoformat(override).timestamp()
    with av.open(str(path)) as c:
        for key in ("com.apple.quicktime.creationdate", "creation_time"):
            value = c.metadata.get(key)
            if value:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    sys.exit(f"{path.name}: no creation time in metadata; pass --start")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--start")
    args = ap.parse_args()
    visit = json.loads((OUT / "visit.json").read_text())
    secrets = {visit["visit_id"]: presence.secret_from_b64url(visit["secret_b64url"])}
    reader = PresenceReader()
    files = [RAW / c for c in args.clips] if args.clips else sorted(
        p for p in RAW.iterdir() if p.suffix.lower() in (".mov", ".mp4", ".m4v"))
    for path in files:
        start = recording_start(path, args.start)
        clip = path.stem.lower().replace(" ", "_")
        frames_dir = OUT / clip / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        hits: list[dict] = []
        used: set = set()
        n = 0
        with av.open(str(path)) as c:
            stream = c.streams.video[0]
            next_t = 0.0
            for frame in c.decode(stream):
                t = float(frame.pts * stream.time_base) if frame.pts is not None else n / FPS
                if t + 1e-6 < next_t:
                    continue
                next_t += 1 / FPS
                img = frame.to_ndarray(format="bgr24")
                if img.shape[1] > 1920:
                    img = cv2.resize(img, (1920, int(img.shape[0] * 1920 / img.shape[1])))
                cv2.imwrite(str(frames_dir / f"{n:04d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                for text in reader.read(img).texts:
                    for role in ("in", "out"):
                        verify = presence.verify_code if text.startswith("DL1.") else presence.verify_compact_code
                        res = verify(text, secrets, role, at=start + t, used=used)
                        if res.valid:
                            hits.append({"frame": n, "t": round(t, 2), "role": role})
                n += 1
        meta = {"clip": clip, "source_file": path.name, "recorded_start": start, "fps": FPS,
                "frames": n, "valid_codes": hits}
        (OUT / clip / "clip.json").write_text(json.dumps(meta, indent=2))
        roles = sorted({h["role"] for h in hits})
        print(f"{clip}: {n} frames, valid codes: {len(hits)} {roles or ''}")


if __name__ == "__main__":
    main()
