# Review 03: independent judging panel (11 Oct 2026, night)

**Scope.** HEAD `fd7fa70` plus 4 uncommitted doc edits.
- **Tests:** **243 passed, 2 skipped**; the README says 239. The SDK's 55 tests pass, and `webhook_receiver.py --self-test` passes 4/4.
- **Live `full_day` run** (Bedrock perception, template writer, AgentCore ARN): the Ring frame appeared at 14:07. The ladder went Rosa (ES) 14:07, Luis 14:27, Ana 14:37.
- **Ask:** `runtime: agentcore`, Claude Haiku 4.5, 2.3 s in the handler, 7.6 s round trip.

## 1. Scores (1–10)

| Criterion | Ring Eng | Appstore/PM | AWS | OSS |
|---|---|---|---|---|
| Tech implementation | 8 | 7.5 | 7.5 | 8 |
| Design | 6.5 | 6.5 | 7.5 | 6.5 |
| Potential impact | 6.5 | 6.5 | 6 | 7 |
| Quality of idea | 7.5 | 8 | 7 | 7 |

**Combined:** 7.1 across the personas, ×1.05 for the friction log, gives **≈7.5** (+0.3 vs. 7.2, +0.6 vs. 6.9).
- **Gains:** privacy zones and E2EE match the documented schema, AgentCore is really deployed, the banner and Agency view tell the truth, the friction log is in the official format, and there is a business model.
- **Cap:** nothing a judge can click exists yet (no repo, video or hosted demo). The hero feature, aide check-in, is a grey "No camera frame · footage not filmed yet" box on the main screen.

## 2. Review-02 top 10: verified in code

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Docs synced | Partial | Stale: test count (`README.md:22,322`); "not covered by tests" (`README.md:435`, `BUSINESS.md:136`); "re-detects live" (`README.md:49`, see §3.2) |
| 2 | Real frame everywhere, hosted | Partial | Cache and mock modes show the real frame (`script.ts:27`), and the vehicle clip is gone. Not hosted |
| 3 | Banner, Agency, ARIA | Done | `banner.ts` with 17 cases (not run in CI). Agency shows "0 verified · 1 simulated" (`AgencyView.tsx:31`). Tab ARIA (`Header.tsx:76-77`) |
| 4 | Friction log | Done | 17 entries with time lost. AWS entries A1–A6 |
| 5 | Engine truthfulness | Partial | Done: gap on the at-risk path (`responder.py:221`), Spanish text (`:103`), `delivered` (`notify.py:105-112`). Open: `allowed()` ignores `now` (`:174`); no webhook TTL; unretained task (`live.py:120`); `device_id` ignored; unbounded dedupe set (`:42`) |
| 6 | Privacy zones, E2EE | Done | `privacy.py:66-86`; masked before reader, vision and storage (`watcher.py:220`); 4 tests. E2EE fails open without configurations (`models.py:85`) |
| 7 | Pricing | Done, unvalidated | `BUSINESS.md`: $7.99 / $15, COGS ≈ $2.81. Zero customer calls |
| 8 | Poller | Partial | Snapshot is now classified (`live.py:165`). Still: first page only, no `event_types` (`:158`), `ring_events` write-only, untested |
| 9 | Appstore shell | Not done | None of the screens exist |
| 10 | Hygiene | Partial | CVS removed. STATUS, CHECKPOINT and SHOT_LIST are still in Spanish, and SHOT_LIST is linked from the judge table (`README.md:50`). No GIF. History not purged |

## 3. New weaknesses

1. **The agent over-claims on simulated data (seen live).**
   - Asked "Did Maria come today?", it said she checked in "**using a compact QR code**".
   - The tool output said `simulated event` (`agent.py:110`), and the model dropped it.
   - On screen, that answer sits next to the "Simulated · No camera frame" card.
2. **"Live" Bedrock isn't live.** In `bedrock` mode, `CachingVision` answers cache hits without calling Bedrock (`vision.py:137`). The committed frames always hit the cache, so no vision call happens. `README.md:49` and the 0:10 video shot ("Nova 2 Lite · 1.5 s") imply live inference.
3. **"Tamper-evident care ledger"** appears in the agent prompt (`agent.py:445`). The ledger has no hash chain, and `reset()` wipes it.
4. **Rosa gets an "App alert"** (`MedicationCard.tsx:26`) while the visit card says "no app for Rosa" (`VisitCard.tsx:185`). Unchanged since review-02.
5. **The Pass page never says "press the doorbell first"** (`caregiver-pass/index.html:117`). Burst mode depends on that press.
6. **Error and token handling.** `agentcore_error` returns the raw exception text, which can contain ARNs and the account ID (`api.py:333`). The admin token is compared with `!=` (`:272`).
7. **Smaller issues.**
   - The 7.6 s Ask round trip will look slow on camera.
   - `make api-offline` loads `.env`, so for the owner it turns on DynamoDB and AgentCore.
   - The dashboard polls `/api/state` about twice a second on top of SSE.
