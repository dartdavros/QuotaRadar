from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase
from redis import Redis

from apps.analysis.llm import LlmAnalysisResponse
from apps.analysis.models import Analysis, AnalysisEventType
from apps.analysis.schemas import AnalysisPayload
from apps.configuration.models import SystemConfiguration
from apps.monitoring.tasks import poll_source
from apps.monitoring.x_api import XTimelinePage
from apps.sources.models import Source, SourcePostProcessingStatus, SourceProvider
from apps.telegram.models import (
    Delivery,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryTargetType,
)


class _ContextResult(AbstractContextManager):
    def __init__(self, value: Any) -> None:
        self.value = value

    def __enter__(self) -> Any:
        return self.value

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


class _FakeXClient:
    def __init__(self, post: dict[str, Any]) -> None:
        self.post = post

    def iter_user_posts(
        self,
        user_id: str,
        *,
        since_id: str | None,
        max_results: int,
        max_pages: int | None = None,
    ):
        yield XTimelinePage(
            posts=(self.post,),
            includes={},
            meta={"result_count": 1},
            errors=(),
        )


@skipUnless(connection.vendor == "postgresql", "PostgreSQL integration test")
class EndToEndPipelineTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        self.redis = Redis.from_url(settings.REDIS_URL)
        try:
            self.redis.ping()
        except Exception:
            self.skipTest("Redis integration service is unavailable")
        self.redis.flushdb()

        configuration = SystemConfiguration.load()
        configuration.monitoring_enabled = True
        configuration.llm_provider = "openai_compatible"
        configuration.llm_base_url = "https://llm.example/v1"
        configuration.llm_model = "fixture-model"
        configuration.save()
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_e2e",
        )

    def tearDown(self) -> None:
        self.redis.flushdb()
        self.redis.close()

    def test_fixture_pipeline_covers_irrelevant_reset_increase_extension_and_duplicate(
        self,
    ) -> None:
        scenarios = (
            {
                "external_id": "8001",
                "provider": SourceProvider.OPENAI,
                "text": "General developer platform update.",
                "payload": {
                    "is_relevant": False,
                    "event_type": None,
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": None,
                    "message_ru": None,
                },
            },
            {
                "external_id": "8002",
                "provider": SourceProvider.OPENAI,
                "text": "Codex usage limits have reset for all users.",
                "payload": {
                    "is_relevant": True,
                    "event_type": "quota_reset",
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": "Codex: лимиты сброшены",
                    "message_ru": "OpenAI сообщила о массовом сбросе лимитов Codex.",
                },
            },
            {
                "external_id": "8003",
                "provider": SourceProvider.OPENAI,
                "text": "Weekly Codex limits are 50% higher.",
                "payload": {
                    "is_relevant": True,
                    "event_type": "quota_increase",
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": "Codex: повышены лимиты",
                    "message_ru": "OpenAI временно увеличила лимиты Codex на 50%.",
                },
            },
            {
                "external_id": "8004",
                "provider": SourceProvider.ANTHROPIC,
                "text": "The Claude Code boost is extended through August 19.",
                "payload": {
                    "is_relevant": True,
                    "event_type": "quota_extension",
                    "provider": "anthropic",
                    "product": "claude_code",
                    "title_ru": "Claude Code: повышение лимитов продлено",
                    "message_ru": "Anthropic продлила повышенные лимиты до 19 августа.",
                },
            },
        )
        telegram = Mock()
        telegram.send_message.side_effect = ["101", "102", "103"]

        for scenario in scenarios:
            source = Source.objects.get(provider=scenario["provider"])
            source.x_user_id = "1001" if source.provider == "openai" else "1002"
            source.save(update_fields=("x_user_id",))
            post = {
                "id": scenario["external_id"],
                "text": scenario["text"],
                "created_at": datetime(
                    2026, 7, 20, 10, 0, tzinfo=timezone.utc
                ).isoformat(),
                "author_id": source.x_user_id,
            }
            llm_response = LlmAnalysisResponse(
                payload=AnalysisPayload.model_validate(scenario["payload"]),
                raw_response={"fixture": scenario["external_id"]},
            )
            llm = Mock()
            llm.analyze.return_value = llm_response

            with (
                patch(
                    "apps.monitoring.tasks.XApiClient",
                    return_value=_ContextResult(_FakeXClient(post)),
                ),
                patch(
                    "apps.analysis.tasks.create_llm_client",
                    return_value=_ContextResult(llm),
                ),
                patch(
                    "apps.telegram.tasks.TelegramBotApiClient",
                    return_value=_ContextResult(telegram),
                ),
            ):
                result = poll_source.run(source.pk)

            self.assertEqual(result["status"], "ok")

        self.assertEqual(Analysis.objects.count(), 4)
        self.assertEqual(
            Analysis.objects.filter(
                is_relevant=True,
                delivery_fanout_completed_at__isnull=False,
            ).count(),
            3,
        )
        self.assertEqual(
            set(
                Analysis.objects.filter(is_relevant=True).values_list(
                    "event_type", flat=True
                )
            ),
            {
                AnalysisEventType.QUOTA_RESET,
                AnalysisEventType.QUOTA_INCREASE,
                AnalysisEventType.QUOTA_EXTENSION,
            },
        )
        self.assertEqual(Delivery.objects.count(), 3)
        self.assertEqual(
            Delivery.objects.filter(status=DeliveryStatus.SENT).count(),
            3,
        )
        self.assertEqual(telegram.send_message.call_count, 3)
        self.assertEqual(
            Analysis.objects.get(
                source_post__external_id="8001"
            ).source_post.processing_status,
            SourcePostProcessingStatus.ANALYZED_IRRELEVANT,
        )

        duplicate_source = Source.objects.get(provider=SourceProvider.OPENAI)
        duplicate_post = {
            "id": "8003",
            "text": "Weekly Codex limits are 50% higher.",
            "created_at": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc).isoformat(),
            "author_id": duplicate_source.x_user_id,
        }
        with patch(
            "apps.monitoring.tasks.XApiClient",
            return_value=_ContextResult(_FakeXClient(duplicate_post)),
        ):
            duplicate_result = poll_source.run(duplicate_source.pk)

        self.assertEqual(duplicate_result["created_posts"], 0)
        self.assertEqual(Delivery.objects.count(), 3)
        self.assertEqual(telegram.send_message.call_count, 3)
