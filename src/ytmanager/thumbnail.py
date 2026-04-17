from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from ytmanager.models import ThumbnailCaptureResult

MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
JPEG_SIGNATURES = (b"\xff\xd8\xff",)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
YOUTUBE_THUMBNAIL_HOST = "https://i.ytimg.com/vi"


def detect_image_mime(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(PNG_SIGNATURE):
        return "image/png"
    if any(header.startswith(signature) for signature in JPEG_SIGNATURES):
        return "image/jpeg"
    return "application/octet-stream"


def validate_thumbnail_file(path: Path) -> ThumbnailCaptureResult:
    if not path.exists():
        return ThumbnailCaptureResult(path, 0, "", False, "파일을 찾을 수 없습니다.")
    size = path.stat().st_size
    mime = detect_image_mime(path)
    if mime not in {"image/jpeg", "image/png"}:
        return ThumbnailCaptureResult(path, size, mime, False, "지원하지 않는 이미지 형식입니다.")
    if size > MAX_THUMBNAIL_BYTES:
        return ThumbnailCaptureResult(path, size, mime, False, "썸네일 파일은 2MB 이하여야 합니다.")
    if size == 0:
        return ThumbnailCaptureResult(path, size, mime, False, "빈 파일은 업로드할 수 없습니다.")
    return ThumbnailCaptureResult(path, size, mime, True, "업로드 가능한 썸네일 파일입니다.")


def public_thumbnail_url(video_id: str, *, quality: str = "maxresdefault", cache_bust: bool = False) -> str:
    """Return the public YouTube thumbnail URL used for post-upload visual checks.

    YouTube can take a short time to propagate a freshly uploaded thumbnail, so
    callers may append a cache-busting query parameter when opening the URL in a
    browser after `thumbnails.set`.
    """
    safe_quality = quality.strip("/") or "maxresdefault"
    url = f"{YOUTUBE_THUMBNAIL_HOST}/{video_id}/{safe_quality}.jpg"
    if cache_bust:
        query = urlencode({"ytmanager_preview": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")})
        return f"{url}?{query}"
    return url


def public_watch_url(video_id: str) -> str:
    """Return the public YouTube watch page URL for the selected video."""
    return f"https://www.youtube.com/watch?{urlencode({'v': video_id})}"
