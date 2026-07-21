# SPEC-QUOTARADAR-0001 — Техническая спецификация QuotaRadar

- **Статус:** утверждена и синхронизирована с реализацией
- **Версия:** 1.1
- **Дата:** 2026-07-20
- **Связанный документ:** `ARCH-QUOTARADAR-0001-System-Architecture.md`

## 1. Цель

Реализовать open-source систему QuotaRadar, которая автоматически отслеживает публикации `@OpenAIDevs` и `@ClaudeDevs` в X, определяет через ИИ сообщения о сбросе, повышении или продлении повышенной квоты Codex/Claude Code и отправляет русскоязычные уведомления со ссылкой на источник в Telegram.

## 2. Термины

- **Источник** — официальный X-аккаунт `@OpenAIDevs` или `@ClaudeDevs`.
- **Пост** — публикация X, полученная через X API v2.
- **Релевантное событие** — сброс квоты, повышение квоты или продление повышенной квоты Codex/Claude Code.
- **Получатель** — Telegram-канал или личный Telegram-чат.
- **Прокси** — единая строка подключения для всех внешних HTTP/HTTPS-запросов.

## 3. Функциональные требования

### FR-001. Мониторинг источников

Система должна периодически проверять:

- `OpenAIDevs`;
- `ClaudeDevs`.

Список источников хранится в PostgreSQL и управляется через Django Admin.

### FR-002. Получение данных через официальный X API

Система должна использовать X API v2 и App-Only Bearer Token.

Для получения X User ID используется:

```http
GET https://api.x.com/2/users/by?usernames=OpenAIDevs,ClaudeDevs
Authorization: Bearer <x_bearer_token>
```

Для получения публикаций используется:

```http
GET https://api.x.com/2/users/{user_id}/tweets
Authorization: Bearer <x_bearer_token>
```

Общие обязательные параметры:

```text
exclude=retweets
tweet.fields=id,text,created_at,author_id,entities,referenced_tweets,note_tweet,article,attachments,edit_history_tweet_ids,in_reply_to_user_id
expansions=referenced_tweets.id,referenced_tweets.id.author_id,attachments.media_keys
media.fields=media_key,type,url,preview_image_url,alt_text
```

Параметры зависят от режима polling:

```text
Первичная загрузка источника:
since_id не передаётся
max_results=<bootstrap_post_limit>, по умолчанию 10
получается только первая страница

Последующие проверки:
since_id=<last_post_id>
max_results=<regular_poll_post_limit>, по умолчанию 5
при наличии next_token получаются все страницы
```

Ответы аккаунтов не исключаются и передаются на ИИ-анализ.

### FR-003. Инкрементальный polling

- Для каждого источника хранится `last_post_id`.
- Если у конкретного источника отсутствуют и `last_post_id`, и сохранённые `SourcePost`, система получает одну страницу последних постов. Размер страницы задаётся `bootstrap_post_limit`, значение по умолчанию — 10.
- Если `last_post_id` отсутствует, но посты источника уже сохранены, курсор восстанавливается из последнего сохранённого Post ID.
- При последующих запросах используется `since_id`.
- Размер страницы последующего polling задаётся `regular_poll_post_limit`, значение по умолчанию — 5, минимально допустимое значение X API.
- Если ответ содержит `next_token`, система должна получить все страницы.
- Посты обрабатываются от старого к новому.
- `last_post_id` обновляется только после успешного сохранения всех полученных постов.

Начальный интервал опроса: **5 минут**, редактируется через Django Admin.

### FR-004. Дедупликация

- `SourcePost.external_id` должен быть уникальным.
- Повторно полученный X Post ID не должен повторно анализироваться.
- Параллельный опрос одного источника блокируется Redis-lock.

### FR-005. Нормализация поста

Перед ИИ-анализом система формирует единый текстовый контекст из:

- `text`;
- полного текста `note_tweet`, если присутствует;
- текста `article`, если присутствует;
- текста процитированного поста из `referenced_tweets`, если присутствует;
- раскрытых URL из `entities`;
- alt text медиа, если присутствует.

Изображения и видео не передаются мультимодальной модели в версии 1.0.

### FR-006. ИИ-анализ

