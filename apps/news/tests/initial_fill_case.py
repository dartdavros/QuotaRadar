"""Shared setup extracted from the historical-policy tests to keep files focused."""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from apps.sources.models import Source, SourcePost
from apps.telegram.models import DeliveryTarget
from apps.news.models import NewsAssessment, NewsConfiguration, NewsEvent, NewsEventEvidence


class InitialFillCase(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.source = Source.objects.get(username="OpenAIDevs")
        self.target = DeliveryTarget.objects.create(target_type="channel", feed="news", telegram_chat_id="-100909")
        self.config = NewsConfiguration.load()
        self.config.target = self.target
        self.config.collection_enabled = self.config.analysis_enabled = self.config.publishing_enabled = True
        self.config.save()

    def evidence(self, number, days=2, score=90, kind="tool_release", product="Codex"):
        date = self.now-timedelta(days=days)
        post = SourcePost.objects.create(source=self.source, external_id=str(number),
            text="Codex adds review.", normalized_text="Codex adds review.",
            source_url=f"https://x.com/OpenAIDevs/status/{number}", published_at=date, raw_data={})
        NewsAssessment.objects.create(post=post, status="done")
        event = NewsEvent.objects.create(fingerprint=str(number), product=product, version=str(number),
            event_type=kind, score=score, urgent=True, facts=[], first_seen_at=date, last_seen_at=date,
            expires_at=date+timedelta(hours=36))
        NewsEventEvidence.objects.create(event=event, post=post, facts=[])
        return event
