"""Prefer existing Telegram file IDs, then original URLs, then confirmed fallback uploads."""
from contextlib import ExitStack
from hashlib import sha256
import json
from apps.configuration.http_client import create_http_client, ExternalHttpRequestError
from apps.secrets.models import SecretCode
from apps.secrets.services import get_secret
from .media import validate_url
from .payload import publication_hash
from .receipts import (DeliveryUncertain, DeliveryRejected, DeliveryRateLimited, RemoteMediaRejected,
                       Receipt, file_receipts, parse_receipt)

def media_reference(asset, publication, bot_identity, index):
    if asset.telegram_file_id and asset.telegram_bot_identity == bot_identity:
        return asset.telegram_file_id
    if publication.upload_media:
        return f"attach://asset{index}"
    validate_url(asset.url)
    return asset.url

class NewsTransport:
    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.token = get_secret(SecretCode.NEWS_TELEGRAM_BOT_TOKEN)
            self.bot_identity = sha256(self.token.encode()).hexdigest()[:32]
            self.client = self.stack.enter_context(create_http_client(timeout_seconds=60))
        except Exception:
            self.stack.close()
            raise
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def prepare(self, publication):
        if not publication.payload_hash or publication_hash(publication) != publication.payload_hash:
            raise ValueError("Содержимое публикации изменилось после проверки.")
        assets = list(publication.media.all())
        references = [media_reference(asset, publication, self.bot_identity, index)
                      for index, asset in enumerate(assets)]
        payload = {"chat_id": publication.target.telegram_chat_id}
        files = {}
        for index, (asset, reference) in enumerate(zip(assets, references)):
            if not reference.startswith("attach://"):
                continue
            handle = self.stack.enter_context(asset.file.open("rb"))
            digest = sha256()
            while chunk := handle.read(65536):
                digest.update(chunk)
            handle.seek(0)
            if digest.hexdigest() != asset.checksum:
                raise ValueError("Сохранённое медиа повреждено.")
            mime = "image/png" if asset.file.name.endswith(".png") else "image/jpeg"
            files[f"asset{index}"] = (asset.file.name.rsplit("/", 1)[-1], handle,
                                     mime if asset.kind == "photo" else "video/mp4")
        if not assets:
            method = "sendMessage"
            payload.update(text=publication.rendered, parse_mode="HTML",
                           link_preview_options=json.dumps({"is_disabled": True}))
        elif len(assets) == 1:
            kind = assets[0].kind
            method = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation"}[kind]
            payload.update({kind: references[0], "caption": publication.rendered, "parse_mode": "HTML"})
        else:
            method = "sendMediaGroup"
            media = [{"type": asset.kind, "media": reference} for asset, reference in zip(assets, references)]
            media[0].update(caption=publication.rendered, parse_mode="HTML")
            payload["media"] = json.dumps(media)
        self.method, self.payload, self.files = method, payload, files
        self.assets = assets
        self.remote_media = any(reference.startswith("https://") for reference in references)

    def send(self):
        try:
            response = self.client.post(f"https://api.telegram.org/bot{self.token}/{self.method}",
                                       data=self.payload, files=self.files or None, follow_redirects=False)
        except ExternalHttpRequestError:
            raise DeliveryUncertain("Сеть оборвалась; проверьте канал перед повтором.") from None
        try:
            body = response.json()
        except (ValueError, TypeError):
            body = None
        ids = parse_receipt(response.status_code, body, max(1, len(self.assets)), remote_media=self.remote_media)
        return Receipt(ids, file_receipts(body, self.assets))
