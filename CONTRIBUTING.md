# Contributing

Use GitHub Issues for reproducible bugs and focused feature requests. For security concerns, follow [SECURITY.md](SECURITY.md). Review the data access limitations in the [README](README.en.md) before running live requests.

## Local setup

Use Python 3.13 and an isolated environment:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python tools/validate_project.py
.venv/bin/python tools/build_release.py
```

Tests run offline with actual Home Assistant classes and controlled HTTP responses. Do not make ordinary tests depend on Allegro availability or your own Home Assistant instance. Use minimal fixtures; do not commit full pages, cookies, credentials, location searches, or bulk point directories.

## Changes

- Keep one config entry per physical locker and preserve stable entity unique IDs.
- Keep network work asynchronous and release sessions on success, failure, cancellation, unload, and HA shutdown.
- Validate point identity, source timestamps, and finite numeric measurements. Missing readings are unavailable, never zero.
- A grouped map response is incomplete. Ask for a narrower search rather than fetching the entire country recursively.
- Update `strings.json` and both translations together. Keep Polish and English README instructions consistent.
- Add meaningful tests for changed behavior and update [CHANGELOG.md](CHANGELOG.md).

Keep pull requests focused. Describe the observed problem, resulting behavior, and validation. Do not include private email addresses or home coordinates in reports, commits, or fixtures.

The project is MIT licensed. By contributing, you agree that your contributions may be distributed under that license. No copyright assignment or legal name is required by this contribution policy.
