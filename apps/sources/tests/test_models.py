from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.sources.models import (
    Source,
    SourcePost,
    SourcePostProcessingStatus,
    SourceProvider,
)


class SourceModelTests(TestCase):
    def test_initial_official_sources_exist(self) -> None:
        self.assertEqual(
            list(Source.objects.values_list("provider", "username")),
            [
                (SourceProvider.ANTHROPIC, "ClaudeDevs"),
                (SourceProvider.OPENAI, "OpenAIDevs"),
            ],
        )

    def test_external_post_id_is_globally_unique(self) -> None:
        openai = Source.objects.get(username="OpenAIDevs")
        claude = Source.objects.get(username="ClaudeDevs")
        defaults = {
            "text": "post",
            "normalized_text": "post",
            "source_url": "https://x.com/OpenAIDevs/status/123",
            "published_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
            "raw_data": {},
        }
        SourcePost.objects.create(source=openai, external_id="123", **defaults)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SourcePost.objects.create(source=claude, external_id="123", **defaults)

    def test_new_post_starts_received(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        post = SourcePost.objects.create(
            source=source,
            external_id="124",
            text="post",
            normalized_text="post",
            source_url="https://x.com/OpenAIDevs/status/124",
            published_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            raw_data={},
        )
        self.assertEqual(post.processing_status, SourcePostProcessingStatus.RECEIVED)
