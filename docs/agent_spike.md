# Spike S5: CareAgent (Strands Agents on Amazon Bedrock)

**Date:** 2026-10-11 · **SDK:** `strands-agents` 1.59.0 · **Region:** us-east-1
**Code:** `core/src/doorledger/agent.py`, `core/tests/test_agent.py`, `scripts/agent_spike.py`,
and two endpoints added to `core/src/doorledger/api.py`.

## What was built

`CareAgent` wraps a Strands `Agent` + `BedrockModel` around the deterministic engine. The tools
are `@tool` methods on `CareTools`, so one instance serves one household.

| Tool | Kind | Grounded in |
|---|---|---|
| `get_today_status()` | read | `Engine.state()`: visits, deliveries with the exposure estimate, findings, actions. Compact JSON, about 4.3 KB, local HH:MM times, source label for every observation |
| `get_timeline(since_hour)` | read | ledger records (observations, findings, actions) from that local hour onward |
| `export_evv()` | read | `evv.rows()` (Cures Act fields) |
| `notify(person_name, message, reason)` | act | goes through `Responder.allowed` plus the agent guardrails below |
| `request_backup_aide(reason)` | act | only for an open **visit** incident, once per incident |
| `draft_pharmacy_replacement(expectation_id)` | act | only when the deterministic exposure status is `compromised`. Saved as a draft and never sent |

Capabilities:

- `ask(question)` gets **read-only tools only**, so a question typed into the family app can
  never send a message.
- `daily_summary()` also gets read-only tools.
- `handle(finding)` is optional. It exposes the read and act tools. The incident key comes
  from the deterministic finding, so the agent cannot invent an incident. It is **not wired**
  into the engine or the API, and the Responder rules remain the default path (see the
  verdict below).

Guardrails on every outbound call. A refusal comes back to the model as a tool result that
gives the reason.

1. The person must be in the household. A caregiver is never contacted directly; the message
   goes through the agency.
2. The message must belong to an open incident. Outside `handle()` there must be exactly one
   open incident. The tool replies "no open incident…" otherwise.
3. The per-incident cap is enforced (`MAX_MESSAGES_PER_INCIDENT` = 5) through `Responder.allowed`.
4. Porch incidents climb the ladder in order (patient, then neighbor, then family). Climbing a
   rung requires `LADDER_GAP` (10 min) since the last message. Family and patient may always be
   told about a `compromised` package.
5. Visit incidents may contact only the agency and family.
6. The same person cannot be messaged twice about the same incident within 10 min. This rule
   was added after a live run where Nova messaged the patient twice in one turn.
7. Safety wording is deterministic: `exposure_estimate.assessment` is a fixed string per
   status, so the LLM repeats a grade it did not make.