ИИ получает:

- источник;
- продукт, ожидаемый для источника;
- нормализованный текст;
- дату публикации;
- ссылку на пост.

ИИ должен вернуть структурированный JSON:

```json
{
  "is_relevant": true,
  "event_type": "quota_increase",
  "provider": "openai",
  "product": "codex",
  "title_ru": "Codex: повышены лимиты",
  "message_ru": "OpenAI временно увеличила лимиты Codex на 50%."
}
```

Допустимые значения:

```text
event_type: quota_reset | quota_increase | quota_extension
provider: openai | anthropic
product: codex | claude_code
```

Для нерелевантной публикации:

```json
{
  "is_relevant": false,
  "event_type": null,
  "provider": "openai",
  "product": "codex",
  "title_ru": null,
  "message_ru": null
}
```

### FR-007. Валидация ответа ИИ

- Ответ должен соответствовать серверной схеме.
- При невалидном ответе выполняются повторные попытки согласно конфигурации.
- Невалидный ответ не публикуется.
- Ссылка на источник не доверяется ИИ и добавляется приложением.

### FR-008. Формирование Telegram-сообщения

Сообщение формируется на русском языке.

Шаблон:

```text
{title_ru}

{message_ru}

Источник: {source_url}
```

Обязательные свойства:

- русский язык;
- краткость;
- сохранение чисел, процентов, тарифов и дат из исходного поста;
- отсутствие неподтверждённых фактов;
- обязательная ссылка на исходный пост X.

### FR-009. Telegram-канал

Администратор может создать активный `DeliveryTarget` типа `channel` через Django Admin.

Бот должен быть администратором канала и иметь право публикации сообщений.

### FR-010. Личные уведомления

Telegram-бот должен поддерживать long polling через `getUpdates` и команды:

- `/start` — создать или активировать `DeliveryTarget` типа `private_chat`;
- `/stop` — отключить личные уведомления;
- `/status` — показать текущее состояние подписки.

### FR-011. Доставка

- Релевантное событие отправляется всем активным получателям.
- Для каждого получателя создаётся одна запись `Delivery`.
- Уникальное ограничение `analysis + target` запрещает создание второго журнала доставки.
- Статус `sent` запрещает повторную отправку после подтверждённого и сохранённого результата.
- Redis-lock защищает одну запись `Delivery` от штатной параллельной отправки.
- Ошибка одного получателя не блокирует остальные доставки.
- При неопределённом исходе `sendMessage` возможна повторная попытка: Telegram Bot API не предоставляет idempotency key, поэтому абсолютная exactly-once гарантия не заявляется.

### FR-012. Django Admin

Django Admin должен позволять:

- включать и отключать мониторинг;
- менять интервал polling и размеры первичной и регулярной выборки X;
- управлять источниками;
- настраивать ИИ-провайдера и модель;
- редактировать промпт;
- настраивать прокси;
- вводить и просматривать расшифрованные секреты;
- управлять Telegram-каналами;
- просматривать посты, анализы и доставки;
- массово возвращать посты со статусом `failed` в очередь анализа;
- видеть последнюю ошибку каждой интеграции.

## 4. Прокси

### PRX-001. Единая конфигурация

Система использует один секрет `proxy_url` для всех внешних интеграций.

Через прокси должны выполняться:

```text
QuotaRadar → api.x.com
QuotaRadar → Telegram Bot API
QuotaRadar → ИИ-провайдер
```

### PRX-002. Централизованное применение

Прокси применяется через общий HTTP client factory. Интеграционные клиенты не должны самостоятельно читать или переопределять строку подключения.

### PRX-003. Обязательность

Прямые внешние запросы запрещены. При отсутствии корректного `proxy_url` задачи мониторинга, ИИ-анализа и Telegram-доставки должны завершаться конфигурационной ошибкой без попытки прямого подключения.

### PRX-004. Защита строки подключения

`proxy_url`:

- хранится зашифрованно;
- отображается только пользователю с permission просмотра секретов;
- не выводится в логах и ошибках;
- маскируется при диагностике соединения.

## 5. Секреты

### SEC-001. Перечень

