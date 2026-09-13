"""Health of the quota feed: X polling, AI analysis, Telegram delivery."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Max, Q

from apps.analysis.models import Analysis
from apps.monitoring.models import MonitoringComponent, MonitoringEvent, MonitoringEventStatus
from apps.sources.models import Feed, Source, SourcePost, SourcePostProcessingStatus
from apps.sources.routing import quota_sources
from apps.telegram.models import Delivery, DeliveryStatus, DeliveryTarget

from .report import ERROR, OFF, WARN, Check, admin_link, age, minutes, short

POLL_GRACE = 3  # A source is "not polled" after this many missed intervals.


def last_event_error(check: Check, component: str, now) -> None:
    event = MonitoringEvent.objects.filter(component=component, status=MonitoringEventStatus.ERROR).first()
    if event:
        check.last_error_at = age(event.created_at, now)
        check.last_error = short(f"{event.error_type}: {event.message}" if event.error_type else event.message)


def check_x_polling(config, now) -> Check:
    check = Check("Опрос X (лимиты)", links=[
        admin_link("Источники", "sources_source_changelist"),
        admin_link("Ошибки X", "monitoring_monitoringevent_changelist", "component=x&status=error"),
        admin_link("Настройки", "configuration_systemconfiguration_change", args=(config.pk,)),
    ])
    last_event_error(check, MonitoringComponent.X, now)
    if not config.monitoring_enabled:
        check.fail(OFF, "Мониторинг лимитов выключен в настройках системы.")
        return check
    sources = list(quota_sources(Source.objects.filter(enabled=True)))
    if not sources:
        check.fail(ERROR, "Нет ни одного активного источника для лимитов.")
        return check
    check.last_success = age(max((s.last_success_at for s in sources if s.last_success_at), default=None), now)
    limit = now - timedelta(seconds=config.poll_interval_seconds * POLL_GRACE)
    stale = [s.username for s in sources if not s.last_checked_at or s.last_checked_at < limit]
    if stale:
        check.fail(ERROR, f"Не опрашивались более {minutes(config.poll_interval_seconds * POLL_GRACE)}: "
                          f"@{', @'.join(stale)}. Проверьте планировщик и воркер.")
    failing = [s for s in sources if s.last_error and (not s.last_success_at or s.last_checked_at
                                                       and s.last_checked_at > s.last_success_at)]
    for source in failing:
        check.fail(ERROR, f"@{source.username}: {short(source.last_error, 160)}")
        check.details.append(f"@{source.username}: {short(source.last_error)}")
    check.details.insert(0, f"Активных источников: {len(sources)}, опрос каждые {minutes(config.poll_interval_seconds)}.")
    if not check.summary:
        check.summary = "Все источники опрашиваются вовремя."
    return check


def check_ai_analysis(config, now) -> Check:
    check = Check("Анализ ИИ (лимиты)", links=[
        admin_link("Посты с ошибкой", "sources_sourcepost_changelist", "processing_status__exact=failed"),
        admin_link("Ошибки ИИ", "monitoring_monitoringevent_changelist", "component=ai&status=error"),
        admin_link("Настройки ИИ", "configuration_systemconfiguration_change", args=(config.pk,)),
    ])
    last_event_error(check, MonitoringComponent.AI, now)
    if not config.monitoring_enabled:
        check.fail(OFF, "Мониторинг лимитов выключен, анализировать нечего.")
        return check
    if not config.llm_provider or not config.llm_model:
        check.fail(ERROR, "ИИ-провайдер или модель не заданы в настройках системы.")
    posts = SourcePost.objects.filter(source__in=quota_sources(Source.objects.all()))
    done = posts.filter(processing_status__in=(SourcePostProcessingStatus.ANALYZED_RELEVANT,
                                               SourcePostProcessingStatus.ANALYZED_IRRELEVANT))
    check.last_success = age(Analysis.objects.filter(source_post__in=done).aggregate(m=Max("created_at"))["m"], now)
    day = now - timedelta(hours=24)
    failed = posts.filter(processing_status=SourcePostProcessingStatus.FAILED, received_at__gte=day)
    if failed.exists():
        latest = failed.order_by("-received_at").first()
        check.fail(ERROR, f"Ошибок анализа за сутки: {failed.count()}. Последняя: {short(latest.last_error, 160)}")
    cutoff = now - timedelta(seconds=settings.QUOTARADAR_ANALYSIS_STALE_SECONDS)
    stuck = posts.filter(processing_status__in=(SourcePostProcessingStatus.RECEIVED, SourcePostProcessingStatus.QUEUED),
                         received_at__lt=cutoff).count()
    if stuck:
        check.fail(WARN, f"{stuck} пост(ов) ждут анализа дольше {minutes(settings.QUOTARADAR_ANALYSIS_STALE_SECONDS)}. "
                         "Проверьте воркер и ИИ-провайдера.")
    check.details.append(f"Модель: {config.llm_model or '—'} ({config.llm_provider or 'провайдер не задан'}).")
    if not check.summary:
        check.summary = "Посты анализируются без ошибок."
    return check


def check_telegram_quota(config, now) -> Check:
    check = Check("Telegram (лимиты)", links=[
        admin_link("Ошибки доставки", "telegram_delivery_changelist", "status__exact=failed"),
        admin_link("Цели доставки", "telegram_deliverytarget_changelist"),
        admin_link("Ошибки Telegram", "monitoring_monitoringevent_changelist", "component=telegram&status=error"),
    ])
    last_event_error(check, MonitoringComponent.TELEGRAM, now)
    targets = DeliveryTarget.objects.filter(feed=Feed.QUOTA)
    if not targets.filter(enabled=True).exists():
        check.fail(ERROR if targets.exists() else WARN,
                   "Нет активной цели доставки для лимитов: сообщения никуда не уходят.")
    deliveries = Delivery.objects.filter(target__feed=Feed.QUOTA)
    check.last_success = age(deliveries.filter(status=DeliveryStatus.SENT).aggregate(m=Max("sent_at"))["m"], now)
    day = now - timedelta(hours=24)
    failed = deliveries.filter(status=DeliveryStatus.FAILED, updated_at__gte=day)
    if failed.exists():
        latest = failed.order_by("-updated_at").first()
        check.fail(ERROR, f"Неотправленных за сутки: {failed.count()}. Последняя причина: {short(latest.last_error, 160)}")
    cutoff = now - timedelta(seconds=settings.QUOTARADAR_DELIVERY_STALE_SECONDS)
    hung = deliveries.filter(status=DeliveryStatus.PENDING, created_at__lt=cutoff).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lt=now)).count()
    if hung:
        check.fail(WARN, f"{hung} доставок висят в ожидании дольше {minutes(settings.QUOTARADAR_DELIVERY_STALE_SECONDS)}.")
    check.details.append(f"Активных целей: {targets.filter(enabled=True).count()}, "
                         f"отправлено за сутки: {deliveries.filter(status=DeliveryStatus.SENT, sent_at__gte=day).count()}.")
    if not check.summary:
        check.summary = "Сообщения о лимитах доставляются."
    return check
