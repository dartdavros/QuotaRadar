# ARCH-QUOTARADAR-0001 — Архитектура системы QuotaRadar

- **Статус:** утверждена и синхронизирована с реализацией
- **Версия:** 1.1
- **Дата:** 2026-07-20
- **Язык продукта:** русский

## 1. Назначение

QuotaRadar автоматически отслеживает новые публикации официальных X-аккаунтов:

- `@OpenAIDevs` — события, относящиеся к Codex;
- `@ClaudeDevs` — события, относящиеся к Claude Code.

Каждая новая публикация интерпретируется ИИ. Если публикация сообщает о сбросе квоты, повышении квоты или продлении повышенной квоты, QuotaRadar формирует краткое сообщение на русском языке, добавляет ссылку на исходный пост в X и автоматически доставляет уведомление в Telegram.

Ручная модерация не используется.

## 2. Пользовательские сценарии

### 2.1. Официальная инсталляция

Официальный экземпляр QuotaRadar публикует уведомления в настроенный Telegram-канал.

### 2.2. Самостоятельная инсталляция

Пользователь разворачивает собственный экземпляр QuotaRadar, создаёт Telegram-бота и получает уведомления в личные сообщения после команды `/start`.

Один экземпляр может одновременно отправлять сообщения в канал и в личные чаты подписчиков.

## 3. Технологический стек

- Django;
- Django Admin;
- PostgreSQL;
- Celery;
- Celery Beat;
- Redis;
- Telegram Bot API;
- X API v2;
- Docker;
- Docker Compose.

## 4. Контейнерная схема

Система разворачивается единым Docker Compose-контуром.

```text
init      — one-shot checks, миграции и static files
web       — Django Admin и служебный HTTP-процесс
bot       — Telegram long polling и команды пользователей
worker    — Celery Worker
beat      — Celery Beat
test      — PostgreSQL/Redis integration tests в профиле tools
postgres  — PostgreSQL
redis     — persistent Celery broker, result backend и distributed locks
```

Контейнеры `init`, `web`, `bot`, `worker`, `beat` и `test` используют один Docker-образ Django-приложения и одну кодовую базу. Runtime-процессы стартуют только после healthcheck PostgreSQL/Redis и успешного завершения `init`. Результат `collectstatic` передаётся `web` через общий named volume `static_data`.

## 5. Общая схема взаимодействия

```text
                     Django Admin
                          │
                          ▼
                    PostgreSQL
                          ▲
                          │
X API ── proxy ──► Celery Worker ◄── Celery Beat
                          │
                          ├── proxy ──► ИИ-провайдер
                          │
                          └── proxy ──► Telegram Bot API
                                           │
                                  ┌────────┴────────┐
                                  ▼                 ▼
                           Telegram-канал    Личные сообщения
```

Все внешние HTTP/HTTPS-запросы проходят через настроенный прокси:

- QuotaRadar → X API;
- QuotaRadar → ИИ-провайдер;
- QuotaRadar → Telegram Bot API.

Внутренние соединения Docker-сети через прокси не проходят:

- Django/Celery → PostgreSQL;
- Django/Celery → Redis.

## 6. Django-приложения

### 6.1. `configuration`

Хранит и предоставляет рабочую конфигурацию:

- включение мониторинга;
- интервал опроса X;
- ИИ-провайдер;
- базовый URL ИИ-провайдера;
- модель;
- параметры генерации;
- активный промпт;
- таймауты;
- количество повторных попыток;

Рабочие параметры редактируются через Django Admin и хранятся в PostgreSQL.

### 6.2. `secrets`

Управляет секретами:

- Telegram Bot Token;
- API-ключ ИИ-провайдера;
- X Bearer Token;
- строка подключения к HTTP/HTTPS-прокси.

Секреты:

- вводятся и просматриваются в Django Admin;
- хранятся в PostgreSQL только в зашифрованном виде;
- расшифровываются в приложении;
- доступны только пользователям Django с отдельным разрешением;
- не выводятся в логи;
- не передаются как аргументы Celery-задач.

