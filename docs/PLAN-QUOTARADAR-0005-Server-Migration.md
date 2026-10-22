# Перенос QuotaRadar на новый сервер

- Дата обследования: 2026-10-03, Europe/Moscow.
- Статус: согласован владельцем командой «делай» и выполнен 2026-10-03; QuotaRadar работает на новом сервере. Владелец изменил A-запись; оба authoritative DNS и доступ домена к новому IP проверены в 19:10:28 Europe/Moscow. Старый HTTPS vhost сохранён для клиентов с кешированной записью.
- Фактические результаты, время простоя и оставшиеся действия: `REPORT-QUOTARADAR-0005-Server-Migration.md`.
- Уже выполнено: создан SSH-пользователь `quotaradar` на новом сервере; проверены вход по ключу и `sudo -n`.
- Изменения production разрешаются только после явного согласования владельцем этого плана, согласно `AGENTS.md`.

## 1. Подтверждённое состояние

| Объект | Старый сервер | Новый сервер |
| --- | --- | --- |
| IP | `84.23.55.108` | `138.124.109.186` |
| SSH | `ubuntu`, существующий PEM владельца | `quotaradar`, новый Ed25519-ключ |
| ОС | Ubuntu 24.04.3 LTS, x86_64 | Ubuntu 26.04 LTS, x86_64 |
| Ресурсы | 1 CPU, 2 ГБ RAM, 2 ГБ swap | 1 CPU, 2 ГБ RAM, swap отсутствует |
| Свободный диск | около 79 ГБ | около 26 ГБ |
| Docker / Compose | 29.3.1 / 5.1.1 | Docker пока отсутствует |
| Deployment | `/opt/quotaradar`, без `.git` | `/opt` пока пуст |
| HTTP | Nginx → `127.0.0.1:8000` | Nginx пока отсутствует |

Домен: `qr.edevs.tech`, A-запись указывает на старый IP, TTL **21600 секунд (6 часов)**.
AAAA-запись при обследовании не получена. DNS обслуживают `ns1.mcs.mail.ru` / `ns2.mcs.mail.ru`.
TLS-сертификат `qr.edevs.tech` действует до 2026-12-17 17:40:12 UTC.
Админка отвечает штатным HTTP 302 на страницу входа с 2FA.
Старый сервер обслуживает другие сайты; их контейнеры, Nginx-конфигурации и сертификаты не входят в миграцию.

| Persistent volume | Данные | Размер при обследовании |
| --- | --- | --- |
| `quotaradar_postgres_data` | Полный кластер PostgreSQL 17.10 | 358 МиБ |
| `quotaradar_redis_data` | Redis 7.4.9, AOF + RDB, очереди и блокировки | 50 МиБ |
| `quotaradar_static_data` | Статика Django | 5,2 МиБ |

Размер самой БД около 302 МиБ; `/opt/quotaradar` вместе с существующими backup около 93 МиБ.
Внешних tablespace нет; PostgreSQL config, HBA, ident и WAL находятся внутри PGDATA.
Один администратор, один TOTP device, пять зашифрованных секретов; расшифровка всех пяти проверена без вывода значений.
571249 Django sessions также сохраняются: очистка или изменение retention не входит в задачу.
Это снимок количества записей, а не контрольные значения на момент будущего переключения.

Сервисы: `web`, `bot`, `worker`, `news-worker`, `news-urgent`, `beat`, `postgres`, `redis`; `init` — одноразовый.
При обследовании Redis не содержал очередей-list и `unacked`; фоновые процессы продолжали работать.
Мониторинг квот, сбор, анализ и публикация новостей включены; первое наполнение завершено.
Есть существующие `uncertain`/`reserved` записи X API — сохранить их статусы, не повторять запросы вручную.
Локальный news media cache в шести контейнерах отсутствовал, но перед переносом проверить снова.
У `beat` есть `/tmp/celerybeat-schedule` и SQLite WAL/SHM; их нужно сохранить после остановки процесса.

## 2. Доступ и неизменяемые материалы

