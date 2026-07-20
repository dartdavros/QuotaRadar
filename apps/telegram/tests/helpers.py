from datetime import datetime, timezone

from apps.analysis.models import Analysis, AnalysisEventType, AnalysisProduct
from apps.sources.models import Source, SourcePost, SourceProvider


def create_relevant_analysis(*, external_id: str = "5001") -> Analysis:
    source = Source.objects.get(provider=SourceProvider.OPENAI)
    post = SourcePost.objects.create(
        source=source,
        external_id=external_id,
        text="Codex limits increased by 50%.",
        normalized_text="Codex limits increased by 50%.",
        source_url=f"https://x.com/OpenAIDevs/status/{external_id}",
        published_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        raw_data={},
    )
    return Analysis.objects.create(
        source_post=post,
        is_relevant=True,
        event_type=AnalysisEventType.QUOTA_INCREASE,
        provider=SourceProvider.OPENAI,
        product=AnalysisProduct.CODEX,
        title_ru="Codex: повышены лимиты",
        message_ru="OpenAI временно увеличила лимиты Codex на 50%.",
        model="test-model",
        prompt_version=1,
        raw_response={},
    )
