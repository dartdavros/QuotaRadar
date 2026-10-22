# Перенос QuotaRadar: результат 2026-10-03

## Результат

QuotaRadar перенесён с `84.23.55.108` на `138.124.109.186` по согласованному PLAN-0005.
Новый сервер является источником истины с **18:44:38 Europe/Moscow**.
Домен `qr.edevs.tech` обслуживает новый backend. Владелец изменил A-запись на `138.124.109.186`.
В **19:10:28 Europe/Moscow** оба authoritative DNS (`5.61.237.121`, `5.61.237.122`), Cloudflare и Google подтвердили новый IP. Запрос по домену с нового сервера получил HTTP 302 от `138.124.109.186`, TLS verification = 0.
На компьютере владельца отдельные DNS-запросы ещё возвращали кешированный старый IP. Старый Nginx продолжает направлять такие запросы на новый IP по HTTPS с проверкой сертификата и SNI.

## Что сохранено и проверено

- Действующий image приложения, PostgreSQL 17.10 и Redis 7.4.9 перенесены без пересборки и обновления images; их IDs совпали.
- Сохранены `/opt/quotaradar`, `.env`, master key и все три named volume с прежними именами. Новых storage paths/bind mounts для данных нет.
- Все восемь старых runtime containers завершились с exit code 0. PostgreSQL подтвердил `shut down`; SIGKILL не применялся.
- Frozen volumes прошли финальный checksum rsync, пустой контрольный dry-run и проверку SHA256 всех файлов до старта target services.
- До прикладных writes совпали counts всех **39 таблиц**, fingerprints **17 критичных таблиц**, статусы работы и результат расшифровки всех **5 секретов**.
- Сохранены администратор, password hashes, роли, TOTP, Django sessions, подписчики, доставленные message IDs, курсоры, prompts, бюджеты, generated covers и Redis persistence.
- На момент финального снимка: 1 администратор, 1 TOTP device, 571525 sessions, 43 targets, 1107 quota deliveries, 85 news publications и 43 media assets.
- Сохранён локальный runtime `beat`, включая его schedule. Возможные per-service media cache переносились из штатно остановленных контейнеров.
- `migrate --check` прошёл. Init завершился с exit code 0; неожиданных миграций схемы нет.
- Новый `web`, PostgreSQL и Redis healthy; все восемь services running, restarts = 0, OOM = false.
- Штатные `monitoring.poll_sources`, `monitoring.poll_source`, recovery и news collection/tick успешно выполняются. Ошибок/tracebacks/Telegram 409 в проверенных новых логах нет.
- TLS и admin HTTP 302 проверены напрямую на новом IP и через старый IP. В браузере открылась реальная штатная форма авторизации; вход с паролем/TOTP не выполнялся.
- Перенесены TLS lineage/ACME account, renewal config и мониторинг памяти; Certbot timer включён. Новый сертификат не выпускался.
- Другой работающий сайт старого сервера (`markmello-website`) остался healthy. Его deployment, данные и vhost не изменялись.

## Фактические интервалы

Все времена ниже — 2026-10-03, **Europe/Moscow**.

| Этап | Начало | Окончание | Интервал |
| --- | --- | --- | --- |
| Админка через прежний IP/DNS | 18:40:36 | 18:47:57 | **7 мин 21 с** |
| Остановка bot: от начала процедуры до старта нового container | 18:40:36 | 18:47:55 | 7 мин 19 с |
| Пауза scheduler/publications | 18:38:45 | 18:47:57 | 9 мин 12 с |

Исходная оценка 1–3 минуты не достигнута. Штатный exit beat/bot/web занимал 36–41 секунду на процесс; ожидание workers также увеличило паузу scheduler.
Дополнительная задержка admin возникла после старта нового web: старый Nginx возвращал 502 из-за недостаточной глубины TLS chain verification.
Исправлено только `proxy_ssl_verify_depth 3`; `proxy_ssl_verify on` и системный CA bundle сохранены. TLS-проверка не отключалась.
Прямой доступ нового web был проверен в 18:44:43, forwarding старого IP окончательно проверен в 18:47:57.

## Резервные копии и доступ

SSH: `quotaradar@138.124.109.186`; ключ находится в существующей папке рядом с репозиторием:
`C:\Users\drmar\MyProjects\QuotaRadar\secrets\quotaradar-138.124.109.186.ed25519`.
Приватный ключ принадлежит Windows-владельцу `CRASH\drmar`, доступ только ему. Root password и SSH authentication policy не менялись.

Артефакты операции на обоих серверах: `/opt/quotaradar-migration/20261003-server-migration/`, root-only.
На новом сервере `source/` содержит старый backup и frozen evidence; `post-cutover/` — свежий backup нового источника истины.
Независимая копия свежего backup на старом сервере: `new-authority-backup/` внутри каталога операции. SHA256 проверены на обоих концах.
Локальный архив, отдельно явно разрешённый владельцем, находится в:
`C:\Users\drmar\MyProjects\QuotaRadar\secrets\20261003-server-migration\source-backup.private.tar`.
Содержимое и SHA256 DB/globals/config archive проверены; Windows ACL — только владелец. TLS private keys в локальный архив не входят.
Временное SSH-agent forwarding использовалось для передачи без копирования приватных SSH-ключей на серверы.
Старые volumes/deployment/backups не удалялись; старые runtime containers выключены с restart policy `no`.

## Оставшиеся действия владельца

1. A `qr.edevs.tech` → `138.124.109.186` изменена владельцем и проверена. NS/root-domain/AAAA в рамках миграции не менялись.
2. Сохранить старый QR HTTPS proxy минимум на прежний TTL с запасом; согласованный ориентир — 48 часов после изменения A и проверка DNS. Отключать его не ранее **2026-10-05 19:11 Europe/Moscow** и только после проверки. Прежний TTL был 21600 секунд; текущий authoritative TTL — 86400 секунд.
3. Снятие старого proxy или удаление старых данных — отдельное согласованное действие, в выполненную миграцию не входит. Автоматическое отключение не настроено.

После первых новых writes нельзя просто включать прежние volumes: это потеряет новые данные.
При необходимости отката руководствоваться разделом 7 согласованного плана с новым сервером как источником истины и отдельным согласованием обратного переноса.
Регулярные backup schedules/retention не добавлялись: план предусматривает отдельное решение по ним.
Приложение, UI, passwords, TOTP, recovery tokens и бизнес-конфигурация не редактировались; mock API/fixtures/seed не создавались.
