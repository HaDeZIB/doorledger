# DoorLedger on AWS

DoorLedger keeps **ground truth deterministic** (what was expected at the door vs. what the
Ring camera observed) and uses AWS AI services for perception, language and agentic
orchestration on top of it.

```
Ring doorbell (WHEP live view / snapshots / webhooks)
        │ frames
        ▼
 ┌──────────────────────┐  Bedrock Converse (image)   ┌───────────────────────┐
 │ Watcher + Perception  │ ─────────────────────────▶ │ Amazon Nova 2 Lite     │
 │ vision.py, watcher.py │ ◀── strict JSON labels ──── │ (vision, per frame)    │
 └──────────┬───────────┘                              └───────────────────────┘
            │ Observations (package dropped, presence code, vehicle…)
            ▼
 ┌──────────────────────┐   deterministic, unit-tested; no LLM
 │ Engine + reconcile    │──▶ Findings (late, missed, short, package at risk…)
 │ + exposure model      │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐  Bedrock Converse (text)    ┌───────────────────────┐
 │ Responder (rules)     │ ─────────────────────────▶ │ Claude Haiku 4.5 →     │
 │ ladder + guardrails   │ ◀── SMS-length message ──── │ Nova Lite → template   │
 └──────────┬───────────┘                              └───────────────────────┘
            │ Actions (notify / backup request / pharmacy draft)
            ▼
   Append-only ledger (SQLite now; DynamoDB mirror) ──▶ dashboard, EVV CSV
            ▲
            │ read-only tools / guarded action tools
 ┌──────────┴───────────┐  Bedrock Converse + tool use ┌───────────────────────┐
 │ CareAgent (Strands)   │ ─────────────────────────▶ │ Claude Haiku 4.5 →     │
 │ agent.py              │ ◀── tool calls / answer ─── │ Nova Pro (fallback)    │
 └──────────────────────┘                              └───────────────────────┘
   POST /api/ask · GET /api/summary
```

## Services in use

| Service | Where | How |
|---|---|---|
| **Amazon Bedrock: Converse API, image input** | `vision.py` (`BedrockVision`) | Each sampled doorbell frame goes to `us.amazon.nova-2-lite-v1:0` with a facts-only prompt that returns strict JSON (`package_visible`, `person_present`, `phone_screen_shown`…). A k-of-n tracker (`porch.py`) turns labels into Observations. Eval: 54/54 synthetic and 10/10 real Ring Playground frames, about $0.37 per 1k frames, p50 1.5 s. |
| **Amazon Bedrock: Converse API, text** | `responder.py` (`BedrockWriter`) | Rewrites each alert from a template into a short, warm SMS. Model chain: Claude Haiku 4.5, then Nova Lite, then template. An alert is never blocked by the LLM. |
| **Strands Agents SDK on Bedrock** | `agent.py` (`CareAgent`) | Strands `Agent` + `BedrockModel` (Converse with tool use) over `@tool` methods grounded in the engine: `get_today_status`, `get_timeline`, `export_evv` (read); `notify`, `request_backup_aide`, `draft_pharmacy_replacement` (act, gated by the Responder's guardrails). It serves family Q&A, the end-of-day summary, and an optional agentic `handle(finding)` mode. Model: Claude Haiku 4.5 when the account has access, else Nova Pro. See `docs/agent_spike.md`. |
| IAM | account | A least-privilege user for local development: `bedrock:InvokeModel*` on the model ids above. |
| AWS Budgets | account | A US$30/month budget with email alerts. |

Agent orchestration patterns shown:

- **Tool-using agent.** The model plans which ledger tools to call and cites them.
- **Deterministic core with an LLM edge.** Rules decide that something happened and that
  someone must act. LLMs perceive frames, phrase messages and answer questions.
- **Guardrailed actions.** Every agent tool call that touches the world is checked by code
  (household membership, open incident, per-incident cap, ladder order and gap, no repeats).
  Refusals go back to the model as tool results.
- **Model routing with graceful degradation.** Claude, then Nova, then template, per
  capability. A model the account cannot use is skipped for the rest of the process.

## Proposal: deploy CareAgent to Amazon Bedrock AgentCore Runtime (researched, not deployed)

Source: AWS developer guide, *Get started with the AgentCore CLI* (Oct 2026). The Python
`bedrock-agentcore-starter-toolkit` CLI (`agentcore configure` / `agentcore launch`) is
marked **no longer supported**. The current path is the Node.js **AgentCore CLI**
(`npm i -g @aws/agentcore`), which provisions resources with AWS CDK.

**Shape.** The agent becomes a stateless AgentCore Runtime service. The DoorLedger API keeps
the ledger and **enforces guardrails server-side**, so a compromised or confused agent still
cannot message anyone outside the rules.

1. **Split the tools behind HTTP.**
   - Read tools call `GET /api/state` and `GET /api/timeline` (they already exist) and
     `GET /api/evv.csv`.
   - Action tools call new guarded endpoints, such as `POST /api/agent/notify`, which run the
     same `CareTools.check_notify` code inside the API process.
   - Optionally put these behind **AgentCore Gateway** (`agentcore add gateway`) so they appear
     to the agent as MCP tools with outbound auth.
2. **Entrypoint** (`app/CareAgent/main.py`, generated by `agentcore create --framework Strands`):
   ```python
   from bedrock_agentcore.runtime import BedrockAgentCoreApp
   app = BedrockAgentCoreApp()

   @app.entrypoint
   def invoke(payload):
       mode = payload.get("mode", "ask")          # ask | summary
       agent = build_agent(household_id=payload["household_id"])  # Strands Agent + HTTP tools
       return {"answer": str(agent(payload.get("prompt", "Write today's summary.")))}

   if __name__ == "__main__":
       app.run()   # serves /invocations and /ping on :8080
   ```
3. **Scaffold, test, deploy:**
   ```
   npm install -g @aws/agentcore
   agentcore create --project-name DoorLedgerAgent --name CareAgent --language Python \
     --framework Strands --model-provider Bedrock --memory none --build CodeZip
   agentcore dev                 # local server + agent inspector
   agentcore deploy --dry-run    # preview CDK changes
   agentcore deploy              # first run bootstraps CDK; creates the Runtime endpoint + CloudWatch
   agentcore status              # prints the agent runtime ARN
   agentcore invoke --prompt '{"mode":"ask","household_id":"hh_rosa","prompt":"Did Maria come today?"}'
   agentcore logs --since 30m ; agentcore traces list
   ```
4. **Call from the API.** `POST /api/ask` would call
   `boto3.client("bedrock-agentcore").invoke_agent_runtime(agentRuntimeArn=…,
   runtimeSessionId=<household+day>, payload=…)`. The local `CareAgent` stays as the fallback.
   Required permission: `bedrock-agentcore:InvokeAgentRuntime`.
5. **Optional later steps:**
   - `agentcore add memory` for short-term memory per family member, so follow-up questions
     keep context.
   - AgentCore Observability traces for the judges' demo.
   - `agentcore add evaluator` to score grounding (does the answer cite a ledger time?).
6. **Clean up:** run `agentcore remove all`, then `agentcore deploy`.

**Cost and risk notes.**

- Runtime is billed per active session compute. The model calls are the same as today (about
  $0.003 per question on Nova Pro).
- The runtime execution role needs `bedrock:InvokeModel` on the chosen models, CloudWatch
  Logs, and X-Ray.
- The main risk is demo-day latency (cold microVM). Keep the in-process agent as the fallback
  path.
