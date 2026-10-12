# Live run: Ring Playground click → Rosa's phone rings

This is the one unbroken take that shows DoorLedger reacting to Ring in real time:

1. You click **Package** in the Ring Developer Playground
   (`developer.amazon.com/ring/console/playground`).
2. Ring records it in the device's event history.
3. DoorLedger's history poller sees the new event and fetches Ring snapshots taken at the
   moment it started.
4. Ring privacy zones are blacked out and faces pixelated. Then **Amazon Nova 2 Lite** on
   Bedrock labels each frame.
5. The porch tracker's k-of-n vote decides "package dropped".
6. Reconciliation finds insulin on a −9 °C porch.
7. The responder calls Rosa in Spanish through **Amazon Connect** and texts her through
   **Amazon SNS**. Your phone rings.

The dashboard's top card shows each step with its time and measured latency, labelled **Live**.
Latencies are measured from Ring's own timestamp of the event. The same numbers are printed in
the terminal and saved as JSON under `fixtures/raw/live_runs/`, which git ignores.

Code: [`scripts/live_demo.py`](../scripts/live_demo.py),
[`core/src/doorledger/live_session.py`](../core/src/doorledger/live_session.py) (run, trace,
safety caps), [`live_preflight.py`](../core/src/doorledger/live_preflight.py) (preflight,
probe, offline Playground replay) and [`live.py`](../core/src/doorledger/live.py) (history
poller, snapshot burst, WHEP).

## Safety: what a live run can send

| | Default | Change with |
|---|---|---|
| Calls | **1**, to Rosa only, dialled **only** to `DOORLEDGER_VOICE_TO` | `--max-calls N` |
| SMS | **1**, **only** to `DOORLEDGER_SMS_TO` (any per-person number is dropped) | `--max-sms N` |
| Second call at +5 min, texts to Luis and Ana | **skipped** (logged as "skipped" on the trace) | `--full-ladder` (still capped) |
| Asks before arming | yes, type `yes` | `--yes` |
| `/api/demo/*` while the run is active | refused (409) | n/a |

`make live-dry` and `make live-rehearse` never send anything. Tests never build a real
Connect or SNS client: the wrappers refuse to under pytest.

## What the Playground actually emits (and what we still don't know)

These facts come from our recorded Playground responses (`fixtures/playground/`) and
[`FRICTION_LOG.md`](../FRICTION_LOG.md):

- **No webhooks** (F3). The Package, Vehicle and Motion buttons open a live view, and Ring logs
  it as an **`on_demand` history row** with no `sub_type`. Our recorded rows last 20–40 s, with
  `start` and `end` in epoch milliseconds.
- **Snapshots at a row's `start` work.** Ring renders the selected scene and stamps it
  "Generated-At". The range form (`latest_in_range`) returns **403** (F7).
- **WHEP streams whatever scene was last clicked**, for the whole account (F5). Re-opening a
  WHEP session within about 20–40 s returns **HTTP 500** (F6).
- **Unknown until you try with a token:** whether the row appears when the live view *starts*
  or only when it *ends*, and whether our own WHEP session can run while the Playground page is
  streaming. `make live-probe` answers the first question in two minutes.

So DoorLedger supports two triggers:

| Trigger | How it notices | Expected time from click to call | When to use |
|---|---|---|---|
| `history` (default) | Polls history every 2 s and takes 3 snapshots at the row's start (+0/+1/+2 s) | Row appears at start: **~10 s**. Row appears at end: **~40–50 s** | The probe shows a new row within ~45 s of the click |
| `whep` | 25 s WHEP sessions at 1 fps, back to back with the 20 s gap the Playground needs. History rows are still recorded, to timestamp the click | Up to **~50 s** | The probe shows **no** new row. First click **Motion** so the starting scene has no package |
| `both` | Both at once | Whichever is faster | Only if the probe showed a slow row and WHEP works |

## Before the day (once)

`.env` must have these lines (values are never printed or committed):
`DOORLEDGER_VOICE_TO`, `DOORLEDGER_SMS_TO`, `DOORLEDGER_CONNECT_INSTANCE_ID`,
`DOORLEDGER_CONNECT_FLOW_ID`, `DOORLEDGER_CONNECT_SOURCE_NUMBER`. The AWS CLI user needs
Bedrock, Connect and SNS permissions. Optionally set `RING_DEVICE_ID`; otherwise the first
device is used.

Rehearse offline any time. No token is needed and nothing is sent:

```bash
make live-rehearse        # terminal 1: API on :8787 with recorded Playground data
make dashboard            # terminal 2: open http://localhost:3000
```

About 8 s after start, a recorded "Package click" fills the card at the top of the dashboard.

## On the day, step by step

The token lasts about 30 minutes, so do steps 2–8 in one go (about 15 minutes).

1. **Close the other DoorLedger API.** Anything on port 8787 has to stop, including the
   `doorledger-api` preview server. Preflight checks for this.
2. **Get a token.** Open the Playground in normal Chrome and generate a token. In `.env`,
   replace the line `RING_ACCESS_TOKEN=...` with the new one: no quotes, no spaces. Save the
   file.
