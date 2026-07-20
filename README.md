# QuotaRadar

QuotaRadar автоматически отслеживает публикации официальных X-аккаунтов `@OpenAIDevs` и `@ClaudeDevs`, определяет массовые изменения квот Codex и Claude Code с помощью ИИ и отправляет уведомления на русском языке в Telegram.

Поддерживаемые события:

- сброс квоты;
- повышение квоты;
- продление повышенной квоты.

Система работает без ручной модерации. Каждый опубликованный Telegram-текст содержит ссылку на исходную публикацию в X.

## Возможности

- официальный X API v2 без scraping и RSS;
- единый обязательный HTTP/HTTPS proxy для X, ИИ-провайдера и Telegram;
- OpenAI-compatible LLM adapter со structured output;
- Telegram-каналы и личные уведомления через `/start`, `/stop`, `/status`;
- управление через Django Admin;
- зашифрованное хранение токенов, API-ключей и proxy URL в PostgreSQL;
- Celery, Redis locks, retries и восстановление потерянных задач;
- JSON-логи без тел внешних запросов и секретов;
- Docker Compose и GitHub Actions CI.

## Архитектура

```text
                         Django Admin
                              │
                              ▼
                        PostgreSQL
                              ▲
                              │
X API ── обязательный proxy ──► Celery Worker ◄── Celery Beat
                              │
                              ├── обязательный proxy ──► LLM
                              │
                              └── обязательный proxy ──► Telegram Bot API
                                                         │
                                                ┌────────┴────────┐
                                                ▼                 ▼
                                         Telegram-канал    Личные чаты
```

Docker Compose содержит сервисы:

- `init` — проверки, миграции и сборка static files;
- `web` — Django Admin;
- `bot` — Telegram long polling;
- `worker` — Celery Worker;
- `beat` — Celery Beat;
- `postgres` — основная база данных;
- `redis` — Celery broker, result backend и distributed locks;
- `static_data` — общий volume результатов `collectstatic` для `init` и `web`;
- `test` — интеграционный тестовый контур в профиле `tools`.

Подробности зафиксированы в документах:

- `docs/ARCH-QUOTARADAR-0001-System-Architecture.md`;
- `docs/SPEC-QUOTARADAR-0001-Technical-Specification.md`;
- `docs/PLAN-QUOTARADAR-0001-Implementation-Plan.md`;
- `docs/ADR-QUOTARADAR-0002-Recovery-of-Orphaned-Work.md`.

## Требования

Для самостоятельной установки нужны:

- Linux-сервер с Docker Engine и Docker Compose v2;
- доступ к X API v2 для чтения публикаций пользователей;
- Telegram-бот;
- OpenAI-compatible ИИ-провайдер с поддержкой `response_format=json_schema`;
- HTTP или HTTPS proxy, через который доступны X, ИИ-провайдер и Telegram;
- локально на Windows: PowerShell и Python 3 для генерации bootstrap-ключей.

QuotaRadar не выполняет прямые внешние запросы без настроенного proxy.

## Быстрый запуск

### 1. Подготовить `.env`

В PowerShell из корня проекта:

```powershell
Copy-Item .env.example .env
```

Сгенерировать значения:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Первое значение укажите как `DJANGO_SECRET_KEY`, второе — как `POSTGRES_PASSWORD`.

Пример `.env`:

```dotenv
DJANGO_SECRET_KEY=<длинное случайное значение>
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<IP-или-домен-backend>
QUOTARADAR_WEB_BIND_ADDRESS=0.0.0.0
POSTGRES_DB=quotaradar
POSTGRES_USER=quotaradar
POSTGRES_PASSWORD=<длинный случайный пароль>
```

`DJANGO_ALLOWED_HOSTS` должен содержать адрес, по которому браузер открывает Django Admin.

`QUOTARADAR_WEB_BIND_ADDRESS=0.0.0.0` публикует порт `8000` на всех интерфейсах backend-хоста. Ограничьте доступ firewall, VPN или reverse proxy. В релиз `0.1.0` не входят Nginx, TLS и автоматическое управление сертификатами.

Для доступа только с backend-хоста используйте:

```dotenv
QUOTARADAR_WEB_BIND_ADDRESS=127.0.0.1
```

### 2. Создать master key

```powershell
python .\scripts\generate_master_key.py
```

Команда создаёт `docker/secrets/master.key`. Скрипт не перезаписывает существующий ключ.

Файл master key:

- не должен попадать в Git;
- монтируется в прикладные контейнеры read-only;
- нужен для расшифровки всех рабочих секретов;
- должен резервироваться отдельно от PostgreSQL.

Потеря master key делает сохранённые токены и API-ключи нерасшифровываемыми.

### 3. Собрать и запустить

```powershell
docker compose up -d --build
```

Проверить состояние:

```powershell
docker compose ps
docker compose logs --tail 100 init
docker compose logs --tail 100 web worker beat bot
```

Runtime-сервисы запускаются только после успешного завершения `init` и healthcheck PostgreSQL/Redis.

### 4. Создать администратора

```powershell
docker compose exec web python manage.py createsuperuser
```

Открыть:

```text
http://<backend-host>:8000/admin/
```

### 5. Настроить рабочие параметры

В Django Admin заполните **Системную конфигурацию QuotaRadar**:

- `Мониторинг включён` — пока оставьте выключенным;
- `Интервал опроса` — начальное значение `300` секунд;
- `Код ИИ-провайдера` — `openai_compatible`;
- `Базовый URL ИИ-провайдера` — URL до API-префикса, например `https://provider.example/v1`;
- `Модель` — идентификатор модели провайдера;
- остальные параметры генерации и retry;
- активный промпт — создан миграцией.