```text
telegram_bot_token
llm_api_key
x_bearer_token
proxy_url
```

### SEC-002. Хранение

- Секреты хранятся в PostgreSQL как ciphertext.
- Шифрование и расшифровка выполняются Django-приложением.
- Master key не хранится в PostgreSQL.
- Master key монтируется в `web`, `bot`, `worker`, `beat` как Docker secret/file.

### SEC-003. Алгоритм

Используется аутентифицированное симметричное шифрование библиотеки `cryptography` с поддержкой ротации ключей и поля `key_version`.

### SEC-004. Django Admin

- Секреты должны быть видны в расшифрованном виде пользователю с отдельным permission.
- Доступ к просмотру и изменению секретов разделяется permissions.
- Изменения фиксируются через `updated_at` и `updated_by`.

### SEC-005. Логи

Секреты запрещено включать в:

- application logs;
- Celery task arguments;
- exception messages;
- health-check responses;
- Django messages;
- raw HTTP request dumps.

## 6. Модель данных

### 6.1. `SystemConfiguration`

| Поле | Тип | Требование |
|---|---|---|
| `monitoring_enabled` | bool | Глобальное включение мониторинга |
| `poll_interval_seconds` | positive int | По умолчанию 300 |
| `bootstrap_post_limit` | int 5..100 | Постов в первой странице bootstrap, по умолчанию 10 |
| `regular_poll_post_limit` | int 5..100 | Размер страницы регулярного polling, по умолчанию 5 |
| `llm_provider` | string | Код адаптера провайдера |
| `llm_base_url` | URL | Endpoint провайдера |
| `llm_model` | string | Имя модели |
| `llm_temperature` | decimal | Параметр модели |
| `llm_max_tokens` | positive int | Максимальный ответ |
| `llm_timeout_seconds` | positive int | Таймаут запроса |
| `retry_count` | non-negative int | Число повторов |
| `active_prompt_id` | FK | Активная версия промпта |

Должна существовать одна активная конфигурация.

### 6.2. `PromptTemplate`

| Поле | Тип |
|---|---|
| `code` | string |
| `version` | positive int |
| `system_prompt` | text |
| `user_prompt_template` | text |
| `is_active` | bool |
| `created_at` | datetime |

Уникальность: `code + version`.

### 6.3. `EncryptedSecret`

| Поле | Тип |
|---|---|
| `code` | unique string |
| `encrypted_value` | binary/text |
| `key_version` | string |
| `updated_at` | datetime |
| `updated_by` | FK User |

### 6.4. `Source`

| Поле | Тип |
|---|---|
| `provider` | enum |
| `username` | unique string |
| `x_user_id` | nullable string |
| `enabled` | bool |
| `last_post_id` | nullable string |
| `last_checked_at` | nullable datetime |
| `last_success_at` | nullable datetime |
| `last_error` | text |

Начальные записи:

```text
openai / OpenAIDevs
anthropic / ClaudeDevs
```

### 6.5. `SourcePost`

| Поле | Тип |
|---|---|
| `source` | FK Source |
| `external_id` | unique string |
| `text` | text |
| `normalized_text` | text |
| `source_url` | URL |
| `published_at` | datetime |
| `received_at` | datetime |
| `raw_data` | JSON |
| `processing_status` | enum |
| `processing_started_at` | nullable datetime |
| `last_error` | text |

Статусы:

```text
received
queued
analyzed_irrelevant
analyzed_relevant
failed
```

### 6.6. `Analysis`

| Поле | Тип |
|---|---|
| `source_post` | one-to-one SourcePost |
| `is_relevant` | bool |
| `event_type` | nullable enum |
| `provider` | enum |
| `product` | enum |
| `title_ru` | nullable string |
| `message_ru` | nullable text |
| `model` | string |
| `prompt_version` | positive int |
| `raw_response` | JSON/text |
| `created_at` | datetime |
| `delivery_fanout_completed_at` | nullable datetime |

### 6.7. `DeliveryTarget`

| Поле | Тип |
|---|---|
| `target_type` | channel/private_chat |
| `telegram_chat_id` | unique string |
| `enabled` | bool |
| `created_at` | datetime |
| `updated_at` | datetime |

