<p align="center">
  <a href="https://t.me/quotaradar">
    <img src="docs/assets/cover.jpg" alt="QuotaRadar — Codex and Claude Code quota alerts" width="100%">
  </a>
</p>

<p align="center">
  <a href="https://t.me/quotaradar"><strong>📡 Follow @quotaradar on Telegram for live Codex and Claude Code quota alerts</strong></a>
</p>

# QuotaRadar

QuotaRadar automatically monitors trusted OpenAI and Anthropic sources on X, uses an LLM to identify quota changes affecting Codex and Claude Code users at scale, and publishes Russian-language alerts to Telegram. Codex sources include `@OpenAIDevs`, `@thsottiaux`, and the fallback source `@sama`; Claude Code uses `@ClaudeDevs`.

Supported events:

- quota resets;
- quota increases;
- extensions of temporarily increased quotas.

The system operates without manual moderation. Every published Telegram message includes the original publication date and a link to the source post on X.

## Features

- official X API v2 integration without scraping or RSS;
- one mandatory HTTP/HTTPS proxy for X, the LLM provider, and Telegram;
- OpenAI-compatible LLM adapter with structured output;
- Telegram channel delivery and personal notifications through `/start`, `/stop`, and `/status`;
- administration through Django Admin;
- safe manual import of older publications without resetting the live polling cursor;
- encrypted storage of tokens, API keys, and the proxy URL in PostgreSQL;
- Celery, Redis locks, retries, and recovery of orphaned work;
- JSON logs without external request bodies or secrets;
- Docker Compose and GitHub Actions CI.

## Architecture

```text
                         Django Admin
                              │
                              ▼
                        PostgreSQL
                              ▲
                              │
X API ── mandatory proxy ─────► Celery Worker ◄── Celery Beat
                              │
                              ├── mandatory proxy ──► LLM
                              │
                              └── mandatory proxy ──► Telegram Bot API
                                                         │
                                                ┌────────┴────────┐
                                                ▼                 ▼
                                         Telegram channel   Personal chats
```

Docker Compose includes the following services:

- `init` — validation, migrations, and static file collection;
- `web` — Django Admin;
- `bot` — Telegram long polling;
- `worker` — Celery Worker;
- `beat` — Celery Beat;
- `postgres` — primary database;
- `redis` — Celery broker, result backend, and distributed locks;
- `static_data` — shared `collectstatic` output volume for `init` and `web`;
- `test` — PostgreSQL/Redis integration test environment under the `tools` profile.

Architecture and implementation details are documented in:

- `docs/ARCH-QUOTARADAR-0001-System-Architecture.md`;
- `docs/SPEC-QUOTARADAR-0001-Technical-Specification.md`;
- `docs/PLAN-QUOTARADAR-0001-Implementation-Plan.md`;
- `docs/ADR-QUOTARADAR-0002-Recovery-of-Orphaned-Work.md`;
- `docs/ADR-QUOTARADAR-0003-Trusted-Codex-Sources.md`.

## Requirements

A self-hosted installation requires:

- a Linux server with Docker Engine and Docker Compose v2;
- X API v2 access for reading user publications;
- a Telegram bot;
- an OpenAI-compatible LLM provider supporting `response_format=json_schema`;
- an HTTP or HTTPS proxy that can reach X, the LLM provider, and Telegram;
- Python 3 for generating bootstrap secrets.

QuotaRadar does not make direct external requests when the mandatory proxy is not configured.

## Quick start

Run all commands from the project root on Linux.

### 1. Prepare `.env`

```bash
cp .env.example .env
```

Generate random values:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Use the first value as `DJANGO_SECRET_KEY` and the second as `POSTGRES_PASSWORD`.

Example `.env`:

```dotenv
DJANGO_SECRET_KEY=<long-random-value>
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<backend-ip-or-domain>
QUOTARADAR_WEB_BIND_ADDRESS=0.0.0.0
POSTGRES_DB=quotaradar
POSTGRES_USER=quotaradar
POSTGRES_PASSWORD=<long-random-password>
```

`DJANGO_ALLOWED_HOSTS` must include the address used to open Django Admin in a browser.