Приватный ключ: `C:\Users\drmar\MyProjects\QuotaRadar\secrets\quotaradar-138.124.109.186.ed25519`.
Публичный ключ лежит рядом с суффиксом `.pub`; `known_hosts` — в той же существующей папке вне репозитория.
Windows ACL приватного ключа: только владелец `CRASH\drmar`, без наследования.
Fingerprint клиентского ключа: `SHA256:2fOlctH3o/S0pGwi18yQpRPMOBdAgJp6oUV954BVQpw`.
Fingerprint SSH нового сервера: `SHA256:ZadbKUBQzGqoNWfHDhj28VB1n+yR57lo/1/Tc+oMlGg`.
Fingerprint SSH старого сервера: `SHA256:dw8FTrSht8bdXe7bkzLfB81rhD6IRZjcXHRMt17TNdo`.
Пользователь `quotaradar`: `/home/quotaradar`, shell `/bin/bash`, группа `sudo`, passwordless sudo.
Права `.ssh` / `authorized_keys`: 0700 / 0600. Пароль root и политика SSH не изменялись.

```powershell
ssh -o UserKnownHostsFile="C:\Users\drmar\MyProjects\QuotaRadar\secrets\known_hosts" -i "C:\Users\drmar\MyProjects\QuotaRadar\secrets\quotaradar-138.124.109.186.ed25519" quotaradar@138.124.109.186
```

Перенести именно действующие images через `docker save` / `docker load`, без rebuild и без pull новых тегов:

| Image | Подтверждённый image ID |
| --- | --- |
| `quotaradar:local` | `sha256:518acb549a4843acd45118a87126f2369b9e6632bcb4baf3916c3386f57e9261` |
| `postgres:17-alpine` | `sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193` |
| `redis:7.4-alpine` | `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99` |

Источник кода — `/opt/quotaradar` и действующий image. Локальный `quotaradar/settings.py` отличается от production.
Поле commit в старом release.json: `dd56e41342de4ba3611f2f2d93e2ce83a406465a`; были последующие выкладки, поэтому это не идентификатор всего текущего deployment.
Сохранить production `.env` и `docker/secrets/master.key`, без генерации новых значений:
- `.env` SHA256: `90f1fe84bbf7380dcfff15da8954104f27806eec9eb7ad2b7447c024eecec47d`;
- master key SHA256: `bf30b6256e84b457eb502364e1c56f5718bf096dbac2665a2577d64334db1dde`;
- compose SHA256: `3091b63cc2392475770d36313dd8a6d59242e40bdcb13549913e11f156e08952`.
Перед миграцией заново снять manifest: production может измениться после обследования.

## 3. Предлагаемый способ и точные пути

Сохранить `/opt/quotaradar`, имя compose project `quotaradar` и все три named volume с существующими именами.
Не переводить PostgreSQL/Redis на новые bind mounts, не обновлять приложение, схему или версии images.
Основной перенос: предварительный `rsync` работающих volumes, затем штатная остановка и финальный `rsync --checksum`.
Предварительная копия PGDATA/AOF не является backup и никогда не запускается до завершения финальной синхронизации.
Физически переносится весь кластер PostgreSQL, включая роли, пароли, системные каталоги и WAL.

