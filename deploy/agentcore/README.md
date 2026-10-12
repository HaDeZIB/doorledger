# DoorLedger CareAgent on Amazon Bedrock AgentCore Runtime

This folder is an **AgentCore CLI** project (`@aws/agentcore` 0.31.1, the Node CLI that AWS
documents as current; the Python `bedrock-agentcore-starter-toolkit` is the legacy path). It
was scaffolded with:

```
agentcore create --project-name DoorLedgerAgent --name CareAgent --language Python \
  --framework Strands --model-provider Bedrock --memory none --build CodeZip \
  --idle-timeout 300 --max-lifetime 900
```

After scaffolding, the generated sample agent was replaced with DoorLedger's own `CareAgent`.

## What runs in the runtime (and what cannot)

```
DoorLedger API (guardrails + ledger)                       AgentCore Runtime (microVM, arm64)
------------------------------------                       ----------------------------------
POST /api/ask ─▶ export_snapshot(engine)  ── InvokeAgentRuntime ──▶ main.py @app.entrypoint
                 (roster without phones,     (SigV4, session =        engine_from_snapshot()
                  expectations, observations, household+day)          → sealed in-memory engine
                  ledger records, now, °C)                            CareAgent(engine).ask()
                                             ◀── JSON answer ──────   Strands + Bedrock Converse
                                                                      Claude Haiku 4.5 → Nova Pro
```

* **Read-only by design.** The entrypoint accepts only `mode: ask | summary` (plus `ping`, a
  no-model warm-up the API sends when a scenario starts). Both modes give the
  Strands agent only the read-only tools (`get_today_status`, `get_timeline`, `export_evv`). The
  rebuilt engine's notifier raises on every send (`ReadOnlyNotifier`), the snapshot carries no
  phone numbers or chat ids, and the runtime has no notification credentials. Guardrailed actions
  (notify, backup aide, pharmacy draft) run only in the DoorLedger API process.
* **Same code as local.** `sync_core.py` vendors the exact core modules the agent imports
  (`agent`, `engine`, `reconcile`, `exposure`, `responder`, `ledger`, `aws/snapshot`…, 13 files, no
  OpenCV) into `app/CareAgent/doorledger/` (gitignored). The unit test
  `core/tests/test_aws_snapshot.py` proves the tools return identical JSON on the live engine
  and on the rebuilt snapshot engine.

Payload contract (`POST /invocations`):

```json
{"mode": "ask", "question": "Did Maria come today?", "snapshot": { "version": 1, "...": "..." }}
{"mode": "summary", "snapshot": { "...": "..." }}
{"mode": "ping"}
```

Response: `{"answer"|"summary", "tool_calls", "model", "latency_ms", "usage", "runtime": "agentcore", "session_id", "handler_ms", "snapshot_now"}`.

## Status: DEPLOYED (11 Oct 2026, after the IAM grants below); the history of the first, blocked attempt is kept for the friction log

| Step | Result |
|---|---|
| `agentcore create` + `agentcore validate` | OK |
| Entrypoint served locally by the AgentCore SDK (`python main.py`, `/ping` + `/invocations` on :8080) | OK. `ask` 2.7 s, `summary` 4.3 s, Claude Haiku 4.5, grounded answers that cite tools. Unsupported `mode: "handle"` is rejected. |
| `agentcore package` | OK. `CareAgent.zip` is 41.5 MB (linux/aarch64, Python 3.12, strands-agents 1.59.0, bedrock-agentcore 1.24.1, OTel distro). |
| `agentcore deploy --dry-run` | Synth OK: `AWS::IAM::Role` (execution role) + `AWS::BedrockAgentCore::Runtime` `DoorLedgerAgent_CareAgent`, both tagged `Project=doorledger`. Stopped at "AWS environment needs bootstrapping." |
| `agentcore deploy --yes` | **Blocked:** `doorledger-dev is not authorized to perform: cloudformation:CreateChangeSet on resource: arn:aws:cloudformation:us-east-1:<account-id>:stack/CDKToolkit/*`. Nothing was created. |

Other `doorledger-dev` permission checks, using real calls on 11 Oct:

| Call | Result |
|---|---|
| `bedrock-agentcore:ListAgentRuntimes`, `ListMemories`, `ListGateways` | AccessDenied |
| `iam:CreateRole` (role `AmazonBedrockAgentCoreRuntime-doorledger`) | AccessDenied |
| `sts:AssumeRole` on `cdk-hnb659fds-deploy-role-*` | AccessDenied (the role also does not exist; CDK is not bootstrapped) |
| `cloudformation:CreateChangeSet`, `ListStacks`; `s3:ListAllMyBuckets`; `ecr:DescribeRepositories`; `ssm:GetParameter` `/cdk-bootstrap/*`; `codebuild:ListProjects`; `xray:GetTraceSegmentDestination` | AccessDenied |
| `cloudformation:DescribeStacks`, `iam:GetRole`, `iam:ListRoles`, DynamoDB, Lambda, Logs | allowed (from AWSLambda_FullAccess / DynamoDB / Logs policies) |

`AmazonBedrockFullAccess` (v11) grants `bedrock:*`, `bedrock-mantle:*`, and `iam:PassRole` on
`*AmazonBedrock*` roles. It does **not** grant `bedrock-agentcore:*`, which is a separate IAM
service prefix.

## What the owner must do in the console (about 5 minutes, one time)

