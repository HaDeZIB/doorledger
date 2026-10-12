# DoorLedger on AWS

DoorLedger keeps **ground truth deterministic**: what was expected at the door, compared with
what the Ring camera observed. AWS AI services handle perception, language and agentic
orchestration on top of that. Every AWS piece is optional and controlled by an env flag, so
the demo still runs offline.

```
Ring doorbell (WHEP live view / snapshots / signed webhooks)
        │ frames
        ▼
 ┌──────────────────────┐  Bedrock Converse (image)    ┌───────────────────────┐
 │ Watcher + Perception  │ ─────────────────────────▶  │ Amazon Nova 2 Lite     │
 │ vision.py, watcher.py │ ◀── strict JSON labels ───── │ (vision, per frame)    │
 └──────────┬───────────┘                               └───────────────────────┘
            │ Observations (package dropped, presence code, vehicle…)
            ▼
 ┌──────────────────────┐   deterministic, unit-tested; no LLM
 │ Engine + reconcile    │──▶ Findings (late, missed, short, package at risk…)
 │ + exposure model      │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐  Bedrock Converse (text)     ┌───────────────────────┐
 │ Responder (rules)     │ ─────────────────────────▶  │ Claude Haiku 4.5 →     │
 │ ladder + guardrails   │ ◀── SMS-length message ───── │ Nova Lite → template   │
 └──────────┬───────────┘                               └───────────────────────┘
            │ Actions (notify / backup request / pharmacy draft)
            ▼
 ┌──────────────────────┐ listener, background thread  ┌───────────────────────┐
 │ Append-only ledger    │ ───── PutItem ────────────▶  │ DynamoDB               │
 │ (SQLite, in process)  │  DOORLEDGER_DYNAMO=1         │ doorledger-ledger      │
 └──────────┬───────────┘                               │ pk=household sk=at#id  │
            │ read-only tools                           │ on-demand, TTL 30 d    │
            ▼                                           └───────────────────────┘
 ┌──────────────────────┐  local: Strands in process
 │ /api/ask /api/summary │──────────────────────────▶ CareAgent (Strands + Bedrock Converse)
 │ DoorLedger API        │
 │ (keeps guardrails)    │  DOORLEDGER_AGENTCORE_ARN set:
 └──────────┬───────────┘  export_snapshot() (no phone numbers)
            │ InvokeAgentRuntime (SigV4, session = household+day)
            ▼
 ┌───────────────────────────────────────────┐  Converse + tool use  ┌──────────────────┐
 │ Bedrock AgentCore Runtime (microVM, arm64) │ ───────────────────▶ │ Claude Haiku 4.5 │
 │ DoorLedgerAgent_CareAgent (CodeZip, Py3.12)│ ◀─ tool calls ─────── │ → Nova Pro       │
 │ engine_from_snapshot() → sealed engine     │                       └──────────────────┘
 │ CareAgent.ask/daily_summary, READ-ONLY     │──▶ CloudWatch logs + OTel traces
 └───────────────────────────────────────────┘
   falls back to the local agent on any error ("runtime": "local")
```

## What is actually deployed (11 Oct 2026, account `<account-id>`, us-east-1)