Для каждого volume источник и назначение — `/var/lib/docker/volumes/<точное_имя>/_data/`.
Перед операциями сверить реальные Mountpoint через `docker volume inspect`; несовпадение — стоп до решения владельца.
Артефакты операции: `/opt/quotaradar-migration/<migration-id>/` на обоих серверах, root-only 0700.
Имя операции зафиксировать перед началом, например `20261003-server-migration`; не перезаписывать существующий каталог.
Отдельная копия backup и master key — в существующей локальной папке `C:\Users\drmar\MyProjects\QuotaRadar\secrets\<migration-id>\`.

Передача — SSH/rsync с проверкой host keys, новым сервером как получателем и `sudo -n rsync` на обоих концах.
Использовать существующие ключи владельца через SSH-agent forwarding только на время передачи.
Windows ssh-agent доступен и при обследовании не содержал ключей; сначала повторно проверить его состояние.
Приватные ключи не копировать на серверы; в конце убрать только добавленные этой операцией identities.
Если agent forwarding не работает, остановить подготовку и согласовать способ передачи; не создавать обходные доступы самостоятельно.

## 4. Подготовка без остановки старого QuotaRadar

1. Получить согласование этого плана, включая paths, physical copy, reverse proxy, swap, DNS и условия отката.
2. Зафиксировать текущее состояние, images, manifests, volumes, конфигурации, число строк и схемы; проверить `migrate --check` текущим image.
3. Установить на новом сервере Docker Engine из официального apt repo для Ubuntu 26.04, Compose plugin, Nginx, Certbot и rsync; версии записать в manifest.
4. Создать на новом сервере 2 ГиБ swap `/swapfile`, режим 0600, добавить ровно одну запись в `/etc/fstab`; проверить NTP.
5. Настроить firewall с разрешёнными SSH/HTTP/HTTPS; PostgreSQL/Redis не публиковать, web оставить на `127.0.0.1:8000`.
6. Скопировать полный `/opt/quotaradar`, включая hidden files и прежние backups, и загрузить images; сверить image IDs и SHA256 конфигурации.
7. На новом хосте сделать `.env` root-only 0600. Master key сохранить читаемым для существующего non-root пользователя контейнера; доступ к host secrets directory ограничить.
8. Сохранить Nginx vhost только `qr.edevs.tech`, его certificate lineage `live` + `archive`, renewal config, ACME account и необходимые общие TLS include/DH files.
9. На новом сервере создать этот vhost с прежним доменом и upstream `127.0.0.1:8000`; остальные vhost старого сервера не копировать и не менять.
10. Проверить TLS нового IP с SNI `qr.edevs.tech`, не меняя DNS и не выпуская новый сертификат во время cutover.
11. Перенести `quota-radar-memory.service/.timer`, `/usr/local/libexec/quota-radar-memory.py`, logrotate config и существующие memory logs; новые логи не смешивать с историческим архивом.
12. Сделать свежий online `pg_dump -Fc` и backup globals; архивировать `.env`, master key и конфигурации, подписать SHA256 manifest, сохранить независимую копию локально.
13. Проверить восстановление этого настоящего dump в отдельном compose project `quotaradar-migration-check` на новом сервере: только PostgreSQL и одноразовые команды проверки.
14. Проверить данные, миграции и расшифровку секретов в restored copy без вывода значений; не запускать в rehearsal bot/beat/workers, не обращаться к платным API и не посылать тестовые сообщения.
15. Полностью остановить rehearsal и отделить его volumes от финальных; не использовать восстановленный dump как финальную БД.
16. Создать финальные контейнеры и пустые volumes через `docker compose create --no-build --pull never`; ни один из них пока не запускать.
17. Предварительно скопировать три production volume через `rsync -aHAX --numeric-ids`; повторить ближе к cutover. Исчезающие файлы в live copy не считать доказательством готовности.
18. Предварительно проверить загрузку images, права, Nginx config, доступ нового IP к обязательному proxy и нужным сервисам только безопасными запросами без отправки/платных вызовов.
19. Измерить скорость предварительного копирования и rehearsal startup; согласовать фактический downtime budget до остановки production.
20. При доступе к DNS снизить TTL до 300 заранее и выдержать прежние 6 часов. Если ждать неудобно, переключать через старый Nginx: DNS-кеши не должны вести на остановленный backend.

Копировать изменяемые Docker/Nginx logs отдельно в защищённый архив, без очистки оригиналов.
Никаких mock API, seed пользователей, reset паролей/TOTP, тестовых fixtures или повторного первого наполнения.
Проверка нового контура использует штатные services и реальные копии production-данных.

## 5. Окно переключения

Всё длительное — packages, images, backup, rehearsal, TLS и основное копирование — завершено до этого окна.
Перед началом проверить, что оба сервера доступны, свободного диска достаточно, нет параллельной выкладки и подтверждено ответственное лицо за DNS.

1. Отключить autorestart только старых контейнеров QuotaRadar (`docker update --restart=no` для восьми runtime containers), чтобы не получить второй активный контур после reboot/crash.
2. Сначала направить `SIGTERM` старому `beat`, дождаться штатного exit: новые periodic tasks больше не создаются.
3. Послать `SIGTERM` трём Celery workers и дождаться warm shutdown: текущие внешние вызовы и DB commits заканчиваются, reserved tasks возвращаются в Redis.
4. Не применять SIGKILL/короткий `docker stop` timeout. Если процесс не завершается в согласованное окно — отменить cutover, вернуть restart policy и старые services; разбираться без принудительного обрыва отправок.
5. В vhost только `qr.edevs.tech` временно включить HTTP 503 с Retry-After; сохранить прежний config, выполнить `nginx -t`, затем reload.
6. Штатно остановить `bot` с ожиданием окончания long poll и обработки полученного batch, затем `web` с ожиданием завершения HTTP requests; не сбрасывать Telegram updates/offset.
7. Убедиться, что шесть writers остановлены; зафиксировать финальные counts/checksums/статусы и отсутствие незавершённых DB транзакций, read-only запросами.
8. Зафиксировать Redis queue lengths/unacked и сохранить runtime cache каждого сервиса, если появился. После выхода `beat` забрать весь набор `celerybeat-schedule*`, включая WAL/SHM.
9. Отправить штатный SIGTERM PostgreSQL и Redis, дождаться их полного exit без SIGKILL; проверить clean shutdown по журналам и `pg_controldata`.
10. Замороженные source volumes не запускать. Выполнить финальный `rsync -aHAX --numeric-ids --checksum --delete-after` отдельно для трёх точных `_data/` на новом сервере.
11. `--delete-after` допускается только в этих трёх подтверждённых destination paths; источник всегда старый сервер, назначение всегда новый. Никогда не применять его к `/opt`, `/var/lib/docker` или исходным данным целиком.
12. Проверить exit code 0 и пустой контрольный `rsync --dry-run --checksum --itemize-changes` с теми же параметрами; сохранить manifest содержимого замороженных volumes. Восстановить beat schedule и per-service media cache в соответствующие остановленные контейнеры через `docker cp -a`.
13. Только после совпадения запустить новые `postgres` и `redis`: `docker compose up -d --no-deps --no-build --pull never postgres redis`.
14. Дождаться readiness и успешного чтения AOF, проверить БД read-only, роли, миграции, расшифровку всех секретов. Redis TTL могут естественно истечь: сравнивать persistent файлы до старта и queues/unacked, а не требовать одинаковый DBSIZE после старта.
15. Проверить отсутствие pending migrations до запуска `init`. Запустить только `init` существующим image; при неожиданной миграции или ошибке остановиться. После штатного init отметить checkpoint готовности.
16. **Перед первой прикладной записью объявить новый сервер источником истины.** Даже healthcheck `web` может создавать Django sessions; с момента запуска web простой rollback на старые volumes недопустим.
17. Запустить только новый `web`, проверить настоящий admin HTTP/TLS через `curl --resolve` и штатный браузер; вход с существующими данными/2FA выполняет владелец, если они нужны для проверки.
18. В старом QR vhost заменить upstream на `https://138.124.109.186`, сохранить `Host: qr.edevs.tech` и forwarded headers; включить SNI/hostname `qr.edevs.tech`, `proxy_ssl_verify on` и системный CA bundle. Проверить `nginx -t` и reload; снять временный 503.
19. Убедиться, что запросы через старый IP и напрямую через новый IP обслуживает новый backend. Старый PostgreSQL/Redis/web больше не стартуют.
20. Запустить новые `worker`, `news-worker`, `news-urgent`, затем `bot`, последним `beat`, с `--no-build --pull never` и явным списком сервисов.
21. Проверить отсутствие параллельного bot polling, errors/409, worker crash, повторной обработки sent-записей; resumed publications выполняются только обычным production workflow.
22. Изменить только A `qr.edevs.tech` на `138.124.109.186`; не менять NS, root-domain records или добавлять AAAA самостоятельно. Старый Nginx продолжает HTTPS forwarding на время DNS-кешей.

