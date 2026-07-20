from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.sources.models import Source, SourcePost, SourceProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def make_source_post(
    *,
    external_id: str = "9001",
    provider: str = SourceProvider.OPENAI,
    normalized_text: str = "Weekly Codex limits are 50% higher.",
) -> SourcePost:
    username = "OpenAIDevs" if provider == SourceProvider.OPENAI else "ClaudeDevs"
    source = Source.objects.get(username=username)
    return SourcePost.objects.create(
        source=source,
        external_id=external_id,
        text=normalized_text,
        normalized_text=normalized_text,
        source_url=f"https://x.com/{username}/status/{external_id}",
        published_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        raw_data={"post": {"id": external_id}},
    )
