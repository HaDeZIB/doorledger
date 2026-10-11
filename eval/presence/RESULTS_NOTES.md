## Verdict

**At ~1 m, no: a phone-size QR is not reliably readable by a 150° 1080p doorbell.** With the
best format we found, per-frame decode at 1.0 m is 60% in clean conditions and **0%** in the
`mixed` (realistic) condition; even an 8-frame burst only reaches 10%. The plan's success
criterion (≥95% at ~1 m) is **not met** with a phone. The cause is geometry, not the decoder:
a 6.3 cm QR at 1 m spans ~46 px, i.e. <2 px per module, and table E shows the decoder needs
≥2.5 px/module for clean frames and ≥4 px/module to stay above ~95% under blur, motion and
compression. On oracle crops (the decoder handed the exact phone region) the ceiling is the
same, so a better reader would not change this.

**At 30–50 cm, yes.** With the recommended code, per-frame decode is 100% in every condition at
0.3–0.5 m except motion blur, and an 8-frame burst is 100% / 100% / 90% (mixed / low light /
motion) at 0.5 m. 0.6 m is the edge (85% per frame mixed, 100% burst); 0.75 m is unreliable.

## Recommendation

1. **Instruct the aide: "Hold your phone 30–50 cm from the doorbell, screen facing the lens,
   hold still 2–3 s."** (That is what the Caregiver Pass now says.) Holding something up close
   to a doorbell is a natural gesture; design the check-in UX around it rather than around 1 m.
2. **Use the compact door-scoped numeric payload (`make_compact_code`, 25 digits → QR version
   1) with EC level M, a 2-module quiet zone, filling the full screen width.** This was the
   single biggest lever: versus the original `DL1.<visit>.<step>.<mac>` text form (version 2,
   4-module quiet zone) it moves the 85%+ mixed-condition range from ~0.4 m to ~0.6 m (table C).
   The text form stays supported for logs / APIs. EC level barely matters (L≈M≈Q; H is worse
   because it pushes to version 2); M is the robustness/size sweet spot.
3. **Decode over a burst, not a single frame**: run `PresenceReader` on every 2nd–3rd frame of
   the live stream for the ~3 s hold and accept the first MAC-verified hit. Motion blur is the
   main per-frame failure; bursts recover most of it.
4. **Keep the 6-digit fallback.** It is not evaluated here (it will be read by a vision model
   later), but it is the only channel with a chance beyond ~0.6 m: digits stay visibly legible
   in the contact sheet out to ~0.75–1.0 m where the QR has turned to mush. It also covers the
   1536² devices, which lose ~20% px/rad and are noticeably worse at 0.5–0.6 m (table B).
   Because it is door-scoped and only 6 digits, the backend must rate-limit attempts per door.
5. **If 1 m+ is a hard product requirement**, the QR must be physically larger: ~12 cm at 1 m
   and ~20 cm at 1.5 m for ≥95% in mixed conditions (table D) — a tablet or a printed badge,
   which defeats the rotating code unless the badge carries an e-ink display.
6. **Next step (blocking before relying on this):** capture real frames from the target Ring
   doorbell(s) via the Partner API at 0.3 / 0.5 / 0.75 / 1.0 m, day / night / backlit, and
   rerun the reader. Things this simulation cannot capture: Ring's real lens projection and
   sharpening, H.264 artefacts (blockier than JPEG at the same bitrate), auto-exposure
   behaviour with a bright screen in a dark scene, the API's snapshot watermark overlapping the
   code, IR night mode (phone screens are nearly invisible under IR illumination), and
   screen-refresh banding / moiré.