Во всех командах `up` выбирать точные сервисы; не запускать весь stack одной командой до checkpoint.
Старые data volumes, deployment, backups, TLS и другие сайты сохраняются без удаления.

## 6. Простой, гарантии и критерии приёмки

Цель по зафиксированным небольшим volumes — окно порядка 1–3 минут после окончания активных задач.
Это предварительная инженерная оценка, а не измеренное обещание: фактическое время зависит от warm shutdown, delta, disk I/O и startup.
Продолжительность паузы публикаций измерять от остановки beat; недоступность admin — от включения 503; паузу bot — от остановки polling.
Если подготовка показывает неприемлемое окно, отдельно согласовать PostgreSQL replication/Redis replication; не внедрять их самостоятельно.
Предварительный rsync уменьшает финальную передачу; старый HTTPS proxy исключает дополнительный простой из-за DNS TTL.

Цель RPO = 0 для подтверждённых записей БД и согласованного состояния очередей на момент штатной остановки.
Сохранить всех subscribers/targets, историю доставок/message IDs, prompts/configuration, cursors/checkpoints, budgets, generated cover bytes и encrypted secrets.
Сохранить пользователей, password hashes, TOTP secret/counters, Django sessions и имеющиеся recovery tokens; ничего не bootstrap-ить и не пересоздавать.
Физическая копия frozen volumes + сверка содержимого — основное доказательство; counts и checksums таблиц — дополнительная проверка.
Длительные внешние HTTP-вызовы не обрывать: Telegram exactly-once в неопределённом сетевом исходе приложение не гарантирует, как описано в ADR-0002.
Не повторять вручную `uncertain` доставки/платные операции для видимости успешной проверки.

