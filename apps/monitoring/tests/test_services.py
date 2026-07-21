from datetime import datetime, timezone
from unittest.mock import Mock

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.monitoring.services import (
    PollResult,
    ingest_source_posts,
    resolve_source_user_ids,
)
from apps.monitoring.tests.helpers import load_json_fixture
from apps.monitoring.x_api import XApiResponseError, XApiTemporaryError, XTimelinePage
from apps.sources.models import Source, SourcePost


def page_from_fixture(name: str) -> XTimelinePage:
    payload = load_json_fixture(name)
    return XTimelinePage(
        posts=tuple(payload.get("data") or []),
        includes=payload.get("includes") or {},
        meta=payload.get("meta") or {},
        errors=tuple(payload.get("errors") or []),
    )


class SourceResolutionTests(TestCase):
    def test_resolves_all_trusted_user_ids(self) -> None:
        sources = list(Source.objects.order_by("pk"))
        client = Mock()
        client.lookup_users.return_value = {
            "openaidevs": "1001",
            "claudedevs": "2002",
            "sama": "3003",
            "thsottiaux": "4004",
        }

        result = resolve_source_user_ids(client=client, sources=sources)

        self.assertFalse(result.unresolved_source_ids)
        self.assertEqual(Source.objects.get(username="OpenAIDevs").x_user_id, "1001")
        self.assertEqual(Source.objects.get(username="ClaudeDevs").x_user_id, "2002")
        self.assertEqual(Source.objects.get(username="sama").x_user_id, "3003")
        self.assertEqual(Source.objects.get(username="thsottiaux").x_user_id, "4004")