The AgentCore CLI deploys through AWS CDK. You need two things: (1) the account must be **CDK
bootstrapped** once, by someone with admin rights, and (2) `doorledger-dev` must be allowed to
**assume the CDK bootstrap roles** and **call AgentCore**. CloudFormation then creates the
runtime execution role on your behalf, so `doorledger-dev` never needs `iam:CreateRole`.

### Step 1: Bootstrap CDK (admin, in AWS CloudShell, us-east-1)

1. Sign in to the console as the account admin. Switch the Region to **US East (N. Virginia)**.
2. Open **CloudShell** (the `>_` icon in the top bar).
3. Run:
   ```
   npx -y aws-cdk@2.1126.0 bootstrap aws://<account-id>/us-east-1 --tags Project=doorledger
   ```
   This creates the `CDKToolkit` stack: an assets S3 bucket, an ECR repository, an SSM version
   parameter, and five `cdk-hnb659fds-*` roles. Cost is about $0 at rest.
   By default the CloudFormation execution role gets `AdministratorAccess`. To narrow it, add
   `--cloudformation-execution-policies arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess,arn:aws:iam::aws:policy/IAMFullAccess`.

### Step 2: Grant `doorledger-dev` deploy and invoke rights

Go to **IAM → Users → doorledger-dev → Permissions**.

**Option A (quickest).** Choose **Add permissions → Attach policies directly**, attach the AWS
managed policy **`BedrockAgentCoreFullAccess`**, then add this inline policy (**Add permissions →
Create inline policy → JSON**, name it `DoorLedgerCdkDeploy`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeCdkBootstrapRoles",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::<account-id>:role/cdk-hnb659fds-*-<account-id>-us-east-1"
    },
    {
      "Sid": "ReadDeployState",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks", "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources", "cloudformation:GetTemplate",
        "cloudformation:ListStacks", "ssm:GetParameter"
      ],
      "Resource": "*"
    }
  ]
}
```

**Option B (least privilege).** Use this instead of `BedrockAgentCoreFullAccess`. Add these
statements to the inline policy above:

```json
{
  "Sid": "AgentCoreRuntimeUse",
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:GetAgentRuntime",
    "bedrock-agentcore:GetAgentRuntimeEndpoint", "bedrock-agentcore:ListAgentRuntimes",
    "bedrock-agentcore:ListAgentRuntimeEndpoints", "bedrock-agentcore:ListAgentRuntimeVersions",
    "bedrock-agentcore:StopRuntimeSession"
  ],
  "Resource": "arn:aws:bedrock-agentcore:us-east-1:<account-id>:*"
},
{
  "Sid": "AgentCoreTraces",
  "Effect": "Allow",
  "Action": ["xray:GetTraceSummaries", "xray:BatchGetTraces", "xray:GetTraceSegmentDestination"],
  "Resource": "*"
}
```

The runtime only needs `bedrock-agentcore:InvokeAgentRuntime` to serve `/api/ask`. The other
actions are for `agentcore status`, `agentcore logs`, and `agentcore traces`. Option B could not
be tested end to end from this account. If `agentcore status` reports a denied action, add that
action or fall back to Option A.

## Deploy (after the grants)

```
cd deploy/agentcore
python sync_core.py                       # vendor the core modules into app/CareAgent/
(cd agentcore/cdk && npm ci)              # once; node_modules is gitignored
# account-specific files are gitignored (public repo); start from the redacted template:
cp agentcore/aws-targets.example.json agentcore/aws-targets.json   # then put your account id in it
npx -y @aws/agentcore@0.31.1 deploy --target dev --yes --verbose
npx -y @aws/agentcore@0.31.1 status       # prints the runtime ARN
```

Smoke test, then wire the API:

```
DOORLEDGER_LIVE=1 DOORLEDGER_AGENTCORE_ARN=<runtime-arn> uv run pytest -q core/tests/test_aws_agentcore.py
DOORLEDGER_AGENTCORE_ARN=<runtime-arn> uv run uvicorn doorledger.api:app --port 8787
curl -s localhost:8787/api/ask -H 'content-type: application/json' -d '{"question":"Did Maria come today?"}'
# → "runtime": "agentcore", plus "roundtrip_ms". On any AgentCore error the API falls back to the
#   in-process Strands agent and returns "runtime": "local" with "agentcore_error".
curl -s localhost:8787/api/aws/status
```

## Cost

| Item | Estimate |
|---|---|
| Model tokens per question (measured: 3.9k in / 0.13k out, Claude Haiku 4.5 at $1 / $5 per Mtok) | ≈ $0.0045 |
| Model tokens per daily summary (measured: 4.9k in / 0.29k out) | ≈ $0.0063 |
| Runtime compute per question. CPU is billed only while active (LLM I/O wait is free). Memory: ~0.5 GB × (4 s + 300 s idle timeout) at about $0.017/GB-h (v2) | < $0.001 |
| Idle runtime with no sessions | $0 |
| CDK bootstrap bucket and ECR repo | ≈ $0 |

A 50-question demo day costs about $0.30.

Gitignored here because the repo is public: `agentcore/aws-targets.json` (template:
`aws-targets.example.json`), `agentcore/.cli/` (deployed state with ARNs, logs),
`agentcore/*.zip`, `agentcore/*/staging/`, `agentcore/cdk/cdk.out/`, `app/CareAgent/doorledger/`.

## Clean up

```
npx -y @aws/agentcore@0.31.1 remove all && npx -y @aws/agentcore@0.31.1 deploy --target dev --yes
```

After that, the `CDKToolkit` stack can stay or be deleted in CloudFormation. Empty its S3
bucket first.
