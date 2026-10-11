"""Capture a Ring live view (WHEP) to JPEG frames + an MP4, for fixtures and the demo.

usage: uv run python scripts/capture_live.py NAME [seconds] [fps]
"""
import asyncio, os, sys, time
from pathlib import Path
import cv2
from ringpartner import AsyncRingClient
from ringpartner.whep import WhepSession

async def main(name: str, seconds: float, fps: float) -> None:
    token = os.environ["RING_ACCESS_TOKEN"]
    out = Path("fixtures/raw") / name
    (out / "frames").mkdir(parents=True, exist_ok=True)
    async with AsyncRingClient(token) as ring:
        dev = (await ring.devices())[0]
        async with WhepSession(ring, dev.id, max_seconds=seconds) as live:
            print("session", live.answer.video_codec, flush=True)
            writer = None; n = 0; t0 = time.time()
            async for frame in live.frames(fps=fps):
                img = frame.to_ndarray(format="bgr24")
                if writer is None:
                    h, w = img.shape[:2]
                    writer = cv2.VideoWriter(str(out / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                    print("size", w, h, flush=True)
                writer.write(img)
                cv2.imwrite(str(out / "frames" / f"{n:04d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                n += 1
            if writer: writer.release()
            print(f"frames={n} in {time.time()-t0:.1f}s", flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 25, float(sys.argv[3]) if len(sys.argv) > 3 else 5))