### 6.8. `Delivery`

| Поле | Тип |
|---|---|
| `analysis` | FK Analysis |
| `target` | FK DeliveryTarget |
| `status` | enum |
| `telegram_message_id` | nullable string |
| `attempts` | non-negative int |
| `created_at` | datetime |
| `updated_at` | datetime |
| `last_attempt_at` | nullable datetime |
| `next_attempt_at` | nullable datetime |
| `sent_at` | nullable datetime |
| `last_error` | text |

Уникальность: `analysis + target`.

Статусы:

```text
pending
sent
failed
```

## 7. Celery-задачи

### `poll_sources`

Периодическая задача Celery Beat. Создаёт отдельную задачу для каждого активного источника.

### `poll_source(source_id)`

- получает Redis-lock;
- запрашивает X API;
- сохраняет новые посты;
- обновляет состояние источника;
- ставит новые посты в очередь анализа.

### `analyze_post(source_post_id)`

- получает Redis-lock для одного поста;
- нормализует контент;
- вызывает ИИ через прокси;
- валидирует JSON;
- создаёт единственный `Analysis`;
- при релевантности транзакционно создаёт `Delivery` для всех активных targets и фиксирует `delivery_fanout_completed_at`;
- публикует задачи доставки только после commit транзакции;
- очищает `processing_started_at` при завершении.

### `deliver_analysis(analysis_id, target_id)`

- загружает единственную запись `Delivery` для пары;
- получает Redis-lock для этой доставки;
- прекращает работу для `sent` и `failed`;
- формирует итоговый текст;
- вызывает Telegram Bot API через прокси;
- сохраняет попытку и результат.

### `recover_orphaned_work`

- запускается Celery Beat каждые 300 секунд;
- завершает fan-out релевантных успешных `Analysis`, у которых отсутствует `delivery_fanout_completed_at`;
- повторно публикует устаревшие `queued` анализы;
- повторно публикует устаревшие `pending` доставки только после `next_attempt_at`;
- не восстанавливает `sent` и `failed`;
- использует safety timeout согласно ADR-0002.


## 8. Ошибки и повторные попытки

### X API

| Код | Поведение |
|---|---|
| 401 | Остановить задачу, записать ошибку токена |
| 403 | Записать отсутствие доступа |
| 404 | Записать отсутствие источника |
| 429 | Повторить после `x-rate-limit-reset` |
| 5xx | Celery retry с exponential backoff |

### ИИ-провайдер

- timeout и 5xx → retry;
- 401/403 → сохранить конфигурационную ошибку без бесконечных повторов;
- невалидный structured output → повторить до `retry_count`, затем `failed`.

### Telegram

- временные сетевые ошибки и 5xx → retry;
- заблокированный ботом пользователь или недоступный чат → отключить target после подтверждённой постоянной ошибки;
- ошибка канала → сохранить ошибку, не отключать автоматически.

## 9. Docker Compose

Обязательные сервисы:

```yaml
services:
  init:
  web:
  bot:
  worker:
  beat:
  test:
  postgres:
  redis:
```

`test` включается профилем `tools` и не является production runtime-сервисом.

Требования:

- `web`, `bot`, `worker`, `beat` собираются из одного Dockerfile;
- PostgreSQL использует persistent volume;
- Redis использует persistent volume и AOF `appendfsync everysec`;
- master key монтируется в прикладные контейнеры read-only;
- healthcheck PostgreSQL и Redis используется перед запуском прикладных процессов;
- one-shot сервис `init` выполняет checks, миграции, `collectstatic` и deployment checks;
- `web`, `bot`, `worker`, `beat` зависят от успешного завершения `init`;
- `init` и `web` используют общий `static_data` volume для результатов `collectstatic`;
- в репозитории присутствует `.env.example` только для инфраструктурных параметров без реальных секретов;
- прикладные секреты вводятся через Django Admin после первоначального запуска.

Пользовательские bootstrap-параметры вне PostgreSQL:

```text
DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS
QUOTARADAR_WEB_BIND_ADDRESS
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
```