Корневой ключ шифрования хранится вне PostgreSQL и монтируется в контейнеры приложения как Docker secret/file mount.

### 6.3. `sources`

Управляет X-источниками:

- `OpenAIDevs`;
- `ClaudeDevs`.

Для источника сохраняются X User ID, последний обработанный Post ID, время и результат последней проверки.

### 6.4. `monitoring`

Отвечает за:

- запросы к X API через прокси;
- ограниченную первичную загрузку постов отдельно для каждого источника;
- редактируемые через системную конфигурацию размеры первичной и регулярной выборки;
- получение новых постов через `since_id`;
- исключение репостов;
- сохранение новых постов;
- дедупликацию по X Post ID;
- передачу новых постов на ИИ-анализ.

### 6.5. `analysis`

Отвечает за:

- вызов настроенного ИИ-провайдера через прокси;
- структурированную классификацию публикации;
- формирование заголовка и текста на русском языке;
- валидацию ответа ИИ;
- сохранение результата анализа.

Поддерживаемые типы событий:

```text
quota_reset
quota_increase
quota_extension
```

### 6.6. `telegram`

Отвечает за:

- публикацию в Telegram-каналы;
- отправку в личные чаты;
- команды `/start`, `/stop`, `/status`;
- хранение получателей;
- журнал доставок и повторных попыток.

## 7. Основной поток обработки

```text
1. Celery Beat запускает проверку активных X-источников.
2. Worker запрашивает новые посты через X API и прокси.
3. Новые посты сохраняются в PostgreSQL.
4. Репосты игнорируются, ответы аккаунтов сохраняются и анализируются.
5. Каждый новый пост передаётся ИИ-провайдеру через прокси.
6. ИИ возвращает структурированный результат.
7. Нерелевантный пост сохраняется без отправки.
8. Для релевантного поста формируется сообщение на русском языке.
9. Приложение добавляет человеко-читаемую исходную дату публикации в настроенном часовом поясе и доверенную ссылку на пост в X.
10. Сообщение отправляется всем активным Telegram-получателям через прокси.
11. Результат каждой доставки сохраняется в PostgreSQL.
```

Ручной исторический импорт запускается отдельной Celery-задачей из Django Admin. Он использует `until_id`, получает ограниченную конфигурацией порцию постов старше самого старого сохранённого поста, не изменяет курсор регулярного polling и передаёт на анализ только новые записи. Повторный запуск продолжает движение вглубь истории.

## 8. Основные модели данных

### `SystemConfiguration`

Единая активная конфигурация приложения.

Основные поля:

- `monitoring_enabled`;
- `poll_interval_seconds`;
- `bootstrap_post_limit`;
- `regular_poll_post_limit`;
- `historical_backfill_post_limit`;
- `telegram_message_timezone`;
- `llm_provider`;
- `llm_base_url`;
- `llm_model`;
- `llm_temperature`;
- `llm_max_tokens`;
- `llm_timeout_seconds`;
- `retry_count`;
- `active_prompt`.

### `EncryptedSecret`

- `code`;
- `encrypted_value`;
- `key_version`;
- `updated_at`;
- `updated_by`.

Коды секретов:

```text
telegram_bot_token
llm_api_key
x_bearer_token
proxy_url
```

### `Source`

- `provider`;
- `username`;
- `x_user_id`;
- `enabled`;
- `last_post_id`;
- `last_checked_at`;
- `last_success_at`;
- `last_error`.

### `SourcePost`

- `source`;
- `external_id`;
- `text`;
- `source_url`;
- `published_at`;
- `received_at`;
- `raw_data`;
- `processing_status`;
- `processing_started_at`;
- `last_error`.

`external_id` уникален.

### `Analysis`

- `source_post`;
- `is_relevant`;
- `event_type`;
- `provider`;
- `product`;
- `title_ru`;
- `message_ru`;
- `model`;
- `prompt_version`;
- `raw_response`;
- `created_at`;
- `delivery_fanout_completed_at`.

