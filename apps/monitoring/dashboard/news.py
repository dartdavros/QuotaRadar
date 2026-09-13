"""Health of the news feed: collection, editorial pipeline, publication."""
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Max, Q

from apps.news.budget import WEEKLY_CAP
from apps.news.models import (CollectionCheckpoint, NewsAssessment, NewsConfiguration, NewsDelivery, NewsEvent,
                              NewsPublication, XBudgetPeriod)
from apps.sources.models import Feed, SourcePost

from .report import ERROR, OFF, WARN, Check, admin_link, age, short

STUCK_AFTER = timedelta(minutes=30)


def retry_in(moment, now) -> str:
    seconds = max(0, int((moment - now).total_seconds()))
    return f"{seconds} с" if seconds < 60 else f"{seconds // 60} мин"


def next_window(config, now) -> str:
    """Human label of the next regular publication window in the configured timezone."""
    local = now.astimezone(ZoneInfo(config.timezone))
    minute_now = local.hour * 60 + local.minute
    windows = sorted(config.windows)
    upcoming = [w for w in windows if w > minute_now]
    if any(0 <= minute_now - w < 30 for w in windows):
        return "открыто сейчас"
    if upcoming:
        return f"сегодня в {upcoming[0] // 60:02d}:{upcoming[0] % 60:02d}"
    return f"завтра в {windows[0] // 60:02d}:{windows[0] % 60:02d}" if windows else "окна не заданы"


def queue_line(config, now) -> str:
    """What is waiting to be published and when it can go out."""
    events = NewsEvent.objects.filter(expires_at__gt=now, score__gte=config.min_score)
    if config.activated_at:
        events = events.filter(first_seen_at__gte=config.activated_at)
    if config.target_id:
        events = events.exclude(publications__target=config.target)
    urgent = events.filter(urgent=True).count()
    local_date = now.astimezone(ZoneInfo(config.timezone)).date()
    today = NewsPublication.objects.filter(slot_date=local_date, status__in=("ready", "sending", "sent", "uncertain")).count()
    return (f"В очереди: {events.count()} событий с оценкой ≥ {config.min_score}, из них срочных {urgent}. "
            f"Опубликовано сегодня: {today} из {config.daily_limit}. Следующее окно: {next_window(config, now)}.")


def news_config_link(config):
    return admin_link("Настройки новостей", "news_newsconfiguration_change", args=(config.pk,))


def check_news_collection(config: NewsConfiguration, now) -> Check:
    check = Check("Сбор новостей", links=[
        admin_link("Точки сбора", "news_collectioncheckpoint_changelist"),
        admin_link("Бюджет X", "news_xbudgetperiod_changelist"),
        news_config_link(config),
    ])
    if not config.collection_enabled:
        check.fail(OFF, "Сбор новостей выключен в настройках новостей.")
        return check
    checkpoints = CollectionCheckpoint.objects.select_related("source")
    check.last_success = "собрано до " + age(checkpoints.aggregate(m=Max("completed_until"))["m"], now)
    for point in (c for c in checkpoints if c.last_error):
        retry = (f" Повтор через {retry_in(point.next_attempt_at, now)}." if point.next_attempt_at
                 and point.next_attempt_at > now else " Повтор при следующем тике.")
        check.fail(WARN, f"@{point.source.username}: {short(point.last_error, 160)}{retry}")
        check.details.append(f"@{point.source.username}: {short(point.last_error)}{retry}")
    # The setting is the truth; the week's stored limit only catches up on the next reservation.
    limit = min(config.weekly_x_limit, WEEKLY_CAP)
    period = XBudgetPeriod.objects.order_by("-week").first()
    committed = period.committed if period else 0
    if committed >= limit:
        check.fail(WARN, f"Недельный бюджет X исчерпан ({committed} из {limit} USD): поднимите его в настройках новостей.")
    received = SourcePost.objects.filter(source__subscriptions__feed=Feed.NEWS, source__subscriptions__enabled=True,
                                         received_at__gte=now - timedelta(hours=24)).distinct().count()
    if not received:
        check.fail(WARN, "За сутки не собрано ни одного поста для новостей.")
    check.details.insert(0, f"Бюджет X за неделю: {committed} из {limit} USD (по текущей настройке), "
                            f"постов за сутки: {received}.")
    if not check.summary:
        check.summary = "Сбор идёт, ошибок по источникам нет."
    return check


