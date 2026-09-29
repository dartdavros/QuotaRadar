"""Read-only preview using the same parser and a real saved quota post."""
from html import escape

from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST

from apps.sources.models import Feed
from apps.telegram.formatting import DeliveryMessageError, format_delivery_message
from apps.telegram.models import Delivery, DeliveryTargetType
from .formatting import AD_SEPARATOR, MESSAGE_LIMIT, PREFIX, utf16_length, validate_body
from .models import Campaign


@require_POST
def preview_campaign(request):
    if not request.user.has_perm("advertising.change_campaign"):
        return HttpResponseForbidden()
    body = request.POST.get("body", "").strip()
    if not body:
        return JsonResponse({"html": "", "length": 0})
    try:
        campaign_id = request.POST.get("campaign", "")
        fallbacks = {}
        if campaign_id.isdigit():
            fallbacks = (Campaign.objects.filter(pk=campaign_id)
                         .values_list("emoji_fallbacks", flat=True).first() or {})
        rendered = validate_body(body, emoji_fallbacks=fallbacks)
        length = utf16_length(PREFIX.rstrip() + "\n" + rendered.text)
    except ValidationError as error:
        return JsonResponse({"error": "; ".join(error.messages)}, status=400)

    block = f"{escape(PREFIX.rstrip())}<br>{rendered.html}"
    target_id = request.POST.get("target", "")
    post_length = None
    if target_id.isdigit():
        delivery = (Delivery.objects.filter(target_id=target_id, target__feed=Feed.QUOTA,
                                            target__target_type=DeliveryTargetType.CHANNEL,
                                            analysis__is_relevant=True)
                    .select_related("analysis__source_post").order_by("-created_at").first())
        if delivery:
            try:
                post = format_delivery_message(delivery.analysis)
                post_length = utf16_length(post + AD_SEPARATOR) + length
                block = escape(post).replace("\n", "<br>") + "<br><br>" + block
            except DeliveryMessageError:
                pass
    warning = ""
    if post_length and post_length > MESSAGE_LIMIT:
        warning = "Этот сохранённый пост вместе с рекомендацией превышает лимит Telegram 4096. Текст не обрезан."
    return JsonResponse({"html": block, "length": length, "post_length": post_length,
                         "limit": MESSAGE_LIMIT, "warning": warning})
