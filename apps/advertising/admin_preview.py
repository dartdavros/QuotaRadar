"""Read-only preview using the same parser and a real saved quota post."""
from html import escape

from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST

from apps.sources.models import Feed
from apps.telegram.formatting import DeliveryMessageError, format_delivery_message
from apps.telegram.models import Delivery, DeliveryTargetType
from .formatting import AD_LIMIT, AD_SEPARATOR, PREFIX, utf16_length
from .markup import render_markup


@require_POST
def preview_campaign(request):
    if not request.user.has_perm("advertising.change_campaign"):
        return HttpResponseForbidden()
    body = request.POST.get("body", "").strip()
    if not body:
        return JsonResponse({"html": "", "length": 0})
    try:
        rendered = render_markup(body)
        length = utf16_length(PREFIX.rstrip() + "\n" + rendered.text)
        if length > AD_LIMIT:
            raise ValidationError("Рекламный блок превышает 200 единиц UTF-16.")
    except ValidationError as error:
        return JsonResponse({"error": "; ".join(error.messages)}, status=400)

    block = f"{escape(PREFIX.rstrip())}<br>{rendered.html}"
    target_id = request.POST.get("target", "")
    if target_id.isdigit():
        delivery = (Delivery.objects.filter(target_id=target_id, target__feed=Feed.QUOTA,
                                            target__target_type=DeliveryTargetType.CHANNEL,
                                            analysis__is_relevant=True)
                    .select_related("analysis__source_post").order_by("-created_at").first())
        if delivery:
            try:
                post = format_delivery_message(delivery.analysis)
                if utf16_length(post) + utf16_length(AD_SEPARATOR) + AD_LIMIT <= 4096:
                    block = escape(post).replace("\n", "<br>") + "<br><br>" + block
            except DeliveryMessageError:
                pass
    return JsonResponse({"html": block, "length": length})
