# Contributing to QuotaRadar

Thank you for contributing to QuotaRadar.

## Before you start

Read the following documents:

- `AGENTS.md`;
- `docs/ARCH-QUOTARADAR-0001-System-Architecture.md`;
- `docs/SPEC-QUOTARADAR-0001-Technical-Specification.md`;
- all active ADRs under `docs/`.

Changes must not silently violate architecture constraints. Any proposal that conflicts with ARCH, SPEC, or an accepted ADR requires a separate ADR before implementation.

## Project boundaries

The current scope includes only:

- the approved allowlist: `@OpenAIDevs`, `@thsottiaux`, fallback `@sama`, and `@ClaudeDevs`;
- official X API v2 access;
- automatic LLM classification;
- Telegram channel delivery and personal notifications;
- one mandatory proxy for every external integration;
- Django Admin;
- Docker Compose.

RSS, X scraping, manual moderation, and sources outside the approved allowlist require a separate architecture decision.

## Local development on Linux

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run unit tests and verify migrations:

```bash
python manage.py test --settings=quotaradar.test_settings
python manage.py makemigrations --check --dry-run --settings=quotaradar.test_settings
```

Run the complete PostgreSQL and Redis test environment:

```bash
cp .env.example .env
python3 scripts/generate_master_key.py
docker compose --profile tools run --rm test
```

Do not commit the generated `.env` file or `docker/secrets/master.key`.

## Change requirements

- use the shared HTTP client factory for every external request;
- never pass secrets in Celery task arguments;
- never log tokens, API keys, proxy credentials, or sensitive HTTP request bodies;
- preserve model and task idempotency;
- add migrations for model changes;
- add tests for bug fixes and new contracts;
- keep source files below 300 lines unless responsibility cannot be split cleanly;
- keep public functions typed and documented.

## Pull requests

A pull request must include:

1. a description of the problem;
2. the selected solution;
3. affected architecture contracts;
4. unit and Docker test results;
5. migration and operational consequences;
6. a link to the relevant ADR when the architecture changes.

## Commits

Use Conventional Commits, for example:

```text
feat(monitoring): recover orphaned source posts
fix(telegram): preserve pending delivery after broker failure
test(security): verify encrypted values in PostgreSQL
```

## Contribution license

By submitting a contribution, you agree that it may be distributed as part of QuotaRadar under the `AGPL-3.0-only` license.