`QUOTARADAR_WEB_BIND_ADDRESS=0.0.0.0` publishes port `8000` on every interface of the backend host. Restrict access with a firewall, VPN, or reverse proxy. Release `0.1.0` does not include Nginx, TLS termination, or automated certificate management.

To expose Django Admin only on the backend host, use:

```dotenv
QUOTARADAR_WEB_BIND_ADDRESS=127.0.0.1
```

### 2. Create the master key

```bash
python3 scripts/generate_master_key.py
```

The command creates `docker/secrets/master.key`. The script does not overwrite an existing key.

The master key:

- must never be committed to Git;
- is mounted read-only into application containers;
- is required to decrypt every stored runtime secret;
- must be backed up separately from PostgreSQL.

Losing the master key makes stored tokens and API keys unrecoverable.

### 3. Build and start the stack

```bash
docker compose up -d --build
```

Check service state:

```bash
docker compose ps
docker compose logs --tail 100 init
docker compose logs --tail 100 web worker beat bot
```

Runtime services start only after `init` completes successfully and PostgreSQL and Redis pass their health checks.

### 4. Create an administrator

```bash
docker compose exec web python manage.py createsuperuser
```

Open:

```text
http://<backend-host>:8000/admin/
```

The admin requires two-factor authentication. On first login, after entering the
administrator username and password you will be prompted to set up a TOTP device:

1. scan the displayed QR code with an authenticator app
   (Google Authenticator, Aegis, 1Password, etc.);
2. enter the generated one-time code to confirm enrollment;
3. save the displayed backup tokens in a secure location — they are the only
   way to regain access if the authenticator device is lost.

Subsequent logins ask for the username, the password, and a fresh one-time code.
Backup tokens can be regenerated from the two-factor profile page after login.

### 5. Configure runtime settings

In Django Admin, open the QuotaRadar system configuration and set:

- `monitoring_enabled` — keep it disabled until diagnostics pass;
- `poll_interval_seconds` — use `300` seconds initially;
- `llm_provider` — `openai_compatible`;
- `llm_base_url` — the API prefix, for example `https://provider.example/v1`;
- `llm_model` — the provider model identifier;
- the remaining generation and retry parameters;
- the active prompt created by migrations.

QuotaRadar appends `/chat/completions` to the configured LLM base URL.

Create the following secrets in the **Secrets** section:

- `telegram_bot_token`;
- `llm_api_key`;
- `x_bearer_token`;
- `proxy_url`.

Supported proxy URL formats:

```text
http://user:password@host:port
https://user:password@host:port
```

Secret values are encrypted by the application before they are written to PostgreSQL.

### 6. Configure X

1. Create a project and application in the X Developer Console.
2. Obtain a Bearer Token with X API v2 access.
3. Confirm that the current X plan allows user lookup and user publication retrieval.
4. Store the token as `x_bearer_token` in Django Admin.

QuotaRadar uses the official endpoints:

```text
GET /2/users/by?usernames=<enabled_source_usernames>
GET /2/users/{user_id}/tweets
```

Endpoint pricing, limits, and availability are controlled by X and may change independently of QuotaRadar.

### 7. Configure the Telegram bot

1. Open the official `@BotFather` bot.
2. Run `/newbot` and store the issued token as `telegram_bot_token`.
3. For channel delivery, add the bot as a channel administrator with permission to publish messages.
4. In Django Admin, create a Telegram delivery target with:
   - target type `Channel`;
   - `@channel_username` or a numeric chat ID;
   - the target enabled.

For self-hosted personal notifications, users open the bot and run `/start`. Available commands:

- `/start` — enable notifications;
- `/stop` — disable notifications;
- `/status` — show the current subscription state.

### 8. Run diagnostics

Without an external request:

```bash
docker compose exec web python manage.py diagnose_configuration
```

With a proxy connectivity check:

```bash
docker compose exec web python manage.py diagnose_configuration --test-proxy
```

Before enabling monitoring, open **Sources** in Django Admin:

- `@OpenAIDevs` and `@ClaudeDevs` are enabled by default;
- enable `@thsottiaux` as the primary additional Codex source;
- keep `@sama` disabled unless the fallback source is required;
- before the first poll of a newly enabled source, set `bootstrap_post_limit`. Use `100` to retrieve the latest 100 publications.

