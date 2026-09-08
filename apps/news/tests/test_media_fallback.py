"""Receipt and cache behavior without any HTTP backend or live send."""
from datetime import timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from apps.sources.models import Source, SourcePost
from apps.telegram.models import DeliveryTarget
from apps.news.cache import cleanup_sent
from apps.news.media import preserve
from apps.news.models import NewsEvent, NewsPublication, MediaAsset
from apps.news.payload import publication_hash
from apps.news.receipts import parse_receipt, file_receipts, RemoteMediaRejected, DeliveryRejected, DeliveryUncertain
from apps.news.transport import media_reference
from apps.news.sending import finish


class URLPolicyTests(SimpleTestCase):
    def test_reference_order_is_same_bot_file_id_url_then_explicit_upload(self):
        asset = SimpleNamespace(telegram_file_id="", telegram_bot_identity="", url="https://pbs.twimg.com/a.jpg")
        publication = SimpleNamespace(upload_media=False)
        self.assertEqual(media_reference(asset, publication, "bot", 0), asset.url)
        asset.telegram_file_id, asset.telegram_bot_identity = "telegram-id", "bot"
        self.assertEqual(media_reference(asset, publication, "bot", 0), "telegram-id")
        self.assertEqual(media_reference(asset, publication, "other-bot", 0), asset.url)
        publication.upload_media = True
        self.assertEqual(media_reference(asset, publication, "other-bot", 0), "attach://asset0")

    def test_only_definite_remote_download_failure_allows_upload(self):
        body = {"ok": False, "error_code": 400, "description": "Bad Request: failed to get HTTP URL content"}
        with self.assertRaises(RemoteMediaRejected):
            parse_receipt(400, body, 1, remote_media=True)
        with self.assertRaises(DeliveryRejected) as error:
            parse_receipt(400, body, 1)
        self.assertNotIsInstance(error.exception, RemoteMediaRejected)
        for status, reply in ((502, body), (200, None), (200, {"ok": True, "result": []})):
            with self.assertRaises(DeliveryUncertain):
                parse_receipt(status, reply, 1, remote_media=True)

    def test_unrelated_bad_request_does_not_allow_upload(self):
        with self.assertRaises(DeliveryRejected) as error:
            parse_receipt(400, {"ok": False, "error_code": 400, "description": "chat not found"}, 1, remote_media=True)
        self.assertNotIsInstance(error.exception, RemoteMediaRejected)

    def test_file_ids_are_optional_and_preserve_album_order(self):
        body = {"result": [
            {"photo": [{"file_id": "small"}, {"file_id": "large"}]},
            {"video": {"file_id": "video-id"}}, {"animation": None}]}
        assets = [SimpleNamespace(kind=kind) for kind in ("photo", "video", "animation")]
        self.assertEqual(file_receipts(body, assets), ["large", "video-id", ""])
        self.assertEqual(file_receipts({"result": {"photo": [None]}}, assets[:1]), [""])


class MediaCacheTests(TestCase):
    def setUp(self):
        source = Source.objects.get(username="OpenAIDevs")
        now = timezone.now()
        self.post = SourcePost.objects.create(source=source, external_id="990",
            text="Codex", normalized_text="Codex", published_at=now,
            source_url="https://x.com/OpenAIDevs/status/990",
            raw_data={"post": {"attachments": {"media_keys": ["photo"]}},
                "includes": {"media": [{"media_key": "photo", "type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]}})
        target = DeliveryTarget.objects.create(target_type="channel", feed="news", telegram_chat_id="-100777")
        event = NewsEvent.objects.create(fingerprint="990", product="Codex", event_type="feature",
            score=90, facts=[], first_seen_at=now, last_seen_at=now, expires_at=now+timedelta(hours=36))
        self.pub = NewsPublication.objects.create(event=event, target=target, rendered="Новость")
        preserve(self.pub, [self.post])
        self.asset = self.pub.media.get()

    def test_preparation_preserves_url_without_file_and_hash_ignores_cache(self):
        self.assertFalse(self.asset.file)
        frozen = publication_hash(self.pub)
        self.asset.telegram_file_id = "some-id"
        self.asset.file = "news/cached.jpg"
        self.asset.checksum = "a"*64
        self.asset.save()
        self.assertEqual(publication_hash(self.pub), frozen)
        self.asset.url = "https://pbs.twimg.com/changed.jpg"
        self.asset.save()
        self.assertNotEqual(publication_hash(self.pub), frozen)

    def test_cleanup_removes_only_confirmed_sent_cache_and_retains_identity(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            name = f"news/{self.pub.pk}-0-{'a'*12}.jpg"
            default_storage.save(name, ContentFile(b"temporary-original"))
            self.asset.file, self.asset.checksum = name, "a"*64
            self.asset.telegram_file_id = "telegram-id"
            self.asset.save()
            self.pub.status = "uncertain"
            self.pub.save()
            self.assertEqual(cleanup_sent(), 0)
            self.assertTrue(default_storage.exists(name))
            self.pub.status = "sent"
            self.pub.save()
            self.assertEqual(cleanup_sent(), 1)
            self.asset.refresh_from_db()
            self.assertFalse(self.asset.file)
            self.assertEqual(self.asset.telegram_file_id, "telegram-id")
            self.assertEqual(self.asset.checksum, "a"*64)

    def test_fallback_transition_never_reopens_unknown_delivery(self):
        self.pub.status = "sending"
        self.pub.save()
        finish(self.pub.pk, "ready", "URL rejected", upload_media=True)
        self.pub.refresh_from_db()
        self.assertTrue(self.pub.upload_media)
        self.assertEqual(self.pub.status, "ready")
        self.pub.status = "uncertain"
        self.pub.save()
        finish(self.pub.pk, "ready", "must not retry", upload_media=True)
        self.pub.refresh_from_db()
        self.assertEqual(self.pub.status, "uncertain")
