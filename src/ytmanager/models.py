from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


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

    @classmethod
    def from_youtube_resource(cls, resource: Mapping[str, Any]) -> "VideoSummary":
        snippet = resource.get("snippet", {}) or {}
        status = resource.get("status", {}) or {}
        content = resource.get("contentDetails", {}) or {}
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
        )


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