Docker Compose задаёт внутренние `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_URL` и `QUOTARADAR_MASTER_KEY_FILE`. Master key создаётся локальным скриптом и подключается как read-only file secret. Django также поддерживает `DATABASE_URL` вне Compose, причём он имеет приоритет над дискретными PostgreSQL-параметрами.

Superuser создаётся отдельной воспроизводимой командой и не требует bootstrap-credentials в `.env`.

## 10. Нефункциональные требования

### NFR-001. Автоматизация

После настройки система работает без ручного подтверждения публикаций.

### NFR-002. Идемпотентность

Повторный запуск любой задачи не должен создавать повторные `Analysis` или `Delivery`. Подтверждённо успешная доставка не отправляется повторно. Для неопределённого результата Telegram действует ограничение ADR-0002.

### NFR-003. Безопасность

- шифрование секретов at rest;
- отдельные Django permissions;
- отсутствие секретов в логах;
- master key вне PostgreSQL;
- все внешние запросы через прокси при включённой настройке.

### NFR-004. Наблюдаемость

Структурированные JSON-логи должны содержать применимые поля:

- timestamp;
- level и logger;
- event;
- task ID;
- source ID;
- internal source post ID, если X Post ID недоступен в recovery-контексте;
- X Post ID;
- analysis ID;
- delivery target ID;
- delivery ID;
- status;
- error type.

Тела HTTP-запросов и ответов не логируются. Итоговая JSON-строка проходит редактирование известных секретов и credentials.

### NFR-005. Производительность

Ожидаемая нагрузка — единицы постов в день. Архитектура не должна требовать горизонтального масштабирования для штатной работы.

### NFR-006. Совместимость

Проект должен запускаться через Docker Compose на Linux-сервере. Локальное управление репозиторием и запуск команд должны быть документированы для PowerShell.

## 11. Оценка использования X API

По текущим данным X:

- чтение Post resource — `$0.005`;
- чтение User resource — `$0.010`;
- тарификация чтения выполняется по возвращённым ресурсам.

При ориентировочной активности около 4 постов в день для двух источников ожидается около 120–130 Post reads в месяц без учёта повторно раскрываемых связанных постов.

Тарифы X являются внешней изменяемой зависимостью и должны проверяться перед развёртыванием.

## 12. Критерии приёмки

1. Система разворачивается одной командой Docker Compose после bootstrap-настройки.
2. Django Admin доступен и позволяет настроить все рабочие параметры.
3. Секреты сохраняются в PostgreSQL зашифрованно и отображаются уполномоченному администратору расшифрованными.
4. Все запросы к X, ИИ и Telegram проходят через указанный прокси; прямое подключение невозможно.
5. X User ID обоих источников успешно разрешаются через X API.
6. Новые посты получают уникальные записи в PostgreSQL.
7. Репосты не анализируются; ответы аккаунтов анализируются.
8. ИИ возвращает валидный структурированный результат.
9. Нерелевантный пост не отправляется в Telegram.
10. Релевантный пост формирует русскоязычное сообщение со ссылкой на X.
11. Сообщение успешно публикуется в настроенный канал.
12. Пользователь получает личные уведомления после `/start` и перестаёт получать после `/stop`.
13. Повторная обработка одного X Post ID не создаёт новую запись Telegram-доставки и не переотправляет сохранённо успешную доставку.
14. В логах отсутствуют Telegram token, X token, LLM API key и proxy URL.
15. Устаревшие `queued` и `pending` записи восстанавливаются периодической задачей согласно ADR-0002.
16. PostgreSQL и Redis integration tests проходят в Docker Compose/GitHub Actions.

## 13. Официальные технические источники

- X API — Get Posts: https://docs.x.com/x-api/users/get-posts
- X API — Getting Access: https://docs.x.com/x-api/getting-started/getting-access
- X API — Pricing: https://docs.x.com/x-api/getting-started/pricing
- X API — Rate Limits: https://docs.x.com/x-api/fundamentals/rate-limits
- X API — Pagination: https://docs.x.com/x-api/fundamentals/pagination
- X API — Data Dictionary: https://docs.x.com/x-api/fundamentals/data-dictionary
- Telegram Bot API: https://core.telegram.org/bots/api
- Celery documentation: https://docs.celeryq.dev/
