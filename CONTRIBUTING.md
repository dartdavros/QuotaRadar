# Участие в разработке QuotaRadar

Спасибо за вклад в QuotaRadar.

## Перед началом

Ознакомьтесь с:

- `AGENTS.md`;
- `docs/ARCH-QUOTARADAR-0001-System-Architecture.md`;
- `docs/SPEC-QUOTARADAR-0001-Technical-Specification.md`;
- действующими ADR в `docs/`.

Изменения не должны скрыто нарушать архитектурные ограничения. Новое решение, противоречащее ARCH/SPEC/ADR, сначала оформляется отдельной ADR.

## Границы проекта

В текущий scope входят только:

- утверждённый allowlist: `@OpenAIDevs`, `@thsottiaux`, резервный `@sama` и `@ClaudeDevs`;
- официальный X API v2;
- автоматическая ИИ-классификация;
- Telegram-каналы и личные уведомления;
- единый обязательный proxy;
- Django Admin;
- Docker Compose.

RSS, scraping X, ручная модерация и источники вне утверждённого allowlist не добавляются без отдельного архитектурного решения.

## Локальная подготовка в PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Unit-тесты:

```powershell
python manage.py test --settings=quotaradar.test_settings
python manage.py makemigrations --check --dry-run --settings=quotaradar.test_settings
```

Полный PostgreSQL/Redis-контур:

```powershell
Copy-Item .env.example .env
python .\scripts\generate_master_key.py
docker compose --profile tools run --rm test
```

Не коммитьте созданные `.env` и `docker/secrets/master.key`.

## Требования к изменениям

- использовать общий HTTP client factory для всех внешних запросов;
- не передавать секреты в Celery task arguments;
- не логировать токены, API-ключи, proxy credentials и тела чувствительных HTTP-запросов;
- сохранять идемпотентность моделей и задач;
- добавлять миграции для изменений моделей;
- добавлять тесты для исправлений и новых контрактов;
- не создавать файлы исходного кода более 300 строк без обоснованного разделения ответственности;
- сохранять публичные функции типизированными и документированными.

## Pull request

Pull request должен содержать:

1. описание проблемы;
2. выбранное решение;
3. затронутые архитектурные контракты;
4. результаты unit- и Docker-тестов;
5. миграционные и эксплуатационные последствия;
6. ссылку на ADR, если решение меняет архитектуру.

## Коммиты

Используйте Conventional Commits, например:

```text
feat(monitoring): recover orphaned source posts
fix(telegram): preserve pending delivery after broker failure
test(security): verify encrypted values in PostgreSQL
```

## Лицензирование вклада

Отправляя вклад, вы соглашаетесь распространять его в составе QuotaRadar на условиях `AGPL-3.0-only`.
