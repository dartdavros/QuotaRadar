"""Editorial policy independent of fact verification and Telegram rendering."""
import re

from .errors import NewsPolicyError
from .schemas import (EditorialVerificationPayload, HistoricalEditorialVerificationPayload,
                      HistoricalVerificationPayload, VerificationPayload)


def verification_schema(config, historical):
    prompt = config.verification_prompt
    editorial = prompt.code == "news_verification" and prompt.version >= 3
    if editorial:
        return HistoricalEditorialVerificationPayload if historical else EditorialVerificationPayload
    return HistoricalVerificationPayload if historical else VerificationPayload


def validate_review(writing, verification):
    if not verification.supported:
        raise NewsPolicyError(f"Проверка фактов отклонила текст: {verification.reason}")
    if getattr(verification, "editorial_quality", True) is False:
        raise NewsPolicyError(f"Редактор отклонил текст: {verification.reason}")
    if re.search(r"\bвайбкодер\w*\b", f"{writing.title} {writing.text}", re.IGNORECASE):
        raise NewsPolicyError("Обращение к аудитории вместо конкретного содержания новости.")
