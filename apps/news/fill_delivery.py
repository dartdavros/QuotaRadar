"""Hold the seeded history until the run is fully chosen, then release it oldest first."""
from datetime import timedelta

from django.db.models import Min

from .initial_fill import FILL_LIMIT, remaining
from .models import NewsDelivery

FILL_GAP = timedelta(seconds=30)


def frozen(run):
    """True once no further publication can join the run, so the set can no longer reorder."""
    if run.status not in ("publishing", "completed"):
        return False
    if run.publications.filter(status="preparing").exists():
        return False
    return run.publications.exclude(status="blocked").count() >= FILL_LIMIT or not remaining(run)


def fill_ready(publication, now):
    """One settled set, oldest event first, never closer together than FILL_GAP."""
    run = publication.initial_fill
    if not frozen(run):
        return False
    nearest = run.publications.exclude(status__in=("sent", "blocked")).annotate(
        happened=Min("event__evidence__post__published_at")).order_by("happened", "pk").values_list("pk", flat=True).first()
    if nearest != publication.pk:
        return False
    previous = NewsDelivery.objects.filter(
        publication__initial_fill=run, sent_at__isnull=False).order_by("-sent_at").first()
    return previous is None or now-previous.sent_at >= FILL_GAP