### `DeliveryTarget`

- `target_type`: `channel` или `private_chat`;
- `telegram_chat_id`;
- `enabled`;
- `created_at`.

### `Delivery`

- `analysis`;
- `target`;
- `status`;
- `telegram_message_id`;
- `attempts`;
- `created_at`;
- `updated_at`;
- `last_attempt_at`;
- `next_attempt_at`;
- `sent_at`;
- `last_error`.

Для пары `analysis + target` действует уникальное ограничение.

## 9. Прокси

Прокси является обязательной общей инфраструктурной зависимостью внешних интеграций.

Строка подключения хранится как зашифрованный секрет `proxy_url` и может иметь вид:

```text
http://user:password@host:port
https://user:password@host:port
```

Доступ к прокси централизован через общий HTTP client factory. Интеграции не создают собственную независимую конфигурацию прокси и не имеют режима прямого внешнего подключения. При отсутствии корректного `proxy_url` мониторинг, ИИ-анализ и Telegram-доставка не запускаются.

## 10. Шифрование секретов

Шифрование выполняется на уровне Django с использованием аутентифицированного симметричного шифрования из библиотеки `cryptography`.

Требования:

- ciphertext хранится в PostgreSQL;
- master key хранится вне базы;
- поддерживается версия ключа;
- секреты отображаются в Django Admin только пользователю с отдельным permission;
- секреты маскируются в логах, трассировках и сообщениях об ошибках.

## 11. Надёжность

- уникальность X Post ID предотвращает создание повторного `SourcePost`;
- one-to-one `SourcePost → Analysis` предотвращает создание повторного анализа;
- уникальность `analysis + target` предотвращает создание повторного журнала доставки;
- статусы `sent` и `failed` не отправляются автоматически повторно; `failed` может быть явно возвращён оператором в очередь через Django Admin, а `sent` повторно не ставится;
- polling источника, анализ поста и отправка доставки защищаются Redis-lock;
- временные ошибки X, Telegram и ИИ обрабатываются Celery retry;
- `429` X обрабатывается с учётом `x-rate-limit-reset`;
- ошибка одного Telegram-получателя не блокирует остальных;
- Redis использует named volume и AOF;
- Celery использует late acknowledgement, reject on worker lost и visibility timeout;
- создание `Delivery` для релевантного `Analysis` завершается транзакционным маркером `delivery_fanout_completed_at`;
- Celery Beat сначала завершает потерянный fan-out релевантных анализов, затем восстанавливает устаревшие `queued` посты и `pending` доставки по данным PostgreSQL, соблюдая `next_attempt_at`;
- точные thresholds и статусная модель определены в `ADR-QUOTARADAR-0002`.

Telegram Bot API не предоставляет idempotency key для `sendMessage`. Поэтому после сохранённого `sent` повторная отправка исключается, но при аварии между принятием сообщения Telegram и фиксацией результата в PostgreSQL теоретически возможен дубль. Абсолютная exactly-once гарантия не заявляется.

## 12. Границы системы

В текущую архитектуру входят:

- `@OpenAIDevs` и `@ClaudeDevs`;
- официальный X API v2;
- ИИ-интерпретация;
- автоматическая публикация без модерации;
- русскоязычные сообщения со ссылкой на источник;
- Telegram-каналы и личные сообщения;
- Django Admin;
- зашифрованные и видимые в админке секреты;
- единый прокси для X, Telegram и ИИ;
- Docker Compose;
- PostgreSQL, Celery и persistent Redis;
- GitHub Actions CI;
- структурированные JSON-логи;
- reconciliation потерянных задач согласно ADR-0002.

Не входят:

- RSS;
- scraping X;
- другие аккаунты и продукты;
- ручная модерация;
- публичный веб-интерфейс;
- платные подписки;
- пользовательские фильтры;
- отдельные микросервисы.