| Resource | Status | Notes |
|---|---|---|
| DynamoDB table `doorledger-ledger` (`arn:aws:dynamodb:us-east-1:<account-id>:table/doorledger-ledger`) | **Live** | Created by `deploy/create_dynamo.py`, which is idempotent. PAY_PER_REQUEST, TTL on `expires_at`, tagged `Project=doorledger`. Live test: a full-day replay mirrored 20 records (2 expectations, 5 observations, 6 findings, 7 actions) with 0 failures. Flush took 1.7 s in the background, and a single put took about 240 ms from Mexico. Those 20 demo rows are kept with a 3-day TTL. |
| AgentCore Runtime `DoorLedgerAgent_CareAgent-<id>` + CDK-created execution role (stack `AgentCore-DoorLedgerAgent-dev`) | **Live** (deployed 11 Oct, after the IAM grants and CDK bootstrap) | `deploy/agentcore/` (AgentCore CLI 0.31.1, CodeZip, arm64, Python 3.12). Live tests: 5/5 in `core/tests/test_aws_agentcore.py` with `DOORLEDGER_LIVE=1`. With `DOORLEDGER_AGENTCORE_ARN` set, `/api/ask` returns `"runtime": "agentcore"` (Claude Haiku 4.5), about 7.6 s round trip on a cold-ish session, and falls back to the in-process Strands agent on any error. The first deploy attempt was blocked by IAM ([friction log A2](../FRICTION_LOG.md#a2--agentcore-cli-deploy-hits-an-iam-wall-cdk-bootstrap--bedrock-agentcore-not-in-amazonbedrockfullaccess)); owner steps are in `deploy/agentcore/README.md`. |
| Bedrock models (Nova 2 Lite, Claude Haiku 4.5, Nova Pro / Lite) | In use | On demand, via the Converse API. |
| Lambda webhook receiver | Design only (below) | Not deployed. |

### Permissions that had to be granted before the deploy (verified with real calls from `doorledger-dev`)

`AmazonBedrockFullAccess` (v11) covers `bedrock:*` and `bedrock-mantle:*`, but **not**
`bedrock-agentcore:*`, which is a separate IAM prefix. The following calls were denied:
`bedrock-agentcore:ListAgentRuntimes`, `ListMemories`, `ListGateways`, `iam:CreateRole`,
`sts:AssumeRole` on `cdk-hnb659fds-*`, `cloudformation:CreateChangeSet`, `ListStacks`,
`s3:ListAllMyBuckets`, `ecr:DescribeRepositories`, `ssm:GetParameter` (`/cdk-bootstrap/*`),
`codebuild:ListProjects`, and `xray:GetTraceSegmentDestination`.

Minimum that unblocked the deploy:

1. An admin runs CDK bootstrap once:
   `npx aws-cdk@2.1126.0 bootstrap aws://<account-id>/us-east-1 --tags Project=doorledger`.
2. `doorledger-dev` gets the `BedrockAgentCoreFullAccess` managed policy (or the
   least-privilege list in the README), plus `sts:AssumeRole` on
   `arn:aws:iam::<account-id>:role/cdk-hnb659fds-*` and CloudFormation/SSM read access.

CloudFormation, through the bootstrap execution role, creates the runtime execution role. The
developer user never needs `iam:CreateRole`. Exact JSON and console clicks are in
[`deploy/agentcore/README.md`](../deploy/agentcore/README.md).

## Services in use

| Service | Where | How |
|---|---|---|
| **Amazon Bedrock: Converse API, image input** | `vision.py` (`BedrockVision`) | Each sampled doorbell frame goes to `us.amazon.nova-2-lite-v1:0` with a facts-only prompt that returns strict JSON (`package_visible`, `person_present`, `phone_screen_shown`…). A k-of-n tracker (`porch.py`) turns labels into Observations. Eval: 54/54 synthetic and 10/10 real Ring Playground frames, about $0.37 per 1k frames, p50 1.5 s. |
| **Amazon Bedrock: Converse API, text** | `responder.py` (`BedrockWriter`) | Rewrites each alert from a template into a short, warm SMS. Model chain: Claude Haiku 4.5, then Nova Lite, then template. An alert is never blocked by the LLM. |
| **Strands Agents SDK on Bedrock** | `agent.py` (`CareAgent`) | Strands `Agent` + `BedrockModel` (Converse with tool use) over `@tool` methods grounded in the engine: `get_today_status`, `get_timeline`, `export_evv` (read); `notify`, `request_backup_aide`, `draft_pharmacy_replacement` (act, gated by the Responder's guardrails). It serves family Q&A, the end-of-day summary, and an optional agentic `handle(finding)` mode. See `docs/agent_spike.md`. |
| **Amazon Bedrock AgentCore Runtime** | `deploy/agentcore/`, `aws/agentcore.py`, `aws/snapshot.py` | The same `CareAgent`, packaged with the AgentCore CLI (CodeZip, Python 3.12, OTel instrumentation) and invoked with `InvokeAgentRuntime`. It receives a read-only snapshot, never the live engine. See below. |
| **Amazon DynamoDB** | `aws/dynamo.py`, `deploy/create_dynamo.py` | Durable mirror of the append-only ledger. Each household has its own partition, and the sort key is `<UTC time>#<record id>`, so a day's history comes back from one `Query`. TTL expires old records automatically. |
| CloudWatch Logs / X-Ray | AgentCore Runtime | The CDK-created execution role is allowed to write runtime logs and traces. `agentcore logs` and `agentcore traces list` read them. |
| IAM | account | User `doorledger-dev`: Bedrock, DynamoDB, Lambda, SNS, Logs, Budgets read. |
| AWS Budgets | account | A US$30/month budget with email alerts. |

Agent orchestration patterns shown:

- **Tool-using agent.** The model plans which ledger tools to call and cites them.
- **Deterministic core with an LLM edge.** Rules decide that something happened and that
  someone must act. LLMs perceive frames, phrase messages and answer questions.
- **Guardrailed actions.** Every agent tool call that touches the world is checked by code
  (household membership, open incident, per-incident cap, ladder order and gap, no repeats).
  Refusals go back to the model as tool results.
- **Remote agent with least authority.** The agent on AgentCore can read and explain but cannot
  act. Guardrails and the ledger stay in the API.
- **Model routing with graceful degradation.** Claude, then Nova, then template, per
  capability. A model the account cannot use is skipped for the rest of the process. The
  AgentCore path falls back to the in-process agent in the same way.

## CareAgent on AgentCore Runtime: how it works

Source: AWS developer guide, *Get started with the AgentCore CLI* (Oct 2026). The current path
is the Node.js **AgentCore CLI** (`@aws/agentcore`, used here at 0.31.1), which provisions with
AWS CDK (`@aws/agentcore-cdk` L3 constructs). The Python `bedrock-agentcore-starter-toolkit` is
the legacy path.

1. **Snapshot, not shared state.** `export_snapshot(engine)` (`aws/snapshot.py`) takes the engine
   lock and serializes a consistent view: the household roster with `phone` and
   `telegram_chat_id` removed, expectations, observations, all ledger records, the clock, and
   the ambient temperature. A full demo day is 13 KB.
2. **Sealed engine in the runtime.** `engine_from_snapshot()` rebuilds an in-memory `Engine` with
   a frozen clock, a fixed ambient temperature (no weather calls), and a `ReadOnlyNotifier`
   that raises on any send. It does not re-run the rules: findings and actions come from the
   ledger exactly as recorded. Unit tests show the three read tools return byte-identical JSON
   on the live engine and on the sealed engine.
3. **Entrypoint** (`deploy/agentcore/app/CareAgent/main.py`, `BedrockAgentCoreApp`):
   `mode: ask | summary` only, plus `ping` (answers immediately, no model call; it warms the
   session). Any other mode, such as `handle`, is rejected with "this runtime cannot act".
4. **Packaging.** `deploy/agentcore/sync_core.py` walks the import graph from `agent.py` and
   `aws/snapshot.py` and vendors exactly 13 modules. API, watcher, vision and OpenCV are on a
   deny list. The runtime image therefore runs the same code as the local agent.
5. **API wiring** (appended to `api.py`, behind flags):
   - `DOORLEDGER_AGENTCORE_ARN` swaps the `/api/ask` and `/api/summary` routes for versions that
     call `AgentCoreCareAgent` (session id `doorledger-<household>-<local date>`) and fall back
     to the local Strands agent on any error. The browser only ever gets a generic error code
     (`agentcore_error: "AgentCore runtime unavailable (AccessDeniedException)"`); the raw
     message, which can quote ARNs and the account id, stays in the server log.
   - Warm-up: at API startup and whenever a demo scenario starts, a background `ping` on the
     day's session id boots the runtime microVM (at most once per 5 min), so the first question
     does not pay the session cold start. A failed ping is logged and ignored.
   - `DOORLEDGER_DYNAMO=1` attaches the DynamoDB mirror.
   - `GET /api/aws/status` reports mirror counters and whether AgentCore is configured.

Measured with the AgentCore SDK server locally on the same Bedrock models (Claude Haiku 4.5):

| Call | Latency | Tokens in / out | Model cost |
|---|---|---|---|
| `ask` "Did Maria come today, and how long did she stay?" (1 tool call) | 2.7 s | 3,873 / 126 | ≈ $0.0045 |
| `summary` (2 tool calls) | 4.3 s | 4,868 / 292 | ≈ $0.0063 |

In the cloud (deployed runtime, measured 11 Oct): `/api/ask` routed through
`InvokeAgentRuntime` took about **7.6 s** round trip on a cold-ish session (Claude Haiku 4.5).
That is the same model time plus the InvokeAgentRuntime round trip and microVM start-up. Warm
calls in the same session should be faster, but we have not measured them yet.

## Design only: Ring webhooks on Lambda

Today `POST /webhooks/ring` in the API verifies the HMAC, parses the event and starts a
watching session (`live.py`). The serverless version would work like this:

```
Ring partner webhook ─▶ Lambda function URL (auth NONE; HMAC is the auth)
                         doorledger-ring-webhook (Python 3.12, arm64, 256 MB, 5 s timeout)
                         1. verify X-Ring-Signature with ringpartner.webhooks.verify_and_parse
                            (HMAC key from Secrets Manager / SSM SecureString)
                         2. dedupe on event id: DynamoDB conditional PutItem (pk=hh, sk=webhook#id)
                         3. write an Observation (source=ring_webhook) to doorledger-ledger
                         4. fan out to the API (SQS or EventBridge) to start live watching
                         5. return 200 in < 1 s (Ring requires an answer within 5 s)
```

- **Why a function URL rather than API Gateway:** one route, the signature is the
  authentication, and there is no extra hourly or request cost.
- **Permissions:** the execution role needs `dynamodb:PutItem` on the table and
  `ssm:GetParameter` / `secretsmanager:GetSecretValue` on the key. The deploying user also needs
  `iam:CreateRole` + `iam:PassRole` for the execution role, or a CDK deploy through the
  bootstrap roles, as AgentCore now uses.
- **Cost:** free tier covers about 1M requests per month, so roughly $0 at demo scale.

## Costs

| Item | This work (11 Oct) | Ongoing |
|---|---|---|
| DynamoDB on demand: about 45 writes, a handful of queries, 20 rows stored with TTL | < $0.001 | $1.25 per M writes; storage is pennies; $0 idle |
| Bedrock calls for the local AgentCore entrypoint test (ask + summary) | ≈ $0.011 | ≈ $0.0045 per question, ≈ $0.0063 per summary |
| AgentCore Runtime | ≈ $0 (a handful of live test calls) | CPU billed only while active; memory about 0.5 GB × (call + 300 s idle timeout) ≈ < $0.001 per question; $0 with no sessions |
| CDK bootstrap (S3 bucket + ECR repo) | $0 | ≈ $0 |
| **Total for this task** | **≈ $0.02** | A 50-question demo day costs about $0.30 |

## Clean up

- **DynamoDB:** `aws dynamodb delete-table --table-name doorledger-ledger`.
- **AgentCore:** `agentcore remove all && agentcore deploy --target dev --yes`, then optionally
  delete the `CDKToolkit` stack (empty its bucket first).