class SourceIngestionTests(TestCase):
    def setUp(self) -> None:
        self.source = Source.objects.get(username="OpenAIDevs")
        self.source.x_user_id = "1001"
        self.source.last_post_id = "99"
        self.source.save()
        self.configuration = SystemConfiguration.load()
        self.pages = [
            page_from_fixture("timeline_page_1.json"),
            page_from_fixture("timeline_page_2.json"),
        ]

    def ingest(self, client: Mock) -> PollResult:
        return ingest_source_posts(self.source, client, self.configuration)

    def test_pagination_saves_oldest_to_newest_and_is_idempotent(self) -> None:
        client = Mock()
        client.iter_user_posts.return_value = iter(self.pages)

        first = self.ingest(client)
        self.source.refresh_from_db()

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id="99",
            max_results=5,
            max_pages=None,
        )
        self.assertEqual(first.created_posts, 3)
        self.assertEqual(first.ignored_retweets, 1)
        self.assertEqual(self.source.last_post_id, "105")
        self.assertEqual(SourcePost.objects.count(), 3)
        self.assertEqual(
            list(
                SourcePost.objects.order_by("received_at").values_list(
                    "external_id", flat=True
                )
            ),
            ["102", "103", "104"],
        )
        self.assertTrue(SourcePost.objects.filter(external_id="104").exists())
        self.assertFalse(SourcePost.objects.filter(external_id="105").exists())

        client.iter_user_posts.return_value = iter(self.pages)
        second = self.ingest(client)

        self.assertEqual(second.created_posts, 0)
        self.assertEqual(second.existing_posts, 3)
        self.assertEqual(SourcePost.objects.count(), 3)

    def test_bootstrap_fetches_only_ten_latest_posts_from_one_page(self) -> None:
        self.source.last_post_id = ""
        self.source.save(update_fields=("last_post_id",))
        client = Mock()
        client.iter_user_posts.return_value = iter([self.pages[0]])

        result = self.ingest(client)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id=None,
            max_results=10,
            max_pages=1,
        )
        self.assertEqual(result.pages, 1)
        self.assertEqual(result.created_posts, 1)
        self.assertEqual(result.ignored_retweets, 1)
        self.assertEqual(result.last_post_id, "105")

    def test_bootstrap_limit_comes_from_system_configuration(self) -> None:
        self.source.last_post_id = ""
        self.source.save(update_fields=("last_post_id",))
        self.configuration.bootstrap_post_limit = 25
        self.configuration.save(update_fields=("bootstrap_post_limit",))
        client = Mock()
        client.iter_user_posts.return_value = iter([self.pages[0]])

        self.ingest(client)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id=None,
            max_results=25,
            max_pages=1,
        )

    def test_regular_poll_limit_comes_from_system_configuration(self) -> None:
        self.configuration.regular_poll_post_limit = 20
        self.configuration.save(update_fields=("regular_poll_post_limit",))
        client = Mock()
        client.iter_user_posts.return_value = iter(self.pages)

        self.ingest(client)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id="99",
            max_results=20,
            max_pages=None,
        )

    def test_missing_cursor_is_recovered_from_existing_source_posts(self) -> None:
        self.source.last_post_id = ""
        self.source.save(update_fields=("last_post_id",))
        SourcePost.objects.create(
            source=self.source,
            external_id="98",
            text="Existing post",
            normalized_text="Existing post",
            source_url="https://x.com/OpenAIDevs/status/98",
            published_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            raw_data={},
        )
        client = Mock()
        client.iter_user_posts.return_value = iter(
            [XTimelinePage(posts=(), includes={}, meta={"result_count": 0}, errors=())]
        )

        result = self.ingest(client)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id="98",
            max_results=5,
            max_pages=None,
        )
        self.source.refresh_from_db()
        self.assertEqual(result.last_post_id, "98")
        self.assertEqual(self.source.last_post_id, "98")

    def test_long_text_quote_urls_article_and_alt_text_are_preserved(self) -> None:
        client = Mock()
        client.iter_user_posts.return_value = iter(self.pages)

        self.ingest(client)

        post = SourcePost.objects.get(external_id="103")
        self.assertEqual(
            post.text,
            "Weekly Codex limits are 50% higher through August 19 https://t.co/boost",
        )
        self.assertIn(
            "https://developers.openai.com/codex/limits", post.normalized_text
        )
        self.assertIn("Temporary quota boost", post.normalized_text)
        self.assertIn("Original announcement", post.normalized_text)
        self.assertIn("fifty percent increase", post.normalized_text)
        self.assertIn("original quota announcement", post.normalized_text)
        self.assertEqual(post.raw_data["post"]["id"], "103")
        self.assertEqual(
            post.raw_data["resolved_context"]["attached_media"][0]["media_key"], "3_700"
        )
        self.assertEqual(post.raw_data["meta"]["result_count"], 2)

    def test_failed_second_page_does_not_save_or_advance_cursor(self) -> None:
        client = Mock()

        def failing_pages():
            yield self.pages[0]
            raise XApiTemporaryError("temporary")

        client.iter_user_posts.return_value = failing_pages()

        with self.assertRaises(XApiTemporaryError):
            self.ingest(client)

        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "99")
        self.assertEqual(SourcePost.objects.count(), 0)

        client.iter_user_posts.return_value = iter(self.pages)
        self.ingest(client)
        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "105")
        self.assertEqual(SourcePost.objects.count(), 3)

    def test_cursor_never_moves_backwards(self) -> None:
        self.source.last_post_id = "200"
        self.source.save(update_fields=("last_post_id",))
        client = Mock()
        client.iter_user_posts.return_value = iter(self.pages)

        result = self.ingest(client)

        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "200")
        self.assertEqual(result.last_post_id, "200")

    def test_invalid_post_id_aborts_batch_without_advancing_cursor(self) -> None:
        invalid = XTimelinePage(
            posts=(
                {
                    "id": "not-a-snowflake",
                    "text": "invalid ID",
                    "created_at": "2026-07-20T10:06:00.000Z",
                },
            ),
            includes={},
            meta={"result_count": 1},
            errors=(),
        )
        client = Mock()
        client.iter_user_posts.return_value = iter([invalid])

        with self.assertRaises(XApiResponseError):
            self.ingest(client)

        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "99")
        self.assertEqual(SourcePost.objects.count(), 0)

    def test_malformed_post_aborts_batch_without_advancing_cursor(self) -> None:
        malformed = XTimelinePage(
            posts=({"id": "106", "text": "missing created_at"},),
            includes={},
            meta={"result_count": 1},
            errors=(),
        )
        client = Mock()
        client.iter_user_posts.return_value = iter([malformed])

        with self.assertRaises(XApiResponseError):
            self.ingest(client)

        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "99")
        self.assertEqual(SourcePost.objects.count(), 0)
