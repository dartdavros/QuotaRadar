# Security Policy

## Supported versions

Until the next stable release is available, security fixes are provided for the current `0.1.x` branch.

## Reporting a vulnerability

Do not disclose vulnerability details in a public issue.

Use private vulnerability reporting or a Security Advisory in the GitHub repository. Include:

- the affected version or commit;
- the exploitation scenario;
- the expected impact;
- minimal reproduction steps;
- a possible fix, when known.

Do not disclose tokens, API keys, the master key, proxy credentials, database dumps, or personal Telegram chat IDs before a fix is published.

## Critical secrets

The following data must never be committed, attached to an issue, or included in logs:

- `.env`;
- `docker/secrets/master.key`;
- `telegram_bot_token`;
- `x_bearer_token`;
- `llm_api_key`;
- `proxy_url` containing credentials;
- PostgreSQL dumps;
- master key backups.

The master key cannot be recovered from PostgreSQL. Compromise of both the master key and a database dump exposes the stored secrets. The real key must be excluded from both Git and the Docker build context.

## Django Admin deployment

Port `8000` may be published on the backend host. Operators must restrict access with a firewall or VPN, or place a correctly configured HTTPS reverse proxy in front of the application.

QuotaRadar `0.1.0` does not include Nginx, TLS termination, rate limiting, or automated certificate issuance.

## External dependencies

All X, LLM, and Telegram requests must use the shared proxy-aware HTTP client factory. Any integration that creates a direct external HTTP client violates the security boundary.
