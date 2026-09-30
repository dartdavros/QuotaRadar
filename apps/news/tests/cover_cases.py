"""Database setup shared only by isolated cover and preparation tests."""
from datetime import timedelta

from django.utils import timezone

from apps.sources.models import Source, SourcePost
from apps.telegram.models import DeliveryTarget
from apps.news.models import NewsConfiguration, NewsEvent, NewsEventEvidence, NewsPublication
from apps.news.schemas import WritingPayload


def make_publication():
    now = timezone.now()
    source = Source.objects.get(username="ClaudeDevs")
    post = SourcePost.objects.create(source=source, external_id="cover-test",
        text="Cloud sessions run on Anthropic-hosted infrastructure.",
        normalized_text="Cloud sessions run on Anthropic-hosted infrastructure.",
        published_at=now, source_url="https://x.com/ClaudeDevs/status/2102871552849322082", raw_data={})
    facts = [{"text": "Облачные сессии выполняются на инфраструктуре Anthropic.",
              "evidence": post.text}]
    event = NewsEvent.objects.create(fingerprint="cover-test", product="Claude Code", event_type="feature",
        score=90, facts=facts, first_seen_at=now, last_seen_at=now, expires_at=now+timedelta(hours=36))
    NewsEventEvidence.objects.create(event=event, post=post, facts=facts)
    target = DeliveryTarget.objects.create(target_type="channel", feed="news", telegram_chat_id="-100700")
    config = NewsConfiguration.load()
    config.target, config.publishing_enabled = target, True
    config.save()
    publication = NewsPublication.objects.create(event=event, target=target, attempts=1)
    writing = WritingPayload(title="Облачные сессии Claude Code работают на инфраструктуре Anthropic",
                             text="Облачная сессия выполняется на сервере Anthropic.")
    return publication, config, post, facts, writing
