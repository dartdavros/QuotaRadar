"""Use the existing proxy-backed LLM adapter with an independent schema."""
from copy import copy
import json

from apps.analysis.llm import OpenAICompatibleLlmClient
from apps.configuration.models import SystemConfiguration


def ask(config, *, prompt, schema, data):
    settings = copy(SystemConfiguration.load())
    settings.llm_timeout_seconds = min(settings.llm_timeout_seconds, 120)
    settings.llm_model = config.llm_model or settings.llm_model
    settings.llm_max_tokens = max(settings.llm_max_tokens, 2500)
    with OpenAICompatibleLlmClient(configuration=settings, response_model=schema) as client:
        response = client.analyze(system_prompt=prompt.system_prompt,
                                  user_prompt=prompt.user_prompt_template.replace("{data}", json.dumps(data, ensure_ascii=False)))
    return response.payload, settings.llm_model, response.raw_response.get("usage", {})
