# Friction log: DoorLedger (Ring track + AWS)

Developer-experience feedback from building DoorLedger against the **Ring Partner API /
Developer Playground** and **Amazon Bedrock** during the hackathon. All entries were recorded on
**11 Oct 2026** by a solo developer based in **Mexico**, using a new Amazon developer account and
a new AWS account.

**Format for each entry:** task attempted · steps · expected vs. actual · severity · time lost ·
workaround · actionable suggestion.

- **Severity scale.** *Critical* blocks all progress on the path. *High* blocks a feature or a
  first run, or forces a redesign. *Medium* costs real time or causes a wrong first
  implementation. *Low* is a papercut or a docs inconsistency.
- **Time lost** is an honest estimate of wall-clock time spent on the problem itself, not on
  building workarounds. Status is *Open* unless the entry says *Resolved*.

## Summary (ordered by severity)

| ID | Area | Issue | Severity | Time lost | Status |
|---|---|---|---|---|---|
| [F1](#f1--developer-registration-route-renders-404-blocks-the-playground) | Ring | Developer registration route renders 404, which blocks the Playground | Critical | ~45 min | Resolved (incognito) |
| [A1](#a1--claude-on-bedrock-is-gated-by-the-anthropic-use-case-form-with-a-resourcenotfoundexception) | AWS | Claude on Bedrock is gated by the Anthropic use-case form and fails with `ResourceNotFoundException` | High | ~35 min | Resolved |
| [A2](#a2--agentcore-cli-deploy-hits-an-iam-wall-cdk-bootstrap--bedrock-agentcore-not-in-amazonbedrockfullaccess) | AWS | AgentCore CLI deploy needs CDK bootstrap and `bedrock-agentcore:*`, which `AmazonBedrockFullAccess` lacks | High | ~1.5 h | Open (deploy pending IAM) |
| [F3](#f3--the-playground-does-not-deliver-webhooks) | Ring | The Playground does not deliver webhooks | High | ~30 min | Worked around |
| [F2](#f2--no-hardware-promise-vs-ring-getting-started) | Ring | "No hardware needed" promise vs. Ring Getting Started | Medium | ~1 h | Resolved (forum) |
| [R1](#r1--ring-appstore-and-the-test-phase-are-us-only) | Ring | Ring Appstore and the Test phase are US-only | Medium | ~20 min | Open |
| [R2](#r2--privacy-zones-cannot-be-configured-in-the-playground) | Ring | Privacy zones cannot be configured in the Playground | Medium | ~15 min | Open |
| [R3](#r3--sub_type-is-an-open-vocabulary-but-no-api-says-whether-smart-alerts-is-on) | Ring | `sub_type` is an open vocabulary, but no API says whether Smart Alerts is on | Medium | ~15 min | Open |
| [F5](#f5--playground-scene-selection-is-invisible-to-api-clients) | Ring | Playground scene selection is invisible to API clients | Medium | ~20 min | Worked around |
| [F6](#f6--re-opening-a-whep-session-too-soon-returns-http-500) | Ring | Re-opening a WHEP session too soon returns HTTP 500 | Medium | ~30 min | Worked around |
| [F7](#f7--snapshot-latest_in_range-returns-403-time-range-not-within-authorized-boundaries) | Ring | Snapshot `latest_in_range` returns 403 | Medium | ~30 min | Worked around |
| [A3](#a3--claude-haiku-55--sonnet-55-not-available-for-this-account-with-no-reason) | AWS | Claude Haiku 5.5 / Sonnet 5.5 "not available for this account", with no reason given | Medium | ~20 min | Open |
| [A4](#a4--new-account-bedrock-throttling-and-quotas-that-cannot-be-read) | AWS | New-account Bedrock throttling, and quotas the dev user cannot read | Medium | ~15 min | Worked around |
| [F4](#f4--no-official-partner-sdk) | Ring | No official Partner SDK | Medium | n/a (we built one) | Worked around |
| [A5](#a5--amazon-nova-canvas-is-locked-as-legacy-on-a-new-account) | AWS | Amazon Nova Canvas is locked as "Legacy" on a new account | Low | ~15 min | Worked around |
| [A6](#a6--temperature-0-is-rejected-by-newer-claude-models) | AWS | `temperature: 0` is rejected by newer Claude models | Low | ~10 min | Worked around |
| [R4](#r4--docs-inconsistencies-private-app-account-limit-and-a-broken-release-notes-anchor) | Ring | Docs inconsistencies: private-app account limit, broken release-notes anchor | Low | ~5 min | Open |
| [F8](#f8--merged-into-f1) | Ring | Merged into F1 | n/a | n/a | Closed |

**Total time lost to platform friction:** about **7.5 h** (estimate). The largest items are the
AgentCore IAM wall (A2), the "is the Playground the simulator?" research (F2) and the
registration 404 (F1).

---

## Critical

### F1 — Developer registration route renders 404 (blocks the Playground)
- **Status:** **Resolved.** The page works in an incognito window. The likely root cause is a
  browser extension in the regular profile that broke a script on the registration page. We did
  not isolate which extension.
- **Task:** Get a Ring Developer Playground token, the hackathon's official Ring "simulator".
- **Steps:**
  1. Signed in at developer.amazon.com with a new developer account (Mexico).
  2. Opened `https://developer.amazon.com/ring/console/playground`. It redirected to
     `/settings/console/registration?return_to=/ring/console/playground`.
  3. Started the registration form (Sole Proprietorship).
  4. From then on, every console URL redirected to `/settings/console/registration?...`. That
     includes `/ring/console`, `/alexa/console/ask`, `/settings/console/myaccount` and the LWA
     console. The route rendered **"404 Page not found"**. The account menu's "Complete
     Registration" link also landed on the 404.
  5. Retried in an incognito window with no extensions. The registration form rendered, and the
     Playground opened after we submitted it.
- **Expected:** The registration form (or a "registration pending" message), then the Playground.
- **Actual:** A hard 404 with no error message. There was no way to finish registration or to
  learn what was missing.
- **Severity:** Critical. It blocks the only documented Ring path for entrants without hardware.
- **Time lost:** ~45 min.
- **Workaround:** Incognito window or another browser.
- **Suggestion:** Never return 404 on the registration route. If a required script fails to
  load, show "Something blocked this page. Try disabling extensions or use a private window"
  instead of a 404. Show the incomplete step and its validation errors. Link to support with
  the account ID pre-filled.

## High

### A1 — Claude on Bedrock is gated by the Anthropic use-case form, with a `ResourceNotFoundException`
- **Status:** Resolved. Claude Haiku 4.5 now writes DoorLedger's messages and answers CareAgent
  questions.
- **Task:** Call Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) through the
  Bedrock Converse API on a new account, for the vision eval, the message writer and the agent.
- **Steps:**
  1. Called `converse` with the inference-profile id. The call failed with
     `ResourceNotFoundException: Model use case details have not been submitted for this
     account`.
  2. `us.anthropic.claude-sonnet-4-6` behaved inconsistently. One tiny text call succeeded, then
     all 46 image calls in the eval failed with the same error.
  3. Found the one-time Anthropic use-case form under Model catalog → an Anthropic model, and
     submitted it at 15:27.
  4. At 15:30 calls still failed. They started succeeding about **15 minutes** after submission.
- **Expected:** Either the model works, or the error says "submit the use-case form at
  <link>" with a clear status such as `AccessDeniedException`.
- **Actual:** `ResourceNotFoundException`, the error class for a wrong model id, wrapping an
  account-state problem. The message text is clear-ish, but the exception type sends you to
  check model ids and Regions first. There is no status indicator for the form, and the
  propagation delay is undocumented.
- **Severity:** High. It blocks every first Claude call on a new account, and it blocked our
  planned Claude vision eval (the measured eval covers Nova only).
- **Time lost:** ~35 min, including the propagation wait.
- **Workaround:** Code-level model chains (Claude → Nova → template) that skip a model for the
  rest of the process on an access error (`agent.py`, `responder.py`). The demo kept working
  while access was pending.
- **Suggestion:** Return `AccessDeniedException` with a reason code
  (`USE_CASE_FORM_REQUIRED`) and a console deep link. Show the form status ("submitted,
  propagating, about 15 min") on the model card. Let the form be completed from the CLI or API
  for headless setups.

### A2 — AgentCore CLI deploy hits an IAM wall (CDK bootstrap + `bedrock-agentcore:*` not in `AmazonBedrockFullAccess`)
- **Status:** Open. CareAgent is packaged and tested locally. Cloud deploy is pending IAM
  grants. Details and the exact policy JSON are in
  [`deploy/agentcore/README.md`](deploy/agentcore/README.md).
- **Task:** Deploy the Strands CareAgent to Amazon Bedrock AgentCore Runtime from the
  developer IAM user.
- **Steps:**
  1. Searched for the getting-started path. Results mix the Python
     `bedrock-agentcore-starter-toolkit` (now documented as the legacy path) with the Node
     **AgentCore CLI** (`@aws/agentcore`, which AWS documents as current). Picking the right one
     took reading both.
  2. Ran `agentcore create` (Strands, Python, CodeZip) and `agentcore validate`: OK.
  3. Ran the entrypoint locally under the AgentCore SDK (`/ping`, `/invocations`): OK, with
     Claude Haiku 4.5.
  4. Ran `agentcore package`: OK (41.5 MB arm64 zip).
  5. Ran `agentcore deploy --dry-run`: the synth succeeded, then it stopped at "AWS environment
     needs bootstrapping".
  6. Ran `agentcore deploy --yes`: `not authorized to perform: cloudformation:CreateChangeSet on
     resource: .../stack/CDKToolkit/*`.
  7. Probed permissions. `bedrock-agentcore:ListAgentRuntimes`, `iam:CreateRole`,
     `sts:AssumeRole` on `cdk-hnb659fds-*`, `s3:ListAllMyBuckets`, `ecr:DescribeRepositories` and
     `ssm:GetParameter /cdk-bootstrap/*` were all denied.
- **Expected:** A user with `AmazonBedrockFullAccess` can deploy a Bedrock agent runtime, or
  the CLI says up front which permissions and bootstrap steps are missing.
- **Actual:** `bedrock-agentcore:*` is a separate IAM prefix that `AmazonBedrockFullAccess`
  does not include. The CLI deploys through AWS CDK, so the account also needs a one-time CDK
  bootstrap by an admin, plus `sts:AssumeRole` on the bootstrap roles. Each missing piece shows
  up one failure at a time.
- **Severity:** High. It blocks the AWS-native deployment of the agent.
- **Time lost:** ~1.5 h, including reading the toolkit vs. CLI docs and probing permissions.
- **Workaround:** The API calls the in-process Strands agent. The AgentCore client is wired
  behind `DOORLEDGER_AGENTCORE_ARN` and falls back to the local agent on any error.
- **Suggestion:** Add an `agentcore doctor` (or `deploy --preflight`) that checks bootstrap
  state and simulates the needed IAM actions, then prints one policy to attach. Either fold
  `bedrock-agentcore:*` into `AmazonBedrockFullAccess` or name `BedrockAgentCoreFullAccess`
  in the first error. Put a "legacy, use `@aws/agentcore`" banner on every starter-toolkit page.

### F3 — The Playground does not deliver webhooks
- **Status:** Worked around.
- **Task:** Exercise an event-driven flow: a Ring `motion_detected` or `button_press` webhook
  opens a live-view session.
- **Steps:** Configured a webhook receiver, then pressed the Package, Vehicle and Motion buttons
  in the Playground.
- **Expected:** Signed webhooks, or at least documentation that none are sent.
- **Actual:** The buttons create `on_demand` history rows with no `sub_type`. No webhook is ever
  sent, so the event-driven pattern the rubric calls "creative" can't be exercised end to end
  with Ring-generated events.
- **Severity:** High. It forces either a simulator or a polling redesign.
- **Time lost:** ~30 min to confirm there was nothing to configure.
- **Workaround:** Built a signed webhook simulator into our open-source SDK
  (`ringpartner simulate`). We also added a history poller (`live.py`) that reacts to real
  Playground history rows.
- **Suggestion:** Let the Playground POST signed sample webhooks (all 10 documented types) to a
  configured URL, signed with a Playground HMAC key.

## Medium

### F2 — "No hardware needed" promise vs. Ring Getting Started
- **Status:** Resolved through a Devpost forum reply.
- **Task:** Find out whether a physical Ring device is needed.
- **Steps:** Read the hackathon page, Ring Getting Started and the Ring developer docs.
- **Expected:** One clear statement.
- **Actual:** The hackathon page says "no physical device required / simulators". Ring Getting
  Started says "At least one Ring device for testing". The word "simulator" does not appear in
  the Ring docs. The answer (the Playground *is* the simulator) only appeared in a Devpost forum
  reply.
- **Severity:** Medium.
- **Time lost:** ~1 h.
- **Workaround:** Asked on the forum.
- **Suggestion:** Add a "Develop without hardware" section to Ring Getting Started. It should
  name the Playground and list what it simulates (one doorbell, three live-view scenes,
  snapshots, history) and what it does not (webhooks, chimes, sensors, privacy zones, OAuth
  linking).

### R1 — Ring Appstore and the Test phase are US-only
- **Status:** Open.
- **Task:** Plan the production path: account linking, staging users, subscription webhooks.
- **Steps:** Read the Develop guide and FAQ before attempting the Test phase from Mexico.
- **Expected:** Non-US hackathon entrants can at least test the Appstore flow.
- **Actual:** The Develop guide says "Currently we only support devices located in the US", and
  FAQ Q21 says the Ring Appstore is reachable only from US locations (other visitors are
  forwarded to the Ring home page). A non-US entrant can't exercise OAuth linking, staging
  users or `subscription_activated` against real accounts. The Playground is the only path.
- **Severity:** Medium. The Playground covers development, but certification-relevant flows
  can't be tested.
- **Time lost:** ~20 min, reading and re-planning.
- **Workaround:** None for the real flows. The simulator covers the subscription and
  integration webhook payload shapes.
- **Suggestion:** Allow staging (Test phase) from any country with a US-located test device or
  a Playground device. State the restriction on the hackathon page.

### R2 — Privacy zones cannot be configured in the Playground
- **Status:** Open.
- **Task:** Test that DoorLedger never analyses or stores video inside a customer's privacy
  zones, as the Ring UX guidance requires.
- **Steps:** Read the Playground device's `capabilities` and `configurations`.
- **Expected:** A way to set a privacy zone on the Playground device, since honouring them is a
  certification concern.
- **Actual:** `capabilities.image_enhancements.configurations` lists `privacy_zones`, and
  `configurations.image_enhancements.privacy_zones` is returned as `[]`. Nothing in the
  Playground lets you set one, so the masking path can only be tested with synthetic zones.
- **Severity:** Medium.
- **Time lost:** ~15 min.
- **Workaround:** DoorLedger blacks out zones from `configurations` before any analysis or
  storage (`privacy.apply_privacy_zones`). It can only be exercised with synthetic polygons (test pending).
- **Suggestion:** Add privacy-zone (and motion-zone) editing to the Playground, or provide
  preset devices with zones configured.

### R3 — `sub_type` is an open vocabulary, but no API says whether Smart Alerts is on
- **Status:** Open.
- **Task:** Map `motion_detected.sub_type` to what DoorLedger should look for (package vs.
  person).
- **Steps:** Read the webhook docs.
- **Expected:** A way to know whether `motion` means "unclassified because Smart Alerts is off"
  or "classified as generic motion".
- **Actual:** The docs say `sub_type` is `motion` when Smart Alerts is off and
  `human`/`vehicle`/`package_delivery`/`other_motion` when it is on. They also say *"No API
  exposes whether Smart Alerts is enabled on a device"*. An app therefore can't tell "Ring saw
  no package" from "Ring didn't classify".
- **Severity:** Medium. It pushes every partner into running its own classifier on every motion
  event.
- **Time lost:** ~15 min.
- **Workaround:** Treat `sub_type` as a hint only. DoorLedger always runs its own vision model
  and passes unknown values through.
- **Suggestion:** Expose Smart Alerts state (read-only) in `configurations`, like
  `motion_detection.enabled`.

### F5 — Playground scene selection is invisible to API clients
- **Status:** Worked around.
- **Task:** Capture a specific Playground scene (Package) over a server-side WHEP session.
- **Steps:** Opened a WHEP session from Python and got whichever scene was last picked in the
  browser.
- **Expected:** An API parameter to pick the scene, or documentation of the behaviour.
- **Actual:** Package, Vehicle and Motion are chosen by clicking buttons in the Playground web
  UI. A server-side WHEP session then streams whatever scene was last picked. No parameter or
  endpoint selects a scene, and nothing documents that the UI choice is global per account.
- **Severity:** Medium.
- **Time lost:** ~20 min.
- **Workaround:** Click the scene in the UI, then open our own session.
- **Suggestion:** Support `POST .../whep/sessions?simulated_event=package` in the Playground, or
  document the behaviour.

### F6 — Re-opening a WHEP session too soon returns HTTP 500
- **Status:** Worked around.
- **Task:** Keep watching during a care window, which needs back-to-back live sessions (Ring
  caps them at 30–60 s).
- **Steps:** Closed a session with `DELETE <Location>`, then immediately POSTed a new offer.
- **Expected:** A new session, or `409`/`429` with `Retry-After`.
- **Actual:** Re-opening within about 20–40 s returns `500 Internal server error` with no hint.
- **Severity:** Medium. It looks like a server bug and caused a wrong first diagnosis (we
  suspected our ICE gathering).
- **Time lost:** ~30 min.
- **Workaround:** Wait 20 s between sessions (`SESSION_GAP_SECONDS` in `live.py`).
- **Suggestion:** Return `409` or `429` with `Retry-After` and say a session is still active.

### F7 — Snapshot `latest_in_range` returns 403 "time range not within authorized boundaries"
- **Status:** Worked around.
- **Task:** Fetch an evidence snapshot for a recent event.
- **Steps:** Requested `POST /media/image/download` with a range covering the last 10 minutes.
- **Expected:** The latest image in that range.
- **Actual:** 403 *"time range not within authorized boundaries"*. A request with `at_timestamp`
  equal to a history event's `start` works.
- **Severity:** Medium.
- **Time lost:** ~30 min.
- **Workaround:** Always snapshot at a history event's start (`live.py` history poller).
- **Suggestion:** Explain the authorized window in the error detail (consent time? bounded by
  events?), and document it next to the range parameters.

### A3 — Claude Haiku 5.5 / Sonnet 5.5 "not available for this account", with no reason
- **Status:** Open. We use Claude Haiku 4.5.
- **Task:** Evaluate the newest Claude models for vision and messages.
- **Steps:** Called `us.anthropic.claude-haiku-5-5` and `us.anthropic.claude-sonnet-5-5` (and the
  `global.` profiles), both before and after the use-case form had propagated.
- **Expected:** The model works, or the error says why (account age, quota, Region, sales
  contact).
- **Actual:** `AccessDeniedException: ... not available for this account`, with no reason and no
  next step. The console shows the model in the catalog.
- **Severity:** Medium. The planned model comparison is incomplete.
- **Time lost:** ~20 min.
- **Workaround:** Stay on Claude Haiku 4.5.
- **Suggestion:** Include a reason code and next step in the error (for example "new accounts
  get access after N days" or "request access here"), and show the restriction on the model
  card.

### A4 — New-account Bedrock throttling, and quotas that cannot be read
- **Status:** Worked around.
- **Task:** Run the vision eval: 11 runs × 54 frames, plus image generation.
- **Steps:** Ran the eval with up to 6 parallel runs.
- **Expected:** Default quotas sufficient for a small eval, or a clear way to see them.
- **Actual:** A brand-new account got `ThrottlingException` from Stable Image Core almost
  immediately, and once from Nova 2 Lite with 6 parallel runs. The least-privilege dev user
  could not read Service Quotas, so we couldn't check our per-minute limits. Production at
  1 frame/s is 60 requests per minute per camera.
- **Severity:** Medium.
- **Time lost:** ~15 min.
- **Workaround:** Retries with back-off in the evaluator. Motion gating cuts vision calls 38–60%
  in production.
- **Suggestion:** Show the effective RPM/TPM per model on the model card, readable with the same
  `bedrock:*` permissions. Include the quota name in the throttling error.

### F4 — No official Partner SDK
- **Status:** Worked around. We published our own.
- **Task:** Call the Partner API from a Python backend.
- **Expected:** An official SDK, or at least a reference client.
- **Actual:** The docs say *"There is no official Ring Partner SDK"*. Every partner
  re-implements JSON:API parsing, the 303 pre-signed media flow (fetched *without* the
  `Authorization` header), WHEP negotiation and HMAC verification.
- **Severity:** Medium.
- **Time lost:** Not counted. Building the SDK became one of our deliverables.
- **Workaround:** [`ringpartner`](packages/ringpartner) (Python, Apache-2.0, with tests and CI).
- **Suggestion:** Ship minimal official SDKs (TypeScript and Python), or endorse a community one
  from the docs.

## Low

### A5 — Amazon Nova Canvas is locked as "Legacy" on a new account
- **Status:** Worked around.
- **Task:** Generate synthetic doorbell frames for the vision eval.
- **Steps:** Called Amazon Nova Canvas.
- **Expected:** The model works, or the catalog says it isn't available to new accounts.
- **Actual:** *"marked by provider as Legacy and you have not been actively using the model in
  the last 30 days"*. A new account can never have used it, so it can't use it at all.
- **Severity:** Low.
- **Time lost:** ~15 min.
- **Workaround:** Stability Stable Image Core in us-west-2 ($0.04/image).
- **Suggestion:** Hide or label legacy models as unavailable for new accounts in the catalog,
  and name the successor model in the error.

### A6 — `temperature: 0` is rejected by newer Claude models
- **Status:** Worked around in the eval harness. It was not observed live, because the 5.5
  models are unavailable to us (A3).
- **Task:** Make the vision and agent calls deterministic.
- **Steps:** Read Anthropic's model docs while preparing the 5.5 eval configs.
- **Expected:** `temperature: 0` is accepted everywhere, as on Nova and Claude Haiku 4.5.
- **Actual:** Per the docs, Haiku 5.5 and Sonnet 5.5 return 400 on a non-default `temperature`,
  and both think by default. Code that sends `temperature: 0` to every model (as our
  `BedrockVision` does) breaks when the model id changes.
- **Severity:** Low.
- **Time lost:** ~10 min.
- **Workaround:** Per-model inference settings in `eval/vision/run_eval.py`, which omits
  temperature and sets `thinking` for the 5.5 models.
- **Suggestion:** Ignore `temperature: 0` with a warning instead of returning 400. Alternatively,
  expose a per-model "supported inference parameters" field in `GetFoundationModel`.

### R4 — Docs inconsistencies: private-app account limit and a broken release-notes anchor
- **Status:** Open.
- **Task:** Decide whether a private app could run the agency pilot (see
  [docs/BUSINESS.md](docs/BUSINESS.md)).
- **Actual:**
  - The 21 Jul 2026 release notes say private apps "support up to 5 allowlisted Ring accounts".
    The FAQ (answer to Q16) says up to **10**.
  - The Develop guide links to `release-notes.html#september-10-2026`, but the entry is dated
    **September 11, 2026**, so the anchor doesn't resolve.
- **Severity:** Low.
- **Time lost:** ~5 min.
- **Suggestion:** Note limit changes in the release notes ("raised from 5 to 10 on …"), and
  link-check docs anchors in CI.

### F8 — Merged into F1
The follow-up finding (the 404 disappears in an incognito window, so a browser extension is the
likely cause) is now part of [F1](#f1--developer-registration-route-renders-404-blocks-the-playground).
