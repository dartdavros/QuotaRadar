# ADR-QUOTARADAR-0002 — Восстановление потерянных задач

- **Статус:** принято
- **Дата:** 2026-07-20
- **Связанные документы:**
  - `ARCH-QUOTARADAR-0001-System-Architecture.md`
  - `SPEC-QUOTARADAR-0001-Technical-Specification.md`

## 1. Контекст

QuotaRadar использует PostgreSQL как источник истины и Redis как Celery broker, result backend и хранилище distributed locks.

До принятия решения Redis работал без persistence. При перезапуске или пересоздании Redis могли исчезнуть опубликованные Celery-сообщения, тогда как PostgreSQL уже содержал:

- `SourcePost.processing_status = queued`;
- релевантный `Analysis` без завершённого fan-out доставок;
- `Delivery.status = pending`.

Без отдельного recovery-механизма такие записи могли остаться в промежуточном состоянии навсегда.

Простая периодическая переотправка всех `queued` и `pending` записей неприемлема: она создаёт конкурирующие LLM-запросы, лишние расходы и риск повторной Telegram-доставки.

## 2. Решение

### 2.1. Redis persistence

Redis использует named volume и AOF:

```text
appendonly yes
appendfsync everysec
```

Snapshot также остаётся включённым как дополнительный механизм восстановления.

### 2.2. Celery delivery semantics

Для задач включаются:

- late acknowledgement;
- reject on worker lost;
- task started tracking;
- Redis visibility timeout.

Эти настройки уменьшают вероятность потери задачи при аварийном завершении worker, но не заменяют reconciliation с PostgreSQL.

### 2.3. Явные processing timestamps

`SourcePost` хранит `processing_started_at`.

`Analysis` хранит `delivery_fanout_completed_at`, который выставляется в одной транзакции с созданием `Delivery` для всех активных targets. Отправка Celery-задач выполняется после commit.

`Delivery` хранит:

- `created_at`;
- `updated_at`;
- `last_attempt_at`;
- `next_attempt_at`.

По этим timestamps определяется, что запись действительно устарела, а не обрабатывается штатно.

### 2.4. Distributed locks

Используются отдельные Redis-lock:

- polling одного источника;
- анализ одного `SourcePost`;
- доставка одной записи `Delivery`.

Lock acquisition является обязательным перед выполнением соответствующего внешнего вызова.

### 2.5. Периодическое восстановление

Celery Beat запускает `monitoring.recover_orphaned_work` каждые 300 секунд.

Задача выполняет reconciliation в следующем порядке:

1. находит успешный релевантный `Analysis` без `delivery_fanout_completed_at`;
2. под блокировкой строки транзакционно создаёт отсутствующие `Delivery`, фиксирует завершение fan-out и публикует новые задачи после commit;
3. находит `SourcePost` в `queued`, чей `processing_started_at` старше safety timeout;
4. повторно публикует `analyze_post(source_post_id)`;
5. находит `Delivery` в `pending`, чей `last_attempt_at` или `created_at` старше safety timeout и чей `next_attempt_at` не задан либо наступил;
6. повторно публикует `deliver_analysis(analysis_id, target_id)` для найденной записи;
7. не трогает `sent` и `failed` записи.

Начальные thresholds:

- анализ — 1800 секунд;
- доставка — 1200 секунд.

Threshold доставки больше штатного retry backoff, чтобы recovery не конкурировал с активной retry-цепочкой.

### 2.6. Статусы Telegram-доставки

- временная ошибка оставляет `Delivery` в `pending` и сохраняет `next_attempt_at` с учётом Telegram `retry_after` или exponential backoff;
- после исчерпания retry запись становится `failed`;
- подтверждённая постоянная ошибка сразу становится `failed`;
- недоступный private chat отключает target;
- ошибка channel target не отключает канал автоматически;
- `failed` не восстанавливается автоматически.

## 3. Идемпотентность и граница гарантии

Уникальность `analysis + target` гарантирует одну запись журнала доставки. Redis-lock предотвращает штатные параллельные отправки этой записи.

Однако Telegram Bot API не предоставляет idempotency key для `sendMessage`. Существует неопределённое окно:

1. Telegram принял сообщение;
2. процесс завершился до сохранения `telegram_message_id` и статуса `sent`;
3. recovery или retry повторяет запрос.

Поэтому гарантируется отсутствие повторной отправки после подтверждённого и сохранённого результата. При неопределённом сетевом исходе действует at-least-once semantics, и теоретический дубль допустим как внешнее ограничение Telegram API.

## 4. Последствия

Положительные:

- перезапуск Redis не уничтожает всю очередь без возможности восстановления;
- PostgreSQL остаётся источником истины для незавершённой работы;
- авария между сохранением релевантного анализа и созданием доставок устраняется reconciliation fan-out;
- зависшие записи автоматически возвращаются в обработку;
- recovery не переотправляет подтверждённо успешные и окончательно ошибочные доставки;
- конкурирующие LLM- и Telegram-вызовы ограничены locks.

Отрицательные:

- Redis AOF требует persistent storage и операций резервного копирования/мониторинга;
- recovery добавляет eventual delay до следующего цикла;
- абсолютная exactly-once Telegram-доставка невозможна без поддержки idempotency key внешним API;
- thresholds являются эксплуатационными параметрами кода версии `0.1.0`, а не редактируемой бизнес-конфигурацией.

## 5. Отклонённые варианты

### Redis без persistence

Отклонён из-за потери опубликованных задач при пересоздании контейнера.

### Переотправка всех `queued`/`pending` на каждом цикле

Отклонена из-за гонок, повторных расходов LLM и повышенного риска дублей.

### Перевод временной Telegram-ошибки сразу в `failed`

Отклонён, потому что временная ошибка должна оставаться восстанавливаемой до исчерпания retry policy.

### Обещание строгой exactly-once доставки

Отклонено как технически недостоверное при использовании Telegram `sendMessage` без idempotency key.
