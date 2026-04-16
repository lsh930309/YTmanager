from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class VideoSummary:
    video_id: str
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    thumbnail_url: str = ""
    duration: str = ""
    privacy_status: str = ""
    published_at: str = ""
    category_id: str = "22"
    width_pixels: int = 0
    height_pixels: int = 0
    display_aspect_ratio: float = 0.0

    @classmethod
    def from_youtube_resource(cls, resource: Mapping[str, Any]) -> "VideoSummary":
        snippet = resource.get("snippet", {}) or {}
        status = resource.get("status", {}) or {}
        content = resource.get("contentDetails", {}) or {}
        width, height, aspect_ratio = extract_video_dimensions(resource)
        thumbnails = snippet.get("thumbnails", {}) or {}
        thumb = ""
        for key in ("maxres", "standard", "high", "medium", "default"):
            if key in thumbnails and thumbnails[key].get("url"):
                thumb = thumbnails[key]["url"]
                break
        return cls(
            video_id=str(resource.get("id", "")),
            title=str(snippet.get("title", "")),
            description=str(snippet.get("description", "")),
            tags=tuple(snippet.get("tags", []) or []),
            thumbnail_url=thumb,
            duration=str(content.get("duration", "")),
            privacy_status=str(status.get("privacyStatus", "")),
            published_at=str(snippet.get("publishedAt", "")),
            category_id=str(snippet.get("categoryId", "22")),
            width_pixels=width,
            height_pixels=height,
            display_aspect_ratio=aspect_ratio,
        )

    def effective_aspect_ratio(self, fallback: float = 16 / 9) -> float:
        """GUI 재생 영역에 적용할 안전한 표시 비율을 반환한다."""
        if self.display_aspect_ratio > 0:
            return self.display_aspect_ratio
        if self.width_pixels > 0 and self.height_pixels > 0:
            return self.width_pixels / self.height_pixels
        return fallback

    def resolution_label(self) -> str:
        if self.width_pixels > 0 and self.height_pixels > 0:
            return f"{self.width_pixels}×{self.height_pixels}"
        return "16:9 기본 비율"


def extract_video_dimensions(resource: Mapping[str, Any]) -> tuple[int, int, float]:
    """YouTube fileDetails에서 가장 큰 비디오 스트림의 해상도/비율을 추출한다."""
    file_details = resource.get("fileDetails", {}) or {}
    streams = file_details.get("videoStreams", []) or []
    best_width = 0
    best_height = 0
    best_aspect = 0.0
    best_area = -1

    for stream in streams:
        width = _safe_int(stream.get("widthPixels"))
        height = _safe_int(stream.get("heightPixels"))
        aspect = _safe_float(stream.get("aspectRatio"))
        if width > 0 and height > 0:
            aspect = width / height
        area = width * height
        if area > best_area and (area > 0 or aspect > 0):
            best_width = width
            best_height = height
            best_aspect = aspect
            best_area = area

    return best_width, best_height, best_aspect


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class VideoDraft:
    video: VideoSummary
    edited_title: str
    edited_description: str
    edited_tags: list[str]
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_video(cls, video: VideoSummary) -> "VideoDraft":
        return cls(
            video=video,
            edited_title=video.title,
            edited_description=video.description,
            edited_tags=list(video.tags),
        )

    def has_changes(self) -> bool:
        return (
            self.edited_title != self.video.title
            or self.edited_description != self.video.description
            or tuple(self.edited_tags) != self.video.tags
        )


@dataclass(frozen=True)
class RuleMapping:
    title_prefix: str
    description_tags: tuple[str, ...]
    display_name: str = ""


@dataclass(frozen=True)
class TimestampEntry:
    seconds: float
    label: str = ""


@dataclass(frozen=True)
class ThumbnailCaptureResult:
    path: Path
    size_bytes: int
    mime_type: str
    can_upload: bool
    message: str = ""
