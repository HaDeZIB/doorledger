# Contributing to DoorLedger

Thanks for your interest. DoorLedger is a hackathon project that is being opened up. Issues and
pull requests are welcome, especially for the `ringpartner` SDK, which is useful to anyone who
builds on the Ring Partner API.

## Ground rules

- **Be honest about where data comes from.** Every observation carries a `Source`
  (`ring_live_view`, `ring_snapshot`, `ring_webhook`, `own_footage`, `simulated`). Never label simulated
  or self-recorded footage as Ring footage, in code, fixtures, screenshots or docs.
- **Ground truth stays deterministic.** Whether a visit happened, how long it lasted and whether
  a package is at risk are decided by `reconcile.py` and `exposure.py`, and they are unit-tested.
  LLMs may perceive frames, phrase messages and answer questions. They never decide outcomes.
  Every outbound action goes through the Responder guardrails.
- **No face recognition.** Caregivers are identified only by the signed rotating presence code
  they show to the doorbell. Do not add biometric identification. Stored evidence frames are
  face-pixelated.
- **No secrets in the repo.** Ring tokens, HMAC keys, AWS credentials and Telegram tokens go in
  `.env` (git-ignored). Recorded fixtures must never contain bearer tokens or pre-signed
  `security_token` values. `ringpartner`'s `RecordingTransport` strips both, so keep it that way.
- **Tests run offline.** `uv run pytest -q` must pass with no AWS credentials and no network.
  Live tests are opt-in (`DOORLEDGER_LIVE=1`).

## Setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+ (CI uses Node 24).

```bash
uv sync --all-packages        # core + ringpartner + dev tools
cp .env.example .env          # optional; only needed for Ring / Bedrock / Telegram
(cd web/dashboard && npm ci)
make help                     # list of run targets
```

## Before you open a pull request

```bash
make test                     # uv run pytest -q
make lint                     # uv run ruff check packages/ringpartner
make sdk-check                # build ringpartner and run twine check
(cd web/dashboard && npm run build)
```

CI (`.github/workflows/ci.yml`) runs the same steps, plus the ringpartner tests against the
built wheel on Python 3.10 and 3.13.

## Layout and ownership

| Path | What | Notes |
|---|---|---|
| `packages/ringpartner/` | Unofficial Ring Partner API SDK (Python ≥3.10) | Keep its only hard dependency `httpx`. Live video stays behind the `[whep]` extra. Update `CHANGELOG.md`. |
| `core/src/doorledger/` | Engine, reconciliation, presence codes, vision, agent, API | Python 3.12. Add a test with every behavior change. |
| `web/dashboard/` | Next.js dashboard | API contract in `web/dashboard/API_CONTRACT.md`. |
| `web/caregiver-pass/` | Caregiver Pass (static page) | Must stay byte-compatible with `presence.py`. `core/tests/test_js_parity.py` enforces it. |
| `eval/` | Vision and presence evaluations | Commit the script, the labels and `RESULTS.md`. Note honestly what is synthetic. |
| `fixtures/` | Recorded Ring Playground frames and responses | Third-party content: see `NOTICE`. |

## Commit messages

Use a short imperative subject (`ringpartner: retry 503 with backoff`). Describe what changed and
why in the body.

## Releasing ringpartner (maintainers)

1. Bump `version` in `packages/ringpartner/pyproject.toml` and `__version__` in
   `src/ringpartner/__init__.py`, then move the `Unreleased` notes in `CHANGELOG.md`.
2. Run `make sdk-check`.
3. Tag `ringpartner-vX.Y.Z`, then publish with `uv publish dist/ringpartner-*`. Trusted
   publishing is recommended.

## License

By contributing, you agree that your contributions are licensed under the Apache License 2.0
(see `LICENSE`), the same license as the project.