3. **Preflight:** `make live-preflight`. Every line must read `OK` or `WARN`.
   - `FAIL Ring devices: 401`: the token was pasted wrong or has expired. Repeat step 2.
   - `FAIL API port`: something is still running on 8787. Repeat step 1.
   - `FAIL Amazon Connect …` or `FAIL Amazon SNS …`: check those `.env` lines. Or use
     `make live-dry`, which doesn't need them.
   - `WARN Ring snapshot … 403`: the history trigger will fall back to the live view. Run the
     probe.

   Preflight makes one Nova call (about US$0.0004) and only read-only AWS lookups. It places
   no call and sends no SMS.
4. **Probe (2 min, read-only):** `make live-probe`. When it says "click 'Package'", click
   **Package** in the Playground once and wait. Each new history row prints as a line like
   `+12.0s on_demand start 19:07:03Z open published 3.1 s after its start snapshot: ok`.
   - A row appears: keep the default `history` trigger. `published N s after its start` is
     roughly your click-to-notice time.
   - No row in 120 s: use `ARGS="--trigger whep"` in steps 6 and 7. Before starting, click
     **Motion** and wait a minute.
5. **Dashboard:** in a second terminal, run `make dashboard` and open `http://localhost:3000`.
   Press **D** to hide the demo strip.
6. **Dry run (no phone):** `make live-dry` (add `ARGS="--trigger whep"` if step 4 said so).
   Click **Package**. Within about 10–50 s the card fills in: Ring event, Frame, Nova 2 Lite,
   Porch k-of-n, Finding. Call and SMS read "not placed (dry run)". Press Ctrl-C. The terminal
   prints the timeline and latencies.
7. **The take.**
   - Wait about 60 s after the last Playground live view, because of the WHEP 500 above.
   - Phone on the desk, ringer on, Do Not Disturb off. Laptop showing the Playground and the
     dashboard. Start recording, with a clock or stopwatch in frame.
   - Run `make live`. It runs preflight again, then asks you to type `yes`.
   - Click **Package**. The dashboard fills in, then the phone rings. Answer on speaker.
   - The SMS arrives at the same moment. Let the message finish.
   - Press Ctrl-C and stop recording.
8. **Keep the numbers.** The terminal summary and `fixtures/raw/live_runs/live_*.json` hold
   the measured latencies: Ring event → noticed, snapshot, Nova, decision, call placed,
   answered. Use them in the video's lower third and in the Devpost text.

Useful options, passed as `ARGS="..."`:

| Option | Effect |
|---|---|
| `--minutes 10` | Stop watching after 10 minutes. The API stays up until Ctrl-C |
| `--ambient-c real` | Use Open-Meteo instead of the story's −9 °C. In October Chicago is usually above 5 °C, so **no alert** would fire |
| `--snapshots 3` | Snapshots per Ring event (3 = the porch tracker's 3-of-5 vote) |
| `--whep-followup` | Also open a 25 s live view after the snapshots |
| `--device ID` | Pick the Ring device |

**Time zone.** The dashboard and the card show Rosa's local time (Chicago). Until 1 Nov 2026
Chicago is on CDT (UTC−5), one hour ahead of Tampico (UTC−6). To show "2:07 PM" on screen,
record at 1:07 pm Tampico time.

**Honesty labels.** The −9 °C is set for the story; the card says so. The delivery window is
set around "now". The Ring event, the snapshots, the Nova labels, the decision, the call and
the SMS are all real and live.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Card says "Waiting for a Ring event…" long after the click | The Playground hasn't published the row yet; it may appear only when its live view ends. Wait about 45 s. If nothing appears, use the WHEP trigger |
| "Nova 2 Lite … no package" | The snapshot shows another scene. Click **Package**, not Motion or Vehicle |
| "Problem: history poll failed: 401" | The token expired mid-run. New token, then restart `make live` |
| Call says "failed" | Amazon Connect rejected the call; the SMS was still sent. Check the terminal log, `DOORLEDGER_CONNECT_*` and the IAM permissions |
| SMS never arrives | The SNS sandbox destination isn't verified. Preflight reports this |
| WHEP "500" lines | You opened sessions too close together. Wait 60 s |

## Verified offline vs. needs the live token

**Offline: tested in `core/tests/test_live_session.py` and run as `make live-rehearse`.**
- The full chain on the recorded Playground device, its history and its Package frame: Ring
  event → 3 distinct snapshots at its start → vision → 3-of-5 decision → finding → exactly one
  Connect call to `DOORLEDGER_VOICE_TO` → one SNS SMS to `DOORLEDGER_SMS_TO` → call outcome.
  Connect and SNS are stubbed.
- The trace order and latencies.
- No re-call and no Luis or Ana without `--full-ladder`. The caps hold even with it.
- A dry run sends nothing.
- With the WHEP trigger, history rows are only recorded.
- No package means no call.
- The API refuses demo runs during a live run.
- Preflight runs on the recorded Playground responses and never prints secrets.
- The probe output.

**Needs the token (tomorrow):**
- When the Playground publishes its history row.
- Real snapshot and Nova latency.
- Whether our WHEP session can run alongside the Playground page.
- The real Connect and SNS round trip.
