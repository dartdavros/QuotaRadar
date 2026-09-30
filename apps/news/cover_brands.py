"""Curated official assets for the main product, never a logo inferred from incidental mentions."""
import json
import re
from hashlib import sha256

from .cover_art import ASSETS
from .cover_client import CoverBlocked


PRODUCTS = (
    (r"claude code\b", "claude-code"),
    (r"(?:claude|opus|sonnet|haiku|fable|mythos)\b", "claude"),
    (r"anthropic\b", "anthropic"),
    (r"cursor\b", "cursor"),
    (r"(?:codex|chatgpt|gpt|openai|astra|sol|luna|sora)\b", "openai"),
    (r"(?:google|gemini|notebooklm|veo|imagen)\b", "google"),
)


def official_logo(product, posts):
    name = product.strip().casefold()
    brand = next((brand for pattern, brand in PRODUCTS if re.match(pattern, name)), None)
    if name == "pro subscription" and {post.source.provider for post in posts} == {"openai"}:
        brand = "openai"
    if brand is None:
        raise CoverBlocked("Нет утверждённого официального логотипа главного продукта новости.")
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest[brand]
    path = ASSETS / entry["file"]
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise CoverBlocked("Официальный логотип отсутствует или отличается от утверждённого ассета.")
    return brand, path
