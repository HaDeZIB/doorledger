# Review 02: independent judging panel (11 Oct 2026, evening)

**Scope.** HEAD `b63ba7f`. Tests: **239 passed, 2 skipped**. I ran the API (Bedrock vision) and the dashboard through `full_day`. Nova re-detected the Ring package at 14:07 (95%). One CareAgent question: Claude Haiku 4.5 answered, grounded, in 4.2 s. A bad signature and a token-less Pass request both got 401.

## 1. Scores (1–10)

| Criterion | Ring Eng | Appstore/PM | AWS | OSS |
|---|---|---|---|---|
| Tech implementation | 7.5 | 7 | 6.5 | 8 |
| Design | 6 | 6 | 7.5 | 6 |
| Potential impact | 6.5 | 6 | 6 | 7 |
| Quality of idea | 7.5 | 8 | 7 | 7 |

**Combined (Ring track):** 6.8 from the personas, ×1.05 for the friction log, gives **≈7.2 (+0.3 vs. 6.9)**. With the top 5 below, ≈8.3. The engineering underneath improved: privacy, tests, the poller, admin-only passes and DynamoDB. But nothing judge-visible has shipped (repo, video, hosted demo, real SMS). The README now contradicts the code in both directions.
**Odds:** Ring 1st ≈30%. Open Source ≈40% once spun out. AWS Builder ≈25% now, ≈40% if AgentCore deploys.

## 2. Review-01 top 10: verified in code

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Public repo + README | Partial | README done. No remote, no GIF, no file:line links |
| 2 | History poller + snapshots | Partial | `live.py:120-154`. No `event_types`, first page only. The snapshot goes to `last_snapshot` (`:145`) and is **never read, classified or shown**. `ring_events` is write-only. Untested |
| 3 | Ring-then-show burst | Partial | Burst works (`live.py:59-79`). The Pass copy never says "press the doorbell" (`caregiver-pass/index.html:117`). 15 s poll + 20 s WHEP gap means live view opens 15–35 s after a ding |
| 4 | Privacy matches the claim | Done in code | Redact before Bedrock, persist only on observation (`watcher.py:129-140,204-213`), retention (`api.py:91-97`). README `:321,:325` and `privacy.py:6-7` still describe the old behaviour. No real-face test; fails open when YuNet misses |
| 5 | AgentCore deployed | Partial | Packaged, synth OK, client wired (`api.py:300-339`). IAM blocks deploy. DynamoDB live. "Claude Code on Bedrock" not documented |
| 6 | Cut spring vehicle | Partial | Out of the backend (`scenarios.py:94`). Still in README `:153`, the mock `script.ts:128` (gitignored jpg, so it 404s) and NOTICE |
| 7 | Real notifications | Partial | `SNSNotifier` ready (`notify.py:64-96`). Rosa gets an "App alert" though the UI says "no app for Rosa" |
| 8 | Spin out `ringpartner` | Not done | Still in the monorepo. No `examples/` |
| 9 | Core unit tests | Done | +132 tests, 4 real bugs fixed. No API-level or poller tests |
| 10 | Friction log + AWS entries | Not done | Unchanged. F1 still "_(in progress)_" (`FRICTION_LOG.md:13`) |

Review-01 red flags:
- **Pass endpoint:** fixed.
- **Still open:** `/api/ask` has no auth, and there is no rate limiting.
- **Still in the script and README:** "cryptographic proof" (`VIDEO_SCRIPT.md:13`), "proves… at the door" (`README.md:102`), "0.7 degrees… safe" (`VIDEO_SCRIPT.md:12`).
- **Still pending:** the CC BY credit says "a YouTube user".
- **`live.py` nits, all unfixed:** unbounded `seen_requests` (`:42`), unretained `create_task` (`:99`), ignored webhook `device_id` (`:72`), `button_press` forced to the package scene (`:97`).

## 3. New weaknesses

1. **The offline demo shows zero Ring footage.** With perception off, the 14:07 drop falls back to `SIMULATED` with no evidence (`scenarios.py:186-196`). README `:235` claims the opposite. Mock mode has no `public/` folder, so no real frame appears there either. The judge's first click shows a fully simulated product.
2. **Privacy zones are ignored.** The Ring UX guide says not to display, analyse or store video from privacy zones. `configurations.privacy_zones` is never read, and there is no E2EE gating in the app. This would block certification.
3. **The ladder-gap guardrail is false on the rules path.** `Responder.allowed` ignores `now` (`responder.py:173-176`), and `PACKAGE_AT_RISK` climbs a rung immediately (`:220-224`).
4. **A false message goes to the patient.** The Spanish "compromised" text says "ya pedimos a la farmacia que la reponga" (`responder.py:103`), but the claim is only a draft.
5. **`delivered` is always true.** `ConsoleNotifier` sits inside the fan-out (`notify.py:106,114`), so a failed SMS still shows ✓.
6. **Dashboard bugs seen live:**
   - "Everything expected so far has arrived" while Maria was late.
   - "Nothing else is scheduled today" inside the insulin window (`StatusBanner.tsx:73-74`).
   - "All clear" after a visit cut short by 77 min.
   - A stale toast (19 vs. 30 min).
   - "Inside. It never froze." based on an estimate (`MedicationCard.tsx:341`).
   - Agency "Verified at the door: 1" counts a **simulated** check-in.
   - The header shows the internal states "Unknown · REPLAY" next to a green "Live" badge, which actually means the SSE stream is connected.
