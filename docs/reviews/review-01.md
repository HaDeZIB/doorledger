# Review 01: independent judging panel (11 Oct 2026, 13 days before the deadline)

Scope: the repo as it stood at commit `931c1ec` plus uncommitted work (AgentCore/DynamoDB still being written). I ran `uv run pytest -q` (106 passed, 2 skipped) and called the API in-process: a bad signature got 401, a valid one got `watching`, and a replay got `duplicate`.

## 1. Scores (1–10)

| Criterion | Roman (Ring Eng) | Clausen / Komaragiri (Appstore/PM) | Melissinos / Hurst (AWS) | OSS judge |
|---|---|---|---|---|
| Tech implementation | 7 | 6.5 | 6 | 7.5 |
| Design | 6 | 5.5 | 7 | 5.5 |
| Potential impact | 6 | 6 | 6 | 7 |
| Quality of idea | 7.5 | 8 | 7 | 7 |

**Ring track, combined estimate:** 6.6/10 for the Ring personas, plus about 5% for the friction log, so **≈6.9**. If you do the top 5 below, ≈8.2.
**Odds (honest):** Ring 1st place is about 25% as things stand. The track looks thin (zero Ring questions on Discord), but Care Handoff is already shipped with a hosted trial and a video. If you do the top 5, it rises to about 45%. AWS Builder is about 20% now (Bedrock plus Strands, with AgentCore not deployed). Open Source is about 30% now and about 45% if `ringpartner` gets its own repo and a PyPI release. You can win only one mini prize, so make the AWS integration the one that is visibly real.

**Why it would lose today:** it is not submittable. There is no root README and no GitHub remote (`HaDeZIB/doorledger` does not resolve). There is also no video, no hosted demo and no real phone notification.

## 2. Top 10 improvements (by gain ÷ effort)

