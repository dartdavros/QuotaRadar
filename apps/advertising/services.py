"""Reserve a channel slot and freeze the exact request before network I/O."""
from django.db import transaction
from django.utils import timezone

from apps.sources.models import Feed
from apps.telegram.models import Delivery, DeliveryStatus, DeliveryTarget, DeliveryTargetType
from .formatting import append_advertising
from .models import Campaign, HELD_STATUSES, Placement, PlacementStatus


def lock_target(delivery_id):
    target_id = Delivery.objects.values_list("target_id", flat=True).get(pk=delivery_id)
    return DeliveryTarget.objects.select_for_update().get(pk=target_id)


@transaction.atomic
def prepare_delivery(delivery, post):
    target = lock_target(delivery.pk)
    current = Delivery.objects.select_for_update().get(pk=delivery.pk)
    placement = Placement.objects.filter(delivery=current).first()
    if placement and placement.status == PlacementStatus.RELEASED:
        campaign = placement.campaign
        if campaign.placements.exclude(status=PlacementStatus.RELEASED).count() >= campaign.total_posts:
            raise ValueError("Для повтора рекламной доставки нет свободного размещения в кампании.")
        placement.status = PlacementStatus.RESERVED
        placement.save(update_fields=("status",))
    if current.rendered_text:
        return current.rendered_text, current.message_entities
    entities = []
    if target.feed == Feed.QUOTA and target.target_type == DeliveryTargetType.CHANNEL:
        campaign = Campaign.objects.filter(target=target, enabled=True).first()
        if campaign and campaign.placements.exclude(status=PlacementStatus.RELEASED).count() < campaign.total_posts:
            post, entities = append_advertising(post, campaign, current.analysis.source_post.source_url.strip())
            Placement.objects.create(campaign=campaign, delivery=current)
    current.rendered_text, current.message_entities = post, entities
    current.save(update_fields=("rendered_text", "message_entities", "updated_at"))
    return post, entities


@transaction.atomic
def begin_send(delivery_id):
    lock_target(delivery_id)
    placement = Placement.objects.filter(delivery_id=delivery_id).first()
    if not placement:
        return True
    if placement.status in (PlacementStatus.SENDING, PlacementStatus.UNCERTAIN):
        mark_uncertain(delivery_id, "Предыдущая попытка не подтверждена. Проверьте канал.")
        return False
    if placement.status != PlacementStatus.RESERVED:
        return False
    placement.status = PlacementStatus.SENDING
    placement.save(update_fields=("status",))
    return True


@transaction.atomic
def mark_uncertain(delivery_id, error):
    lock_target(delivery_id)
    Placement.objects.filter(delivery_id=delivery_id, status__in=HELD_STATUSES).update(status=PlacementStatus.UNCERTAIN)
    changed = Delivery.objects.filter(pk=delivery_id).exclude(status__in=(DeliveryStatus.SENT, DeliveryStatus.UNCERTAIN)).update(
        status=DeliveryStatus.UNCERTAIN, last_error=error, next_attempt_at=None, updated_at=timezone.now())
    if changed:
        from apps.monitoring.events import record_monitoring_event
        from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
        delivery = Delivery.objects.select_related("analysis__source_post__source").get(pk=delivery_id)
        record_monitoring_event(component=MonitoringComponent.TELEGRAM, status=MonitoringEventStatus.ERROR,
                                source=delivery.analysis.source_post.source,
                                message=f"Доставка {delivery_id}: {error}", error_type="AdvertisingDeliveryUncertain")


def has_advertising(delivery_id):
    return Placement.objects.filter(delivery_id=delivery_id).exists()


def unconfirmed_send(delivery_id):
    if Placement.objects.filter(delivery_id=delivery_id, status__in=(PlacementStatus.SENDING, PlacementStatus.UNCERTAIN)).exists():
        mark_uncertain(delivery_id, "Предыдущая попытка не подтверждена. Проверьте канал.")
        return True
    return False


def release(delivery_id):
    Placement.objects.filter(delivery_id=delivery_id, status__in=HELD_STATUSES).update(status=PlacementStatus.RELEASED)


def retry_reserved(delivery_id):
    Placement.objects.filter(delivery_id=delivery_id, status=PlacementStatus.SENDING).update(status=PlacementStatus.RESERVED)


def confirm_placement(delivery_id):
    placement = Placement.objects.filter(delivery_id=delivery_id).first()
    if not placement or placement.status == PlacementStatus.SENT:
        return
    placement.status, placement.sent_at = PlacementStatus.SENT, timezone.now()
    placement.save(update_fields=("status", "sent_at"))
    campaign = placement.campaign
    if campaign.sent_posts >= campaign.total_posts:
        Campaign.objects.filter(pk=campaign.pk).update(enabled=False)


@transaction.atomic
def resolve_placement(placement_id, *, was_sent):
    initial = Placement.objects.get(pk=placement_id)
    lock_target(initial.delivery_id)
    placement = Placement.objects.select_for_update().select_related("delivery").get(pk=placement_id)
    if placement.status != PlacementStatus.UNCERTAIN:
        raise ValueError("Проверка разрешена только для неподтверждённой отправки.")
    if not placement.resolution_note.strip():
        raise ValueError("Сначала запишите результат проверки канала.")
    from apps.telegram.delivery_state import mark_failed, mark_sent
    if was_sent:
        if not placement.telegram_message_id.isdigit() or int(placement.telegram_message_id) < 1:
            raise ValueError("Укажите Telegram message ID найденного поста.")
        mark_sent(placement.delivery_id, placement.telegram_message_id)
    else:
        mark_failed(placement.delivery_id, "Проверено владельцем: пост отсутствует в канале.")