Приёмка: healthy PostgreSQL/Redis/web, init exit 0, один bot/beat, все три workers стабильны; admin доступна по обоим IP с правильным TLS/доменом.
Данные и исходные секреты совпали до разрешения новых writes; existing sent IDs не сброшены; незавершённая работа продолжилась штатно.
Не запускать полный тестовый прогон на production. Наблюдать первые штатные циклы квот/новостей и подтверждать отсутствие ошибок/новых OOM.
После переключения сделать свежий backup нового источника истины; настройку регулярных backups и срока хранения оформить отдельно, если её нет.

## 7. Откат

**До первой прикладной записи на новом сервере:** остановить target services, вернуть исходный старый QR vhost и restart policies `unless-stopped`, запустить старые PostgreSQL/Redis, затем init/web/workers/bot/beat. Данные на старом сервере не изменялись во время frozen transfer; DNS ещё не переключён.

**После запуска нового web или фоновых процессов:** источником истины остаются новые volumes.
Нельзя просто включить старую БД: это потеряет новые subscriptions, sessions, доставки и checkpoints.
При необходимости возврата остановить producers/writers нового контура штатно, заморозить его PostgreSQL/Redis, сохранить backup и выполнить обратную checksum-синхронизацию всех трёх volumes и runtime artifacts.
Перед перезаписью старых destination volumes сохранить их frozen snapshot; сверить роли, секреты и содержимое, затем вернуть единственный active stack на старом хосте.
Новый Nginx временно проксирует на старый IP с TLS/SNI verify для DNS-кешей, а A-запись возвращается на старый IP.
Обратный перенос — отдельное изменяющее действие в production и требует явного согласования владельца; без него сохранять новый источник истины и исправлять новый контур.
Если новый хост недоступен и его свежие данные нельзя получить, rollback с RPO = 0 не подтверждён; не выдавать старый snapshot за полный.

## 8. После переключения и необходимые решения владельца

Старый QR proxy оставить минимум на прежний DNS TTL с запасом; предлагается 48 часов после изменения A-записи и проверка authoritative/public DNS.
Это страховка кешей, а не основание удалить старые данные. Другие сайты остаются на старом сервере.
Настроить renewal только перенесённого сертификата на новом хосте; не отключать глобальный Certbot timer старого хоста.
Убрать forwarding позже отдельным согласованным действием; decommission и удаление backup/volumes не входят в этот план.

Для начала реализации нужны: явное согласование разделов 3–7; кто меняет A/TTL в DNS; подходящее время и приемлемое окно простоя.
Новые учётные данные приложения, password/TOTP reset и выбор других storage paths не требуются и не разрешены этим планом.

## 9. Основания

- [PostgreSQL 17: filesystem backup и двухпроходный rsync с checksum после shutdown](https://www.postgresql.org/docs/17/backup-file.html).
- [Redis: AOF, multipart appendonlydir и persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/).
- [Docker: установка на Ubuntu 26.04](https://docs.docker.com/engine/install/ubuntu/), [compose create](https://docs.docker.com/reference/cli/docker/compose/create/), [compose up](https://docs.docker.com/reference/cli/docker/compose/up/).
- [Nginx: HTTPS upstream, SNI и проверка сертификата](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ssl_verify).
- Внутренние документы: `AGENTS.md`, `README.md`, `ADR-QUOTARADAR-0002-Recovery-of-Orphaned-Work.md`, действующие compose/entrypoint и read-only обследование обоих серверов.
