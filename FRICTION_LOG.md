# Friction Log — DoorLedger (Ring track)

Format per entry: task · steps · expected vs. actual · severity · workaround · actionable suggestion.

---

## F1 — Developer registration page returns 404 (blocks Ring Playground)
- **Task:** Get a Ring Developer Playground token (the hackathon's official Ring "simulator").
- **Steps:** Signed in at developer.amazon.com (new developer account, Mexico) → opened `https://developer.amazon.com/ring/console/playground` → redirected to `/settings/console/registration?return_to=/ring/console/playground` → started the registration form (Sole Proprietorship) → afterwards every console URL (`/ring/console`, `/alexa/console/ask`, `/settings/console/myaccount`, LWA console) redirects to `/settings/console/registration?...`, which renders **"404 Page not found"**. The account menu shows "Complete Registration", which also lands on the 404.
- **Expected:** Registration form (or a "registration pending" message) and then the Playground.
- **Actual:** Hard 404 with no error message; no way to finish registration or to know what is missing.
- **Severity:** Critical (blocks the only documented Ring path for non-US entrants).
- **Workaround:** _(in progress)_ incognito window / different browser.
- **Suggestion:** Never 404 on the registration route; show the incomplete step and its validation errors, and link to support with the account ID pre-filled.

## F2 — Simulator promise vs. Ring docs
- **Task:** Understand whether a physical Ring device is needed.
- **Expected:** One clear statement.
- **Actual:** Hackathon page says "no physical device required / simulators"; Ring Getting Started says "At least one Ring device for testing"; the word "simulator" does not appear in Ring docs. Answer only found in a Devpost forum reply (the Playground is the simulator).
- **Severity:** Medium (cost ~1 h of research).
- **Suggestion:** Add a "Develop without hardware" section to Ring Getting Started that names the Playground and lists what it does and does not simulate (no motion webhooks, no chime, no sensors).

## F3 — Playground does not deliver webhooks
- **Actual:** Package/Vehicle/Motion buttons create `on_demand` history rows with no `sub_type`; no `motion_detected` webhook is ever sent, so event-driven apps (the "creative" pattern in the judging rubric) cannot be exercised end to end.
- **Workaround:** Built a signed webhook simulator into our open-source SDK (`ringpartner simulate`).
- **Suggestion:** Let the Playground POST signed sample webhooks to a configured URL.

## F4 — No official Partner SDK
- **Actual:** Docs say "There is no official Ring Partner SDK". Every partner re-implements JSON:API parsing, the 303 pre-signed media flow, WHEP, HMAC verification.
- **Workaround:** Published `ringpartner` (Python, Apache-2.0).
- **Suggestion:** Ship minimal official SDKs (TS/Python) or endorse a community one.
