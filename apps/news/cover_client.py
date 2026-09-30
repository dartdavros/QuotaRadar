"""One proxy-backed OpenRouter image request; no automatic paid retries."""
import base64
import binascii
from dataclasses import dataclass
from urllib.parse import urlsplit

from apps.configuration.http_client import create_http_client
from apps.configuration.models import SystemConfiguration
from apps.secrets.models import SecretCode
from apps.secrets.services import get_secret
from .errors import NewsPolicyError


MODEL = "google/gemini-3.1-flash-image"
MAX_IMAGE_BYTES = 10_000_000


class CoverBlocked(NewsPolicyError):
    """A cover cannot be safely retried or published without an owner decision."""


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    model: str
    usage: dict


def validate_provider():
    try:
        parsed = urlsplit(SystemConfiguration.load().llm_base_url)
        valid = (parsed.scheme == "https" and parsed.hostname == "openrouter.ai"
            and parsed.path.rstrip("/") == "/api/v1" and parsed.port in (None, 443)
            and not (parsed.username or parsed.password or parsed.query or parsed.fragment))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise CoverBlocked("Для обложек требуется настроенный OpenRouter; другой провайдер не подставляется.")


def generate(prompt, reference):
    validate_provider()
    payload = {
        "model": MODEL, "prompt": prompt, "n": 1, "resolution": "1K", "aspect_ratio": "16:9",
        "input_references": [{"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(reference).decode("ascii")}}],
    }
    try:
        with create_http_client(timeout_seconds=240) as client:
            response = client.post("https://openrouter.ai/api/v1/images", json=payload,
                headers={"Authorization": "Bearer " + get_secret(SecretCode.LLM_API_KEY),
                         "Content-Type": "application/json"}, follow_redirects=False)
        if response.status_code != 200:
            raise CoverBlocked(f"OpenRouter не вернул обложку (HTTP {response.status_code}). Автоповтор отключён.")
        return parse_image(response.json())
    except CoverBlocked:
        raise
    except Exception:
        raise CoverBlocked("Результат генерации обложки неизвестен. Платный автоповтор отключён.") from None


def parse_image(body):
    if not isinstance(body, dict) or not isinstance(body.get("data"), list) or len(body["data"]) != 1:
        raise CoverBlocked("OpenRouter не вернул одно законченное изображение.")
    item = body["data"][0]
    if not isinstance(item, dict) or item.get("media_type") not in (None, "image/png", "image/jpeg", "image/webp"):
        raise CoverBlocked("OpenRouter вернул неподдерживаемый формат обложки.")
    encoded = item.get("b64_json")
    if not isinstance(encoded, str) or not encoded or len(encoded) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
        raise CoverBlocked("Пустая или слишком большая обложка.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise CoverBlocked("OpenRouter вернул повреждённое изображение.") from None
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise CoverBlocked("Пустая или слишком большая обложка.")
    usage = body.get("usage", {})
    return GeneratedImage(content=content, model=MODEL, usage=usage if isinstance(usage, dict) else {})
