"""Small resumable tasks; switches are rechecked when workers execute."""
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from apps.sources.models import Feed, SourceSubscription
from .cache import cleanup_sent
from .collection import collect_source, register_posts
from .editorial import assess
from .fill_collection import advance
from .initial_fill import ACTIVE_FILL
from .models import InitialFill, InitialFillAssessment, NewsAssessment, NewsConfiguration, NewsPublication
from .preparation import prepare
from .scheduling import due, select_publication
from .sending import deliver


def history_collecting(config):
    return InitialFill.objects.filter(target_id=config.target_id,
        status__in=("archive", "collecting", "assessing"), expires_at__gt=timezone.now()).exists()


@shared_task(name="news.tick")
def tick():
    config = NewsConfiguration.load()
    now = timezone.now()
    NewsPublication.objects.filter(status="sending", lease_until__lte=now).update(
        status="uncertain", lease_until=None,
        last_error="Воркер не сохранил квитанцию. Проверьте канал перед повтором.")
    expired = Q(initial_fill__isnull=True, event__expires_at__lte=now) | Q(initial_fill__expires_at__lte=now)
    NewsPublication.objects.filter(expired, status__in=("ready", "preparing")).update(
        status="blocked", lease_until=None, last_error="Новость устарела.")
    if settings.QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED:
        for pk in InitialFill.objects.filter(status__in=ACTIVE_FILL).values_list("pk", flat=True):
            advance_fill.delay(pk)
    if config.collection_enabled:
        if not history_collecting(config):
            for subscription in SourceSubscription.objects.filter(
                feed=Feed.NEWS, enabled=True, source__enabled=True,
            ).order_by("-priority", "pk"):
                collect.delay(subscription.pk)
        register_posts(config)
    if config.analysis_enabled:
        for pk in due(NewsAssessment.objects.filter(status__in=("pending", "running"))).filter(
            post__source__enabled=True, post__source__subscriptions__feed=Feed.NEWS,
            post__source__subscriptions__enabled=True,
        ).exclude(lease_until__gt=now).order_by("pk").values_list("pk", flat=True)[:30]:
            assess_post.delay(pk)
    if config.publishing_enabled:
        select_publication()
        for publication in due(NewsPublication.objects.filter(status__in=("preparing", "ready"))).exclude(
            lease_until__gt=now,
        ).order_by("-urgent", "pk")[:10]:
            task = prepare_post if publication.status == "preparing" else send_post
            task.apply_async(args=(publication.pk,), queue="news.urgent" if publication.urgent else "news.default")


@shared_task(name="news.collect")
def collect(subscription_id):
    config = NewsConfiguration.load()
    if not config.collection_enabled or not config.activated_at or history_collecting(config):
        return
    subscription = SourceSubscription.objects.select_related("source").filter(
        pk=subscription_id, feed=Feed.NEWS, enabled=True, source__enabled=True,
    ).first()
    if subscription:
        collect_source(subscription, config)
        register_posts(config)


@shared_task(name="news.assess")
def assess_post(assessment_id):
    if not settings.QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED and InitialFillAssessment.objects.filter(
        assessment_id=assessment_id).exists():
        return
    config = NewsConfiguration.load()
    if config.analysis_enabled and config.assessment_prompt and config.assessment_prompt.is_active:
        if NewsAssessment.objects.filter(pk=assessment_id, post__source__enabled=True,
            post__source__subscriptions__feed=Feed.NEWS, post__source__subscriptions__enabled=True).exists():
            assess(assessment_id, config)


@shared_task(name="news.prepare")
def prepare_post(publication_id):
    config = NewsConfiguration.load()
    if (config.publishing_enabled and config.writing_prompt and config.writing_prompt.is_active
            and config.verification_prompt and config.verification_prompt.is_active):
        prepare(publication_id, config)


@shared_task(name="news.send")
def send_post(publication_id):
    deliver(publication_id)


@shared_task(name="news.fill")
def advance_fill(run_id):
    advance(run_id, NewsConfiguration.load())


@shared_task(name="news.cleanup_media")
def cleanup_media():
    return cleanup_sent()
