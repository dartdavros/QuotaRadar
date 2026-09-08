"""Interpret Telegram responses without confusing download failure with unknown delivery."""
from dataclasses import dataclass

class DeliveryUncertain(RuntimeError):
    pass

class DeliveryRejected(RuntimeError):
    pass

class RemoteMediaRejected(DeliveryRejected):
    pass

class DeliveryRateLimited(RuntimeError):
    def __init__(self, seconds):
        self.seconds = max(1, min(int(seconds), 86400))

URL_ERRORS = (
    "failed to get http url content", "wrong type of the web page content",
    "webpage_curl_failed", "webpage_media_empty", "file is too big",
    "wrong file identifier/http url specified",
)

def parse_receipt(status, body, expected_count, *, remote_media=False):
    if status >= 500:
        raise DeliveryUncertain("Telegram 5xx: результат не подтверждён.")
    if isinstance(body, dict) and body.get("ok") is False:
        code = body.get("error_code", status)
        if type(code) is not int:
            raise DeliveryUncertain("Некорректный код ответа Telegram.")
        if code >= 500:
            raise DeliveryUncertain("Telegram сообщил ошибку сервера.")
        if code == 429:
            raise DeliveryRateLimited((body.get("parameters") or {}).get("retry_after", 60))
        description = str(body.get("description", "")).lower()
        if remote_media and status == 400 and code == 400 and any(reason in description for reason in URL_ERRORS):
            raise RemoteMediaRejected("Telegram не смог скачать оригинал по URL.")
        raise DeliveryRejected("Telegram отклонил публикацию.")
    if not isinstance(body, dict) or body.get("ok") is not True or not 200 <= status < 300:
        raise DeliveryUncertain("Некорректная квитанция Telegram.")
    result = body.get("result")
    messages = result if isinstance(result, list) else [result]
    if len(messages) != expected_count or any(
        not isinstance(m, dict) or type(m.get("message_id")) is not int for m in messages
    ):
        raise DeliveryUncertain("Telegram не подтвердил все сообщения публикации.")
    return [str(m["message_id"]) for m in messages]

@dataclass
class Receipt:
    message_ids: list
    file_ids: list

def file_receipts(body, assets):
    result = body["result"]
    messages = result if isinstance(result, list) else [result]
    file_ids = []
    for message, asset in zip(messages, assets):
        media = message.get(asset.kind)
        if asset.kind == "photo" and isinstance(media, list):
            photos = [photo for photo in media if isinstance(photo, dict) and isinstance(photo.get("file_id"), str)]
            media = photos[-1] if photos else {}
        value = media.get("file_id") if isinstance(media, dict) else None
        file_ids.append(value if isinstance(value, str) else "")
    return file_ids