7. **No business model.** There is no price, payer or listing copy. The README's own vision cost of $20–40/patient/month (`:353`) exceeds any plausible consumer price.
8. **The hero feature is never seen through a Ring camera.** Presence codes are validated only synthetically and on iPhone footage (shot list).
9. **No Appstore UX shell.** There is no onboarding or account linking, no notification opt-down or daily cap, no data deletion and no offline-device state. All are explicit in the UX guide.
10. **Accessibility.** Tabs have no `role="tab"` or `aria-selected`, and view switches lag 1–2 s under SSE.
11. **Repo first impression.** `STATUS.md`, `CHECKPOINT.md` and `SHOT_LIST.md` are in Spanish ("Necesito de Brandon"). The demo data uses the real brand "CVS Specialty".
12. **The 6-digit fallback is not wired.** `verify_numeric_code` is never called. Yet the Pass page says "the backup code is read instead" (`index.html:119`) and README `:101` lists it as the fallback.

## 4. Top 10 new improvements (gain ÷ effort)

1. **Sync README and video script to the code (45 min).** Fix the privacy section. Mark Claude and DynamoDB as live. Drop the vehicle row. Say "verifiable check-in signal". Call the 6-digit fallback "designed". Use "estimated" for temperatures. Add one line: "built with Claude Code on Amazon Bedrock".
2. **A real Ring frame in every demo path, then host it (1.5 h).** When perception is off, inject the drop as `RING_LIVE` with `evidence/package.jpg`, labelled "pre-labelled replay". Copy the jpg into `web/dashboard/public/`. Delete the vehicle from `script.ts`. Deploy the mock to Vercel.
3. **Fix the banner, labels and Agency logic (1.5 h).** Lateness, open windows and short visits must override "all clear". Use "Estimated: did not freeze". Change the header to "Demo replay · Ring Playground". Count only camera-sourced events as verified. Add tab ARIA.
4. **Friction log (1 h, up to +10%).** Close F1 and add time lost and a date per entry. Add AWS entries: the Anthropic form gate, 5.5 "not available", `temperature:0` rejected, the AgentCore CDK bootstrap/IAM wall, and the starter-toolkit vs. Node CLI confusion.
5. **Engine truthfulness (1 h).** Enforce `LADDER_GAP` in `allowed()`. Fix the Spanish text. Set `delivered` per channel. Add a TTL plus timestamp-age check on webhooks, keep task refs, and use the webhook `device_id`.
6. **Privacy zones + E2EE gating (2 h).** Black out the `privacy_zones` polygons before the reader, vision and persistence. Refuse E2EE devices with plain-language copy. Test it with a synthetic face and a zone. This is the strongest certification signal for Ring Eng.
7. **Pricing and unit economics (1 h).**
   - Pricing: a Family plan sold as a Ring Appstore subscription, plus an agency EVV add-on per client per month.
   - Measure vision calls per patient per day after gating, multiply by $0.00037, and show the margin.
   - Back it with one quoted conversation with an agency or caregiver.
8. **Finish the poller (2–3 h).** Use `event_types` plus pagination. Classify the snapshot first and open WHEP only when it is positive. Show "Ring recorded a ding at 14:06" with the snapshot in the timeline, and test it with the replay transport. A Playground button press then becomes visible in the demo.
9. **Appstore shell screens (3 h).** Onboarding and "Link your Ring account", notification settings (critical vs. daily digest), "Delete my data", and an offline-device state. Use the term "Ring app".
10. **Repo hygiene (30 min).** Move the internal Spanish logs out. Put a GIF and badges at the top of the README. Rename "CVS Specialty". Publish an **orphan history**: the real account ID is in `ec93358`, `b85adee` and `dc2eb7c`, and the author email leaks your hostname.

## 5. Red flags

- **Claims vs. reality:** §3 items 1, 3, 4, 6, 12, plus the stale README lines above.
- **Audit citation:** the NY audit is now cited as "2025, sga-2025-22s31", while review-01 had 2022-S-31 (Nov 2024). Confirm which is right and keep the caveat.
- **Licensing:** the CC BY creator is still missing, and NOTICE lists gitignored vehicle files. The Apache-2.0 and YuNet MIT attributions are OK.
- **Tracked files:** clean. No keys, `111122223333` is the AWS example ID, and `.env` is untracked. Git history is not clean (see #10).
- **Open endpoints:** `/api/ask`, `/api/demo/run` and `/api/live/watch` are unauthenticated and spend Bedrock credit. Label them localhost-only or gate them.

## 6. If owner-dependent items never happen

- **No video:** disqualified (the only hard blocker).
- **No public repo:** no Open Source entry.
- **No own footage:** cut the caregiver act to 15 s and lead with the real Ring porch scene.
- **No AgentCore:** AWS Builder becomes close to "obvious".
- **No SNS:** film the phone buzz with Telegram instead.

## 7. Mini-challenge recommendation

Enter both, but **optimise for Open Source**. `ringpartner` fills a gap Ring admits to ("no official SDK"). Server-side Python WHEP plus a signed webhook simulator is a new integration pattern, and it already has 55 tests and CI. It needs only a spin-out repo, PyPI and `examples/`, about 3 h within your control. AWS Builder is the challenge every entrant has Bedrock for, so you win it only if AgentCore is deployed and shown with a trace. Revisit if IAM is granted by about 16 Oct.