QuotaRadar добавляет `/chat/completions` к указанному базовому URL.

В разделе **Секреты** задайте:

- `telegram_bot_token`;
- `llm_api_key`;
- `x_bearer_token`;
- `proxy_url`.

Поддерживаемые схемы proxy:

```text
http://user:password@host:port
https://user:password@host:port
```

Реальные значения шифруются приложением до записи в PostgreSQL.

### 6. Настроить X

1. Создайте проект и приложение в X Developer Console.
2. Получите Bearer Token с доступом к X API v2.
3. Убедитесь, что текущий тариф/план разрешает user lookup и чтение публикаций пользователя.
4. Сохраните токен в `x_bearer_token` через Django Admin.

QuotaRadar использует официальные endpoints:

```text
GET /2/users/by?usernames=OpenAIDevs,ClaudeDevs
GET /2/users/{user_id}/tweets
```

Стоимость, лимиты и доступность endpoints определяются X и могут меняться независимо от QuotaRadar.

### 7. Настроить Telegram-бота

1. Откройте официальный `@BotFather`.
2. Выполните `/newbot` и сохраните выданный token в `telegram_bot_token`.
3. Для канала добавьте бота администратором с правом публикации сообщений.
4. В Django Admin создайте **Получателя Telegram**:
   - тип `Канал`;
   - `@channel_username` либо числовой chat ID;
   - `Активен`.

Для self-hosted личных уведомлений пользователь открывает бота и выполняет `/start`. Команды:

- `/start` — включить уведомления;
- `/stop` — отключить уведомления;
- `/status` — показать состояние подписки.

### 8. Выполнить диагностику

Без внешнего запроса:

```powershell
docker compose exec web python manage.py diagnose_configuration
```

С проверкой proxy:

```powershell
docker compose exec web python manage.py diagnose_configuration --test-proxy
```

После успешной диагностики включите мониторинг в Django Admin.

## Эксплуатация

### Логи

```powershell
docker compose logs -f --tail 200 web bot worker beat
```

Прикладные логи выводятся в JSON. Основные correlation fields:

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

Тела внешних HTTP-запросов и ответов не логируются.

### Остановка и повторный запуск

```powershell
docker compose stop
docker compose start
```

### Обновление

Перед обновлением создайте резервную копию базы и master key, затем:

```powershell
git pull
docker compose up -d --build --remove-orphans
docker compose ps
```

Сервис `init` применит новые миграции до запуска runtime-процессов.

### Резервное копирование

Создать PostgreSQL dump внутри контейнера и скопировать на хост:

```powershell
New-Item -ItemType Directory -Force .\backups | Out-Null
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/quotaradar.dump'
docker compose cp postgres:/tmp/quotaradar.dump .\backups\quotaradar.dump
Copy-Item .\docker\secrets\master.key .\backups\master.key
```

Храните dump и master key в защищённом хранилище. Не публикуйте их в репозитории.

### Удаление контейнеров

Без удаления данных:

```powershell
docker compose down
```

С удалением PostgreSQL и Redis volumes:

```powershell
docker compose down --volumes
```

Вторая команда необратимо удаляет данные экземпляра.

## Тесты

Полный Docker-контур с реальными PostgreSQL и Redis:

```powershell
docker compose --profile tools run --rm test
```

Проверка миграций:

```powershell
docker compose --profile tools run --rm test python manage.py makemigrations --check --dry-run
```

Локальные unit-тесты без Docker используют SQLite:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py test --settings=quotaradar.test_settings
```

Интеграционные тесты PostgreSQL/Redis в SQLite-контуре корректно пропускаются и выполняются в Docker CI.

## Надёжность доставки

- уникальность X Post ID предотвращает создание дублирующихся постов;
- one-to-one `SourcePost → Analysis` предотвращает повторный анализ;
- уникальность `analysis + target` создаёт один журнал доставки на получателя;
- Redis locks предотвращают параллельный анализ одного поста и параллельную доставку одной записи;
- Redis использует persistent volume и AOF;
- создание доставок для релевантного анализа фиксируется транзакционным маркером fan-out;
- Celery Beat восстанавливает незавершённый fan-out, устаревшие `queued` посты и `pending` доставки, но не раньше сохранённого `next_attempt_at`.

Telegram Bot API не предоставляет idempotency key для `sendMessage`. Если Telegram принял сообщение, а процесс завершился до фиксации `telegram_message_id` в PostgreSQL, повторная попытка теоретически может создать дубль. После сохранённого подтверждения повторная отправка не выполняется.

## Безопасность

- не размещайте Django Admin в открытом интернете без firewall/VPN либо HTTPS reverse proxy;
- не храните `.env`, `docker/secrets/master.key`, дампы и реальные токены в Git или Docker image;
- выдавайте permissions просмотра и изменения секретов только доверенным администраторам;
- перед публикацией репозитория проверьте всю Git-историю на секреты;
- порядок сообщения об уязвимости описан в `SECURITY.md`.

## GitHub Actions

Workflow `.github/workflows/ci.yml` автоматически:

- создаёт одноразовые CI bootstrap-значения;
- генерирует одноразовый master key;
- валидирует Docker Compose;
- собирает образ;
- проверяет миграции;
- запускает полный набор тестов с PostgreSQL и Redis.

Для базового CI repository secrets не нужны. Достаточно разместить проект в GitHub-репозитории с веткой `main` и разрешёнными GitHub Actions.

Публикация образа в GHCR и автоматический deploy на сервер в версию `0.1.0` не входят.

## Лицензия

QuotaRadar распространяется по лицензии `AGPL-3.0-only`. Полный текст находится в `LICENSE`.

Copyright © 2026 ООО «ЭДЕВС».
