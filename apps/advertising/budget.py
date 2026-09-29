"""Reserve space during quota analysis whenever a channel campaign is active."""
from apps.sources.models import Feed
from apps.telegram.models import DeliveryTargetType
from .formatting import AD_SEPARATOR, MESSAGE_LIMIT, utf16_length


def quota_message_limit():
    # Lazy import keeps message formatting independent from Django model loading.
    from .models import Campaign
    active = Campaign.objects.filter(enabled=True, target__enabled=True,
                                     target__feed=Feed.QUOTA, target__target_type=DeliveryTargetType.CHANNEL)
    reserve = max((campaign.block_length + utf16_length(AD_SEPARATOR) for campaign in active), default=0)
    return max(0, MESSAGE_LIMIT - reserve)