def check_news_editorial(config: NewsConfiguration, now) -> Check:
    check = Check("Отбор и редактура новостей", links=[
        admin_link("Отборы", "news_newsassessment_changelist", "status__exact=blocked"),
        admin_link("Публикации", "news_newspublication_changelist"),
        news_config_link(config),
    ])
    if not config.analysis_enabled:
        check.fail(OFF, "Анализ новостей выключен в настройках новостей.")
        return check
    if not config.assessment_prompt or not config.assessment_prompt.is_active:
        check.fail(ERROR, "Не задан активный промпт отбора: новости не оцениваются.")
    if config.publishing_enabled and (not config.writing_prompt or not config.writing_prompt.is_active):
        check.fail(ERROR, "Не задан активный промпт редактора: тексты не пишутся.")
    check.last_success = age(NewsAssessment.objects.filter(status="done").aggregate(m=Max("created_at"))["m"], now)
    day = now - timedelta(hours=24)
    assessed = NewsAssessment.objects.filter(status="done", created_at__gte=day).count()
    events = NewsEvent.objects.filter(first_seen_at__gte=day).count()
    check.details.append(f"За сутки отобрано постов: {assessed}, событий создано: {events}.")
    stuck_since = now - STUCK_AFTER
    stuck = NewsAssessment.objects.filter(status__in=("pending", "running"), created_at__lt=stuck_since).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lt=now)).count()
    if stuck:
        check.fail(WARN, f"{stuck} отбор(ов) не обработаны дольше 30 мин. Проверьте новостной воркер и ИИ.")
    preparing = NewsPublication.objects.filter(status="preparing", created_at__lt=stuck_since).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lt=now))
    if preparing.exists():
        latest = preparing.order_by("-created_at").first()
        check.fail(WARN, f"{preparing.count()} публикаций готовятся дольше 30 мин. "
                         f"{('Последняя ошибка: ' + short(latest.last_error, 140)) if latest.last_error else ''}")
    blocked = NewsAssessment.objects.filter(status="blocked", created_at__gte=day).exclude(last_error="")
    if blocked.exists():
        latest = blocked.order_by("-created_at").first()
        check.details.append(f"Заблокированных отборов за сутки: {blocked.count()}. Последний: {short(latest.last_error)}")
    if not check.summary:
        check.summary = "Отбор и редактура идут без задержек."
    return check


def check_news_publishing(config: NewsConfiguration, now) -> Check:
    check = Check("Публикация новостей в Telegram", links=[
        admin_link("Заблокированные", "news_newspublication_changelist", "status__exact=blocked"),
        admin_link("Неизвестный результат", "news_newspublication_changelist", "status__exact=uncertain"),
        admin_link("Доставки", "news_newsdelivery_changelist"),
        news_config_link(config),
    ])
    if not config.publishing_enabled:
        check.fail(OFF, "Публикация новостей выключена в настройках новостей.")
        return check
    if not config.target or not config.target.enabled:
        check.fail(ERROR, "Новостной канал не задан или выключен: публиковать некуда.")
    publications = NewsPublication.objects.all()
    check.last_success = age(NewsDelivery.objects.filter(sent_at__isnull=False).aggregate(m=Max("sent_at"))["m"], now)
    uncertain = publications.filter(status="uncertain").count()
    if uncertain:
        check.fail(ERROR, f"{uncertain} публикаций с неизвестным результатом отправки: проверьте канал вручную "
                          "и отметьте результат в доставке.")
    failing = NewsDelivery.objects.filter(sent_at__isnull=True).exclude(last_error="").select_related("publication")
    failing = failing.filter(publication__status__in=("ready", "sending"))
    if failing.exists():
        latest = failing.order_by("-publication__created_at").first()
        check.fail(ERROR, f"Telegram отклоняет отправку: {short(latest.last_error, 160)}")
    day = now - timedelta(hours=24)
    blocked = publications.filter(status="blocked", created_at__gte=day)
    if blocked.exists():
        latest = blocked.order_by("-created_at").first()
        check.details.append(f"Заблокированных за сутки: {blocked.count()}. Последняя причина: {short(latest.last_error)}")
    ready = publications.filter(status="ready", created_at__lt=now - STUCK_AFTER).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lt=now)).count()
    if ready:
        check.fail(WARN, f"{ready} готовых публикаций не отправлены дольше 30 мин. Проверьте новостной воркер.")
    check.details.insert(0, queue_line(config, now))
    check.details.insert(1, f"Отправлено за сутки: {NewsDelivery.objects.filter(sent_at__gte=day).count()}, "
                            f"канал: {config.target.telegram_chat_id if config.target else '—'}.")
    if not check.summary:
        check.summary = "Новости публикуются."
    return check