The model is chosen through `DOORLEDGER_AGENT_MODEL` (pinned first choice). The default order
is Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`), then Nova Pro
(`us.amazon.nova-pro-v1:0`). A model that fails with an access or use-case error is skipped
for the rest of the process. Today Claude fails with `ResourceNotFoundException: Model use
case details have not been submitted`, so every call lands on Nova Pro. The failed probe
costs about 0.2 s once per process.

API (additive; existing endpoints untouched):

- `POST /api/ask {question}` returns `{answer, tool_calls:[{name,input}], model, latency_ms, usage}`
- `GET /api/summary` returns `{summary, tool_calls, model, latency_ms, usage}`
- Returns 503 if no Bedrock model is reachable.

## Tests

`uv run pytest core/tests/test_agent.py`: **12 passed, 1 skipped** (live). The full suite
gives 93 passed, 1 skipped. The tests make no network calls. Each one replays `full_day`
minute by minute with `agent.replay_scenario()`, or builds observations by hand.

They cover these cases:

- Status and timeline grounding: 09:22/10:05 check-in, 43 of 120 min, drop 14:07, inside
  15:26, Luis texted at 15:17 with its cause.
- EVV export.
- Refusals: outsider, caregiver, wrong role for a visit incident, no incident, ladder
  skipping, ladder gap ("wait until 14:17"), repeat message, cap.
- Pharmacy draft only when the exposure is compromised.
- Backup aide deduplicated and refused for a porch incident.
- Model fallback (Claude use-case error, then Nova), remembered across calls.
- `<thinking>` stripping, tool-call capture, and `ask` getting read-only tools.

`DOORLEDGER_LIVE=1 uv run pytest -k live` passed against Nova Pro: the answer had to cite
09:22 and 43 min, and a tool had to be called.

## Live run

Command:
```
DOORLEDGER_WRITER=template DOORLEDGER_PERCEPTION=off uv run python scripts/agent_spike.py --api --handle
```
The script uses the real `api.engine`. Only the agent called Bedrock. The scenario was
`full_day` at 34 °C. The sample answers are from the final run (`run_pro2`, default model
order, which resolves to Nova Pro).

| # | Question | Tools | Latency | Tokens in/out |
|---|---|---|---|---|
| 1 | Did Maria come today? | get_today_status | 1.72 s | 3373 / 87 |
| 2 | Is mom's insulin ok? | get_today_status | 1.91 s | 3396 / 124 |
| 3 | Why did you text Luis? | get_today_status | 2.14 s | 3392 / 126 |
| 4 | Did mom take her blood pressure pills this morning? *(not in data)* | get_today_status | 1.99 s | 3393 / 111 |
| — | daily_summary() | get_today_status | 2.61 s | 3311 / 203 |

1. *"Yes, Maria came today. She checked in at 09:22 and checked out at 10:05, as shown by the
   caregiver's signed presence code read at the door."*
2. *"The insulin was delivered at 14:07 and brought inside at 15:26. The estimated temperature
   inside the box was 29.0°C, which is close to the heat limit. It is probably usable, but it is
   recommended to confirm with the pharmacist."*
3. *"Luis was texted at 15:17 because Rosa's refrigerated medication had been on her porch for
   70 minutes in the heat, and she hadn't picked it up. The text asked Luis to bring the
   medication inside for her. This information is from the actions section of today's status."*
4. *"I don't know if Rosa took her blood pressure pills this morning. I can see that Maria, the
   caregiver, arrived at 09:22 and left at 10:05, but there's no mention of blood pressure pills
   in the data."*

**Summary:** *"Today, caregiver Maria from BrightPath Home Care arrived at 09:22 for Rosa's
morning personal care, which was 22 minutes after the planned start time. Maria stayed for 43
minutes, which is less than the planned 120 minutes. The insulin refill from CVS Specialty
arrived at 14:07 and was left on the porch for 79 minutes, with an estimated internal
temperature of 29°C. It is likely safe but should be confirmed with the pharmacist. DoorLedger
contacted BrightPath Home Care about Maria's late arrival and short visit, Rosa about the warm
medication, Luis the neighbor for help, and Ana, Rosa's daughter, to inform her about the
medication's status."*

Every fact checks against the ledger.

### handle() mode (rules silenced, guardrails on)

| Finding | Nova Pro run 1 | Nova Pro run 2 (after the repeat guardrail) | Nova 2 Lite | Rules would do |
|---|---|---|---|---|
| missed_visit 09:50 | request_backup_aide | request_backup_aide | request_backup_aide | backup request **and** notify Ana |
| package_at_risk 15:17 | notify Rosa, pharmacy draft (refused: at_risk), notify Rosa **again** | notify Rosa | pharmacy draft (refused), notify Rosa | notify Rosa (or the next rung) |

None of the runs violated a guardrail. Run 1 messaged Rosa twice, which led to guardrail 6.
On missed visits the agent never told the family. The rules always do.

### Nova Pro vs Nova 2 Lite (same five prompts)

| | Nova Pro | Nova 2 Lite |
|---|---|---|
| ask p50 latency | 1.95 s | 2.09 s (max 3.98 s) |
| tokens per ask | about 3.4K in / 110 out (1 tool call) | 4–11K in (often called 2–3 tools, including irrelevant `export_evv`) |
| cost per ask (list price) | about US$0.0031 | about US$0.0015–0.0037 |
| grounding errors | none | named the source "Ring doorbell camera" for the presence code (the label was fixed afterwards); the summary claimed Maria was "kept updated" (false) and used headings/paragraphs despite "no markdown" |

Prices used: Nova Pro $0.80 / $3.20 and Nova 2 Lite $0.30 / $2.50 per 1M in/out tokens.
For reference, Claude Haiku 4.5 is $1 / $5. **Total Bedrock spend for this spike was about
US$0.09** (4 runs, 26 agent calls), well under the US$1 cap. The failed Claude probes are not
billed.

## Verdict

- **Nova Pro is good enough for `ask` and `daily_summary` today.** It made one tool call, cited
  times and sources, said "I don't know" correctly, made up no facts, and answered in about
  2 s for about $0.003. Keep the default order (Claude Haiku 4.5 first, then Nova Pro). When
  the Anthropic use-case form is approved, Claude takes over automatically with no code
  change. Haiku 4.5 would likely improve tone and instruction-following (format, brevity),
  not correctness. Waiting for Claude is **not** a blocker.
- **Do not use Nova 2 Lite for the agent.** It over-calls tools and made one false claim. It
  remains the right model for per-frame vision (S3), where it is cheaper and was 54/54.
- **Keep `handle()` opt-in and off the default path.** It is safe: across 6 runs no guardrail
  was ever bypassed. It is less complete than the deterministic Responder, though (no family
  notice on a missed visit). The demo story stays the same: "rules decide and act; the
  agent explains, and can propose actions that the same guardrails gate." It is useful for
  the AWS Builder "agentic architecture" point.

## Issues and notes

- The engine dedups findings by `(expectation_id, kind)`. After the 09:16 `late_arrival`
  *warning*, the later `late_arrival` *info* ("checked in 22 min late at 09:22") is never
  written to the ledger. The agent works around it with `minutes_after_window_start` in the
  status, but the ledger timeline only shows "Maria is late", never "arrived late". This is
  for the engine owner to decide.
- `api.evv_csv` calls `reconcile` without `in_sun=` (a different exposure estimate than the
  engine). This has no effect on EVV rows, and the agent's `export_evv` passes `in_sun`.
- Strands `Agent` instances are stateful and lock against concurrent calls, so `CareAgent`
  builds a fresh `Agent` per question. That is cheap: model and tool objects are built in
  milliseconds. There is no memory across questions, which is intentional for now.
- Strands' default `PrintingCallbackHandler` prints to stdout, so `callback_handler=None` is
  required in a server.
