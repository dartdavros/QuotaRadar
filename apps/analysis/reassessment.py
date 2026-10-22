"""One bounded second opinion for a suspicious negative classification."""

from apps.sources.models import SourcePost

from .availability import record_llm_failure, record_llm_success
from .llm import LlmAnalysisResponse, LlmError, OpenAICompatibleLlmClient
from .prompts import RenderedPrompt
from .quality import AnalysisQualityError, validate_payload_for_post
from .reset_signals import needs_reset_review

_REVIEW_INSTRUCTIONS = """Повторная оценка возможного ошибочного отказа:
В собственном тексте доверенного источника обнаружены признаки массового сброса
пользовательской квоты. Заново проверь объявление по исходному тексту и контексту.
@thsottiaux — утверждённый источник событий квот Codex. Его прямое объявление
о глобальном сбросе пользовательской квоты относится к Codex, даже если название
продукта и слова limits/tokens/usage опущены. «Global reset landing by EOD PST time.
Enjoy» и «Global reset by EOD. May the tokens do good things for you.» — объявления
предстоящего массового сброса, quota_reset. Это правило относится к подтверждённому
автору, а не к чужим цитатам или упоминаниям его аккаунта.
Отличай это от вопросов, предположений, сброса Git, настроек, инфраструктуры,
программного API или одного аккаунта. Родительский/процитированный пост — контекст,
а не новое объявление автора. Наличие слова reset само по себе недостаточно.
Не добавляй фактов или часового пояса, которых нет в публикации.
Верни результат в той же JSON Schema."""


class SuspiciousIrrelevanceError(AnalysisQualityError):
    """A reset signal remains unresolved; no successful rejection is persisted."""

    def __init__(self, *, detail: str, raw_response: object) -> None:
        super().__init__(f"Не подтверждена классификация массового сброса квоты: {detail}")
        self.raw_response = raw_response


def reassess_irrelevant_response(
    *,
    client: OpenAICompatibleLlmClient,
    prompt: RenderedPrompt,
    source_post: SourcePost,
    response: LlmAnalysisResponse,
) -> LlmAnalysisResponse:
    """Request at most one additional classification, retaining both responses."""

    if response.payload.is_relevant or not needs_reset_review(source_post):
        return response
    audit = {"initial_response": response.raw_response}
    try:
        reviewed = client.analyze(
            system_prompt=prompt.system_prompt + "\n\n" + _REVIEW_INSTRUCTIONS,
            user_prompt=prompt.user_prompt,
        )
    except LlmError as exc:
        record_llm_failure()
        audit["reassessment_response"] = getattr(exc, "raw_response", None)
        raise SuspiciousIrrelevanceError(
            detail=f"повторная оценка недоступна ({type(exc).__name__}).",
            raw_response=audit,
        ) from exc
    record_llm_success()
    audit["reassessment_response"] = reviewed.raw_response
    try:
        validate_payload_for_post(payload=reviewed.payload, source_post=source_post)
        if not reviewed.payload.is_relevant or reviewed.payload.event_type != "quota_reset":
            raise AnalysisQualityError("Повторная оценка не подтвердила quota_reset.")
    except AnalysisQualityError as exc:
        raise SuspiciousIrrelevanceError(detail=str(exc), raw_response=audit) from exc
    return LlmAnalysisResponse(
        payload=reviewed.payload,
        raw_response={**reviewed.raw_response, "irrelevance_review": audit},
    )