The enabled column in the source table is read-only. Select source rows and use the existing bulk enable or disable actions to change their activity state.

Confirm that `quota_event_classifier v2` is selected as the active prompt, then enable monitoring. Trusted sources are created by migrations and cannot be added manually through Django Admin.

After a permanent Telegram delivery failure, correct the token, bot permissions, or delivery target. Then select the failed delivery records and run the retry bulk action. The attempt counter restarts. Deliveries already marked as sent cannot be queued again.

To retrieve older history, open **Sources**, select the required enabled trusted accounts, and run the historical backfill bulk action. The system configuration controls the number of posts retrieved per source. Backfill retrieves posts older than the oldest stored publication, does not change `last_post_id`, and queues only newly created records for analysis. Repeated runs continue deeper into history.

The original publication date is rendered before the source link using the Telegram date time zone configured in Django Admin. The default is `Europe/Moscow`.

## Operations

### Logs

```bash
docker compose logs -f --tail 200 web bot worker beat
```

Application logs use JSON. Primary correlation fields:

```text
task_id
source_id
source_post_id
x_post_id
analysis_id
delivery_target_id
delivery_id
status
error_type
```

External HTTP request and response bodies are not logged.

### Stop and restart

```bash
docker compose stop
docker compose start
```

### Update

Create a database and master key backup before updating, then run:

```bash
git pull
docker compose up -d --build --remove-orphans
docker compose ps
```

The `init` service applies new migrations before runtime processes start.

### Backup

Create a PostgreSQL dump inside the container and copy it to the host:

```bash
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/quotaradar.dump'
docker compose cp postgres:/tmp/quotaradar.dump ./backups/quotaradar.dump
cp docker/secrets/master.key ./backups/master.key
```

Store the dump and master key in secure storage. Never publish them in the repository.

### Remove containers

Without deleting data:

```bash
docker compose down
```

Delete PostgreSQL and Redis volumes as well:

```bash
docker compose down --volumes
```

The second command irreversibly deletes instance data.

## Tests

Run the complete Docker test environment with PostgreSQL and Redis:

```bash
docker compose --profile tools run --rm test
```

Check for missing migrations:

```bash
docker compose --profile tools run --rm test python manage.py makemigrations --check --dry-run
```

Run local unit tests with SQLite:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py test --settings=quotaradar.test_settings
```

PostgreSQL/Redis integration tests are skipped in the SQLite environment and run in Docker CI.

## Delivery reliability

- unique X post IDs prevent duplicate source publications;
- the one-to-one `SourcePost → Analysis` relation prevents duplicate analysis;
- the unique `analysis + target` constraint creates one delivery journal entry per recipient;
- Redis locks prevent concurrent analysis of the same post and concurrent delivery of the same record;
- Redis uses a persistent volume and AOF;
- delivery fan-out for relevant analyses is protected by a transactional marker;
- Celery Beat recovers incomplete fan-out, stale `queued` posts, and stale `pending` deliveries, while respecting the stored `next_attempt_at` value.

Telegram Bot API does not provide an idempotency key for `sendMessage`. If Telegram accepts a message but the process exits before `telegram_message_id` is stored in PostgreSQL, a retry can theoretically create a duplicate. No retry occurs after the acknowledgement has been persisted.

## Security

- do not expose Django Admin to the public internet without a firewall, VPN, or correctly configured HTTPS reverse proxy;
- do not store `.env`, `docker/secrets/master.key`, database dumps, or real tokens in Git or the Docker image;
- grant permissions to view or change secrets only to trusted administrators;
- scan the complete Git history for secrets before publishing the repository;
- follow the vulnerability reporting process in `SECURITY.md`.

## GitHub Actions

The `.github/workflows/ci.yml` workflow automatically:

- creates disposable CI bootstrap values;
- generates a disposable master key;
- validates Docker Compose;
- builds the image;
- checks migrations;
- runs the complete PostgreSQL and Redis test suite.

Basic CI does not require repository secrets. Place the project in a GitHub repository with a `main` branch and enable GitHub Actions.

Publishing an image to GHCR and automated server deployment are outside the scope of release `0.1.0`.

## License

QuotaRadar is distributed under the `AGPL-3.0-only` license. See `LICENSE` for the complete text.

Copyright © 2026 EDEVS LLC.
