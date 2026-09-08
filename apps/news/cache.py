"""Worker-local temporary media; receipts, URLs and hashes remain in PostgreSQL."""
from hashlib import sha256
import re
from tempfile import SpooledTemporaryFile
from django.core.files import File
from django.core.files.storage import default_storage
from apps.configuration.http_client import create_http_client
from .errors import NewsPolicyError
from .media import LIMITS, validate_url
from .models import MediaAsset, NewsPublication

def download(asset):
    validate_url(asset.url)
    if asset.file and asset.checksum and asset.file.storage.exists(asset.file.name):
        return
    with SpooledTemporaryFile(max_size=2_000_000) as temporary:
        with create_http_client(timeout_seconds=30) as client:
            content_type = client.download_to(asset.url, temporary, max_bytes=LIMITS[asset.kind], max_seconds=90)
        temporary.seek(0)
        signature = temporary.read(16)
        photo = signature.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"))
        video = len(signature) >= 8 and signature[4:8] == b"ftyp"
        if not ((asset.kind == "photo" and photo and content_type in ("image/jpeg", "image/png"))
                or (asset.kind != "photo" and video and content_type == "video/mp4")):
            raise NewsPolicyError("Формат файла не соответствует оригинальному медиа.")
        temporary.seek(0)
        digest = sha256()
        while chunk := temporary.read(65536):
            digest.update(chunk)
        checksum = digest.hexdigest()
        if asset.checksum and checksum != asset.checksum:
            raise NewsPolicyError("Оригинал по URL изменился после первой загрузки.")
        asset.checksum, asset.size = checksum, temporary.tell()
        temporary.seek(0)
        extension = "mp4" if asset.kind != "photo" else ("png" if signature.startswith(b"\x89PNG") else "jpg")
        asset.file.save(f"{asset.publication_id}-{asset.position}-{checksum[:12]}.{extension}", File(temporary), save=False)
        asset.save(update_fields=("file", "checksum", "size"))

def ensure_uploads(publication, bot_identity):
    for asset in publication.media.all():
        if asset.telegram_file_id and asset.telegram_bot_identity == bot_identity:
            continue
        download(asset)

def cleanup_sent():
    """Each worker cleans its own disk, including copies made by another attempt."""
    try:
        _, names = default_storage.listdir("news")
    except FileNotFoundError:
        return 0
    candidates = {}
    for name in names:
        match = re.fullmatch(r"(\d+)-\d+-[a-f0-9]{12}(?:_[A-Za-z0-9]+)?\.(jpg|png|mp4)", name)
        if match:
            candidates[name] = int(match[1])
    sent = set(NewsPublication.objects.filter(pk__in=set(candidates.values()), status="sent").values_list("pk", flat=True))
    deleted = 0
    for name, pk in candidates.items():
        if pk in sent:
            path = f"news/{name}"
            default_storage.delete(path)
            MediaAsset.objects.filter(publication_id=pk, file=path).update(file="")
            deleted += 1
    return deleted