1. **Make the repo public and add a root README.** (All criteria; OSS is a hard gate.) Push to GitHub. The README needs a 3-line pitch and a GIF of the dashboard. Add a "Ring APIs called at runtime" table with file:line links (`live.py` WHEP, `api.py:/webhooks/ring`). Add the mermaid diagram from `docs/architecture.md`, a one-command demo (`make demo` with `DOORLEDGER_PERCEPTION=off DOORLEDGER_WRITER=template`) and a footage-provenance table. Put the CC BY credit there too. Effort: 2 h.
2. **Add a Ring history poller and event-time snapshots.** This replaces "open live view all window long". (Tech, Idea; Roman's top concern.) The product only calls `devices()` and WHEP at runtime today. `history`, `snapshot`, `capabilities` and `location` exist in the SDK but the app never uses them. Poll `history(event_types=...)` every 15–30 s. For each new row, call `snapshot(at=event.start)` (your S1 spike showed it works). Classify it with Nova and open WHEP only to confirm or for presence codes. Pressing the Playground's Package button then creates a **real Ring-generated event** and the whole pipeline runs, with no simulated webhook needed. It is battery-friendly, cheaper, and idiomatic Ring. Effort: 4–6 h.
3. **Make "ring the bell, then show your pass" the check-in flow.** (Design, Tech.) Live sessions are 25 s with a 20 s gap, so the watcher is blind about 44% of the time during a care window. It also checks a QR on every 2nd frame at 1 fps, so a 2–3 s hold gets about one decode attempt, while your own S4 eval recommends an 8-frame burst. Instead, have `button_press` (ding) open WHEP immediately, sample at full rate for 10 s and decode every frame. Change the Pass copy to "Press the doorbell, then hold your phone 30–50 cm from it." Effort: 3 h.
4. **Fix privacy so it matches the claim.** (Tech and Impact for Roman; also a red flag.) `Watcher._save` writes **every sampled frame** to disk, keeps the original whenever YuNet finds no face, and has no retention limit. It also sends the **unredacted** frame to Bedrock (`watcher.py:128-135`, "return the original JPEG for vision"). Keep frames in an in-memory ring buffer and persist only frames attached to an emitted Observation. Pixelate faces *before* the Bedrock call; package and vehicle detection don't need faces. Add a TTL. Then you can honestly say "faces never leave the home unblurred; we keep only the frames that prove an event." Effort: 2–3 h.
5. **Actually deploy AgentCore, then show it.** (AWS Builder.) `deployed-state.json` currently says `"targets": {}`. Run `agentcore deploy`, have `/api/ask` call `InvokeAgentRuntime`, and keep the DynamoDB mirror on. Put a CloudWatch/AgentCore trace screenshot in `docs/aws_architecture.md` and in the video (5 s). Add a line that Claude Code on Bedrock was used for development (a judge said on the forum that this counts). Effort: 4–6 h.
6. **Pick one hero and cut the vehicle frame from the winter story.** (Design, Impact.) The pitch is two products: porch medication and EVV for aides. Lead with medication at the door and make caregiver check-in the second act. The `vehicle` Playground scene is a **green, spring parking lot**, which contradicts "−9 °C Chicago porch" if it appears at 14:05. Drop it, or label it "sample scene, different location". Effort: 1 h.
7. **Send real notifications through a channel an 81-year-old uses.** (Design.) Telegram is not configured, and Rosa wouldn't use it anyway. Send SMS via Amazon End User Messaging/SNS to your own verified number (sandbox), or place a **voice call with Amazon Polly** in Spanish. That adds a third AWS service and gives the video the "phone buzzes" moment. Effort: 2–4 h.
8. **Spin out `ringpartner` as its own repo and publish it.** (OSS.) The rules want a *new* OSS project in addition to the main one. Create `HaDeZIB/ringpartner`, release v0.1.0 on PyPI (`pip install ringpartner`) with CI and a badge, and make DoorLedger depend on it. Add an `examples/` folder: a 20-line Playground snapshot, a webhook FastAPI receiver, a WHEP-to-OpenCV script. Care Handoff already released `ring-view-bridge` separately, so you need parity here. Effort: 3 h.
9. **Add unit tests for the deterministic core.** (Tech, OSS credibility.) The docs say reconcile and exposure are "deterministic, unit-tested", but there are **no tests** for `reconcile.py`, `exposure.py`, `porch.py`, `responder.py`, `watcher.py` or `live.py`. Only the agent, presence and AWS modules have tests. Add a table-driven test for each rule (late, missed, short, exposure crossing 0 °C and 30 °C, k-of-n flicker, ladder gap). Add a webhook test (bad sig → 401, duplicate). Effort: 3 h.
10. **Strengthen the friction log with AWS entries and evidence.** (+10% bonus.) Add entries for the Anthropic use-case form gate, Haiku/Sonnet 5.5 "not available for this account", 5.5 models rejecting `temperature: 0`, the deprecated AgentCore starter toolkit vs the Node CLI, and the snapshot 403 window. Give each entry the time lost and a request ID or timestamp. Close F1's "(in progress)". Effort: 1 h.

Ideas you haven't listed:
- Use Ring `location` for lat/lon and timezone instead of the hard-coded household.
- At startup, read `capabilities` and `status` for battery vs wired and `e2e_encryption`, then refuse or degrade gracefully. That shows Ring certification awareness.
- Host the dashboard's mock mode as a static site so judges can click it, the way Care Handoff does.

## 3. Red flags

- **Not public, no README.** This is an automatic gate for OSS and hurts every criterion.
- **Overclaims.**
  - "Cryptographic proof they were at the door": it proves only that a device holding the visit secret was in view. A relative holding the aide's phone, or a live screen relay, passes. Say "verifiable check-in signal".
  - `GET /api/visits/{id}/pass` returns the secret with **no auth**, and `/api/ask` is unauthenticated (it spends Bedrock credit). Label this a single-tenant demo or add a token.
  - The 6-digit fallback has **no rate limiting**, though `presence.py:351` says it must.
  - "0.7 degrees in the box, safe" in the script is a model estimate. Say "estimated".
  - "10/10 real Ring frames" is a tiny sample. State n.
- **Stats need citations.** The $14.5B figure is real: NY State Comptroller audit 2022-S-31, Nov 2024. Attribute it on screen, and note that the state disputes about $2.7B of it. The "mail-order meds outside safe temps" claim needs a source or should be cut.
- **Footage labelling.**
  - The package clip carries an on-frame timestamp of 20:47 UTC, Oct 11, while the story says 14:07 in winter. Add the caption "Ring Developer Playground stream, re-timed for scenario".
  - The 14:40 pickup and the aide check-ins are `SIMULATED` until you film your own footage. The dashboard labels these honestly; the video must too.
  - Rules forbid YouTube clips. The package scene is Ring's Playground stream, so it is fine, but call it that, not "a YouTube clip".
- **Attribution.** CC BY 4.0 requires the creator's name (if given) and a source link. "A YouTube user" is insufficient. Get the handle or URL from the Playground credit. The vehicle and motion scenes carry no license, yet they are committed to the repo. Either remove them from the public repo or keep the NOTICE disclaimer and avoid redistributing more than you need.
- **Secrets/PII scan of tracked files.**
  - No API keys, tokens or private keys found. The `eyJ…` hit in `web/dashboard/package-lock.json` is an integrity hash.
  - `.env` was never committed.
  - The `users_me` fixture holds only `developer@example.com`.
  - Found: the **12-digit AWS account ID** in `eval/vision/RESULTS.md:3` and `eval/vision/run_eval.py:90`. Redact it.
  - Found: absolute local paths with your username in `.claude/launch.json`. Untrack this file.
  - `fixtures/own_footage/visit.json` holds a demo secret on purpose (documented). That is fine.
  - Personal names appear only in LICENSE, NOTICE and authors, which is expected.
- **Robustness nits Roman will spot** (all in `live.py`):
  - `seen_requests` is unbounded and lost on restart, and there is no check on timestamp age.
  - The `asyncio.create_task` result is not kept, so the task can be GC'd.
  - The webhook's `device_id` is ignored, so a multi-device account watches the wrong camera.
  - A `button_press` is hard-mapped to the "package" scene.

## 4. What the first 30 seconds must show

1. **0–8 s:** A real Ring frame with the `Partner: RingDeveloperPortalPlayground` watermark visible, captioned "Ring Developer Playground · live WHEP · Ring API". Overlay "Insulin delivered · 16 °F".
2. **8–18 s:** A Bedrock label pops ("package_visible ✓, Nova 2 Lite, 1.4 s"), the exposure clock starts, and a **real phone rings or buzzes** with Rosa's message in Spanish.
3. **18–30 s:** A time-lapse with a "60× time" badge runs up the ladder (neighbor, then daughter) and ends on "Brought inside 14:40 · est. 33 °F · safe". Then the one-line thesis: "Care arrives through the front door. DoorLedger checks that it did."
4. Do not use the spring vehicle frame. Keep a persistent corner label throughout: Ring Playground / Own footage / Simulated.

## 5. The competition

- **Care Handoff (blucca):** MIT license, 10 commits, Node.js. It is a coordination workflow: one owner per disrupted visit, then handoff, then completion receipt. It uses Ring REST, history, webhook HMAC and WHEP through its own separately released `ring-view-bridge`. It has **no AWS and no vision**, but it has a **hosted free trial**, a 2:21 video and disciplined claims (price "a hypothesis").
- **Where you beat it:** real perception on Ring frames, deterministic reconciliation, signed presence codes, EVV output, Bedrock and Strands.
- **Where it beats you:** shipped, clickable, focused, and honest-sounding.
- **The rest of the field** is likely package-theft alerts, "describe my doorbell with an LLM", and visitor greeters. All of those are "obvious".
- **How to stand out:**
  - Be the only entry that turns Ring events into **verified care outcomes**: "what was supposed to happen at the door vs. what did".
  - Show it running on real Ring-generated events via the history poller.
  - Make the privacy story true (redaction before the cloud, minimal retention).
  - Give judges a hosted mock to click.
  - Keep every number labelled as measured, estimated or simulated.