8. **Trademark.** `ringpartner` uses Ring's mark as a PyPI package name. Ask Ring, or keep a neutral name ready.

## 4. Top 8 new improvements (gain ÷ effort)

1. **Agent source honesty (20 min).** Simulated sources give `verified:false` and no `method`. Add a prompt rule and a regression test. Delete "tamper-evident" unless you do #7.
2. **Doc and NOTICE drift (30 min).** Fix the counts and test claims. NOTICE needs `web/dashboard/public/ring/package.jpg` and the real CC BY creator. Translate or untrack the Spanish logs.
3. **Make live vision live (20 min).** In `bedrock` mode, skip cache reads and only record. Show model and latency on the evidence card.
4. **Pass copy + AgentCore warm-up (20 min).** Add "Press the doorbell, then…". Ping the runtime when a scenario starts.
5. **Per-person channel truth (30 min).** Rosa gets SMS. Record the channel that actually delivered on each action.
6. **Hardening (45 min).**
   - Webhooks: reject timestamps older than 5 min, use an LRU for dedupe, keep task refs and honour `device_id`.
   - E2EE: fail closed when configurations are missing.
   - API: use `compare_digest` for the admin token and return a generic error instead of `agentcore_error`.
7. **Hash-chain the ledger (1 h).** Store `sha256(prev‖body)` per record. Add `/api/ledger/verify`, and put the chain head in the EVV CSV and the PDF. That is a real EVV differentiator.
8. **One Appstore settings screen (2–3 h).** Critical vs. digest alerts, a daily cap, "Delete my data", and the offline/E2EE device state.

## 5. Red flags

- **Claims vs. code:** §3.1–3.4 and the stale docs in §2 #1.
- **Licensing:** the CC BY creator is still "a YouTube user" (`NOTICE:33`), and CC BY requires the name. The public copy of the frame is missing from NOTICE. Confirm the license of the CLI-generated `.llm-context/*.ts`.
- **Tracked files:** clean. The only 12-digit ID is `111122223333` (the AWS example). No emails, tokens or ARNs.
- **Git history: purge before publishing.**
  - The real AWS account ID is in `ec93358`, `b85adee` and `dc2eb7c` (old `eval/vision/RESULTS.md`).
  - A hostname email is on `1cea3a7`.
  - The unlicensed Vehicle/Motion frames, `vehicle.jpg` and `ring_snapshot.jpg` are in history.
  - Home-directory paths are in `.claude/launch.json` (`6164747`).
  - **Use `git filter-repo`** (paths, `--replace-text`, mailmap), not an orphan squash. The 30 dated commits are your proof the work was done inside the hackathon window.
  - Commit the 4 dirty files first.
- **Unauthenticated endpoints** (`/api/ask`, `/api/demo/*`, `/api/live/*`): documented as localhost-only. Acceptable.

## 6. First 30 seconds of the video

No title card. Nothing labelled "Simulated" before 0:30.

| Time | Picture | Voice-over |
|---|---|---|
| 0:00–0:06 | Real Ring frame, full screen, watermark visible. Label: "Ring Developer Playground · real footage, re-timed". Overlay: "−9 °C · insulin · 2:07 PM" | "This is a Ring doorbell. Rosa is 81, lives alone in Chicago, and her insulin was just left outside at nine below." |
| 0:06–0:13 | Phone buzzes with Rosa's Spanish SMS, English subtitle | "DoorLedger saw it and texted her, in Spanish, to bring it in." |
| 0:13–0:24 | Dashboard at 60×. The exposure clock runs and the box estimate slides toward 32 °F. Ladder: 2:27 Luis → 2:37 Ana | "Still there twenty minutes later, so it asks the neighbor, then her daughter, ten minutes apart." |
| 0:24–0:30 | "Inside 2:40 · est. 0.7 °C · confirm with the pharmacist", then the tagline | "Care arrives through the front door. DoorLedger checks that it did." |

Show the Bedrock label overlay only after fix #3, and the Ask shot only after fix #1.

## 7. Mini-challenge recommendation

Only one mini prize per project is awarded, so enter both, but tell one primary story.
- **Primary: Open Source**, if the public repo and PyPI release are approved by **18 Oct**. The SDK is the most distinctive artifact: 55 tests, CI on Python 3.10 and 3.13, examples, server-side WHEP and a signed webhook simulator.
- **Otherwise: AWS Builder.** AgentCore is now real: a read-only agent in a microVM next to a deterministic engine. Show a 3-second trace from a call that returned `runtime: agentcore`.
- **Odds:** Ring 1st ≈33%. Open Source ≈45% if published, ≈10% if not. AWS Builder ≈40%.
