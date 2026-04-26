from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

from ytmanager.models import RuleMapping
from ytmanager.rules import unique_tags

QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_PROCESSING = "processing"
QUEUE_STATUS_UPLOADED = "uploaded"
QUEUE_STATUS_FAILED = "failed"
DEFAULT_PRIVACY_STATUS = "private"
LOCAL_EDIT_AUTOSAVE_KEY = "local_edit_autosave_v1"
LOCAL_EDIT_AUTOSAVE_VERSION = 1
DEFAULT_FRAME_RATE = 30.0


class SettingsStore(Protocol):
    def get_setting(self, key: str, default: str = "") -> str:
        ...

    def set_setting(self, key: str, value: str) -> None:
        ...


@dataclass(frozen=True)
class LocalVideoProbe:
    duration_seconds: float
    width_pixels: int = 0
    height_pixels: int = 0
    created_at: str = ""
    modified_at: str = ""
    keyframes: tuple[float, ...] = ()
    frame_rate: float = DEFAULT_FRAME_RATE

    def effective_frame_rate(self, fallback: float = DEFAULT_FRAME_RATE) -> float:
        return self.frame_rate if self.frame_rate > 0 else fallback

    def to_payload(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "width_pixels": self.width_pixels,
            "height_pixels": self.height_pixels,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "keyframes": list(self.keyframes),
            "frame_rate": self.frame_rate,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LocalVideoProbe":
        return cls(
            duration_seconds=_safe_float(payload.get("duration_seconds")),
            width_pixels=_safe_int(payload.get("width_pixels")),
            height_pixels=_safe_int(payload.get("height_pixels")),
            created_at=str(payload.get("created_at", "")),
            modified_at=str(payload.get("modified_at", "")),
            keyframes=tuple(_safe_float(value) for value in payload.get("keyframes", []) or []),
            frame_rate=_safe_float(payload.get("frame_rate")) or DEFAULT_FRAME_RATE,
        )


@dataclass(frozen=True)
class SegmentCut:
    seconds: float


@dataclass
class SegmentDraft:
    index: int
    start_seconds: float
    end_seconds: float
    keep: bool = True
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy_status: str = DEFAULT_PRIVACY_STATUS
    thumbnail_path: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def to_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "keep": self.keep,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "privacy_status": self.privacy_status,
            "thumbnail_path": self.thumbnail_path,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SegmentDraft":
        return cls(
            index=_safe_int(payload.get("index")),
            start_seconds=_safe_float(payload.get("start_seconds")),
            end_seconds=_safe_float(payload.get("end_seconds")),
            keep=bool(payload.get("keep", True)),
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            tags=unique_tags(payload.get("tags", []) or []),
            privacy_status=str(payload.get("privacy_status", DEFAULT_PRIVACY_STATUS)) or DEFAULT_PRIVACY_STATUS,
            thumbnail_path=str(payload.get("thumbnail_path", "")),
        )


@dataclass
class UploadQueueItem:
    segment: SegmentDraft
    status: str = QUEUE_STATUS_PENDING
    output_path: Path | None = None
    uploaded_video_id: str = ""
    error_message: str = ""


@dataclass
class UploadProcessSummary:
    total: int
    succeeded: int
    failed: int
    items: list[UploadQueueItem] = field(default_factory=list)


@dataclass
class LocalSourceSession:
    source_path: Path
    probe: LocalVideoProbe
    game_title_prefix: str = ""
    game_display_name: str = ""
    title_text: str = ""
    date_text: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy_status: str = DEFAULT_PRIVACY_STATUS
    cuts: list[SegmentCut] = field(default_factory=list)
    segments: list[SegmentDraft] = field(default_factory=list)

    @property
    def title_preview(self) -> str:
        return build_segment_title(self.game_title_prefix, self.title_text, self.date_text)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "probe": self.probe.to_payload(),
            "game_title_prefix": self.game_title_prefix,
            "game_display_name": self.game_display_name,
            "title_text": self.title_text,
            "date_text": self.date_text,
            "description": self.description,
            "tags": list(self.tags),
            "privacy_status": self.privacy_status,
            "cuts": [cut.seconds for cut in self.cuts],
            "segments": [segment.to_payload() for segment in self.segments],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LocalSourceSession":
        probe_payload = payload.get("probe", {}) if isinstance(payload.get("probe"), dict) else {}
        cuts = [SegmentCut(seconds=_safe_float(value)) for value in payload.get("cuts", []) or []]
        segments = [
            SegmentDraft.from_payload(item)
            for item in (payload.get("segments", []) or [])
            if isinstance(item, dict)
        ]
        return cls(
            source_path=Path(str(payload.get("source_path", ""))),
            probe=LocalVideoProbe.from_payload(probe_payload),
            game_title_prefix=str(payload.get("game_title_prefix", "")),
            game_display_name=str(payload.get("game_display_name", "")),
            title_text=str(payload.get("title_text", "")),
            date_text=str(payload.get("date_text", "")),
            description=str(payload.get("description", "")),
            tags=unique_tags(payload.get("tags", []) or []),
            privacy_status=str(payload.get("privacy_status", DEFAULT_PRIVACY_STATUS)) or DEFAULT_PRIVACY_STATUS,
            cuts=cuts,
            segments=segments,
        )


class LocalUploadController:
    def __init__(
        self,
        rules: Sequence[RuleMapping],
        settings_store: SettingsStore | None = None,
        *,
        prober: Callable[..., LocalVideoProbe],
        splitter: Callable[..., list[Path]],
        uploader: Callable[..., dict[str, Any]],
    ) -> None:
        self.rules = list(rules)
        self.settings_store = settings_store
        self.prober = prober
        self.splitter = splitter
        self.uploader = uploader
        self.session: LocalSourceSession | None = None
        self.queue: list[UploadQueueItem] = []

    def media_root(self) -> Path:
        pinned = self._get_setting("pinned_media_root")
        if pinned:
            return Path(pinned)
        last_dir = self._get_setting("last_media_dir")
        if last_dir:
            return Path(last_dir)
        return Path.home()

    def set_pinned_media_root(self, path: Path | str) -> None:
        self._set_setting("pinned_media_root", str(Path(path)))

    def clear_pinned_media_root(self) -> None:
        self._set_setting("pinned_media_root", "")

    def load_source(self, source_path: Path | str, *, ffprobe_path: Path | str | None = None) -> LocalSourceSession:
        path = Path(source_path)
        probe = self.prober(path, ffprobe_path=ffprobe_path) if ffprobe_path is not None else self.prober(path)
        rule = self.rules[0] if self.rules else RuleMapping("", (), "")
        session = LocalSourceSession(
            source_path=path,
            probe=probe,
            game_title_prefix=rule.title_prefix,
            game_display_name=rule.display_name,
            date_text=probe.created_at or probe.modified_at,
            tags=list(rule.description_tags),
            privacy_status=DEFAULT_PRIVACY_STATUS,
        )
        self.session = session
        self._set_setting("last_media_dir", str(path.parent))
        self.rebuild_segments([])
        return session

    def restore_session(self, session: LocalSourceSession) -> LocalSourceSession:
        self.session = session
        self.fill_segment_defaults()
        self.build_queue()
        return session

    def update_common_metadata(
        self,
        *,
        game_title_prefix: str | None = None,
        title_text: str | None = None,
        date_text: str | None = None,
        description: str | None = None,
        tags: Iterable[str] | None = None,
        privacy_status: str | None = None,
    ) -> LocalSourceSession:
        session = self.require_session()
        if game_title_prefix is not None:
            session.game_title_prefix = game_title_prefix.strip()
            rule = find_rule_mapping(session.game_title_prefix, self.rules)
            session.game_display_name = rule.display_name if rule else session.game_title_prefix
            if tags is None and rule is not None:
                session.tags = list(rule.description_tags)
        if title_text is not None:
            session.title_text = title_text.strip()
        if date_text is not None:
            session.date_text = date_text.strip()
        if description is not None:
            session.description = description
        if tags is not None:
            session.tags = unique_tags(tags)
        if privacy_status is not None:
            session.privacy_status = privacy_status
        self.fill_segment_defaults()
        return session

    def rebuild_segments(self, cuts: Iterable[float] | None = None) -> list[SegmentDraft]:
        session = self.require_session()
        if cuts is not None:
            session.cuts = [SegmentCut(seconds=value) for value in normalize_cut_points(cuts, session.probe.duration_seconds)]
        preserved: dict[int, dict[str, Any]] = {}
        for segment in session.segments:
            preserved[segment.index] = {
                "keep": segment.keep,
                "title": segment.title,
                "description": segment.description,
                "tags": list(segment.tags),
                "privacy_status": segment.privacy_status,
                "thumbnail_path": segment.thumbnail_path,
            }
        boundaries = [0.0, *[cut.seconds for cut in session.cuts], session.probe.duration_seconds]
        session.segments = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            segment = SegmentDraft(index=index, start_seconds=start, end_seconds=end)
            previous = preserved.get(index)
            if previous is not None:
                segment.keep = bool(previous.get("keep", True))
                segment.title = str(previous.get("title", ""))
                segment.description = str(previous.get("description", ""))
                segment.tags = list(previous.get("tags", []))
                segment.privacy_status = str(previous.get("privacy_status", DEFAULT_PRIVACY_STATUS)) or DEFAULT_PRIVACY_STATUS
                segment.thumbnail_path = str(previous.get("thumbnail_path", ""))
            session.segments.append(segment)
        self.fill_segment_defaults()
        return session.segments

    def add_cut(self, seconds: float) -> list[SegmentDraft]:
        session = self.require_session()
        return self.rebuild_segments([*self.cut_seconds(session), seconds])

    def remove_cut(self, seconds: float, *, tolerance: float = 0.001) -> list[SegmentDraft]:
        session = self.require_session()
        remaining = [value for value in self.cut_seconds(session) if abs(value - seconds) > tolerance]
        return self.rebuild_segments(remaining)

    def cut_seconds(self, session: LocalSourceSession | None = None) -> list[float]:
        session = session or self.require_session()
        return [cut.seconds for cut in session.cuts]

    def fill_segment_defaults(self) -> None:
        session = self.require_session()
        total = max(1, len(session.segments))
        for segment in session.segments:
            if not segment.title:
                segment.title = build_segment_title(
                    session.game_title_prefix,
                    session.title_text,
                    session.date_text,
                    segment_index=segment.index,
                    segment_count=total,
                )
            if not segment.description:
                segment.description = session.description
            if not segment.tags:
                segment.tags = list(session.tags)
            if not segment.privacy_status:
                segment.privacy_status = session.privacy_status

    def overwrite_segment_defaults(self) -> None:
        session = self.require_session()
        total = max(1, len(session.segments))
        for segment in session.segments:
            segment.title = build_segment_title(
                session.game_title_prefix,
                session.title_text,
                session.date_text,
                segment_index=segment.index,
                segment_count=total,
            )
            segment.description = session.description
            segment.tags = list(session.tags)
            segment.privacy_status = session.privacy_status

    def update_segment(
        self,
        index: int,
        *,
        keep: bool | None = None,
        title: str | None = None,
        description: str | None = None,
        tags: Iterable[str] | None = None,
        privacy_status: str | None = None,
    ) -> SegmentDraft:
        segment = self.require_segment(index)
        if keep is not None:
            segment.keep = keep
        if title is not None:
            segment.title = title.strip()
        if description is not None:
            segment.description = description
        if tags is not None:
            segment.tags = unique_tags(tags)
        if privacy_status is not None:
            segment.privacy_status = privacy_status
        return segment

    def set_segment_thumbnail(self, index: int, thumbnail_path: Path | str) -> SegmentDraft:
        segment = self.require_segment(index)
        segment.thumbnail_path = str(thumbnail_path)
        return segment

    def build_queue(self) -> list[UploadQueueItem]:
        session = self.require_session()
        self.queue = [UploadQueueItem(segment=segment) for segment in session.segments if segment.keep]
        return self.queue

    def process_queue(
        self,
        youtube_client: Any,
        *,
        ffmpeg_path: Path | str,
        output_dir: Path,
        source_path: Path | None = None,
    ) -> UploadProcessSummary:
        session = self.require_session()
        if not self.queue:
            self.build_queue()
        succeeded = 0
        failed = 0
        for item in self.queue:
            item.status = QUEUE_STATUS_PROCESSING
            item.error_message = ""
            try:
                outputs = self.splitter(
                    source_path or session.source_path,
                    [item.segment],
                    output_dir,
                    Path(ffmpeg_path),
                )
                item.output_path = outputs[0]
                response = self.uploader(
                    youtube_client,
                    title=item.segment.title,
                    description=item.segment.description,
                    tags=item.segment.tags,
                    privacy_status=item.segment.privacy_status,
                    media_path=item.output_path,
                )
                item.uploaded_video_id = str(response.get("id", ""))
                item.status = QUEUE_STATUS_UPLOADED
                succeeded += 1
            except Exception as exc:
                item.status = QUEUE_STATUS_FAILED
                item.error_message = str(exc)
                failed += 1
        return UploadProcessSummary(total=len(self.queue), succeeded=succeeded, failed=failed, items=list(self.queue))

    def active_segment_index(self, seconds: float) -> int | None:
        session = self.require_session()
        for segment in session.segments:
            is_last = segment.index == len(session.segments)
            if segment.start_seconds <= seconds < segment.end_seconds or (is_last and seconds <= segment.end_seconds):
                return segment.index
        return None

    def keyframe_step_seconds(self, current_seconds: float, direction: int) -> float:
        session = self.require_session()
        keyframes = list(session.probe.keyframes)
        if not keyframes:
            return max(0.0, min(session.probe.duration_seconds, current_seconds))
        epsilon = 0.05
        if direction < 0:
            candidates = [value for value in keyframes if value < current_seconds - epsilon]
            return candidates[-1] if candidates else 0.0
        candidates = [value for value in keyframes if value > current_seconds + epsilon]
        return candidates[0] if candidates else session.probe.duration_seconds

    def export_autosave_payload(
        self,
        selected_segment_index: int | None = None,
        current_position_ms: int | None = None,
    ) -> dict[str, Any] | None:
        session = self.session
        if session is None:
            return None
        return {
            "version": LOCAL_EDIT_AUTOSAVE_VERSION,
            "selected_segment_index": selected_segment_index,
            "current_position_ms": current_position_ms,
            "session": session.to_payload(),
        }

    def save_autosave(self, selected_segment_index: int | None = None, current_position_ms: int | None = None) -> None:
        payload = self.export_autosave_payload(selected_segment_index, current_position_ms)
        if payload is None:
            return
        self._set_setting(LOCAL_EDIT_AUTOSAVE_KEY, json.dumps(payload, ensure_ascii=False))

    def clear_autosave(self) -> None:
        self._set_setting(LOCAL_EDIT_AUTOSAVE_KEY, "")

    def restore_autosave(self) -> tuple[LocalSourceSession, int | None, int | None] | None:
        raw = self._get_setting(LOCAL_EDIT_AUTOSAVE_KEY)
        if not raw.strip():
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.clear_autosave()
            return None
        if not isinstance(payload, dict) or payload.get("version") != LOCAL_EDIT_AUTOSAVE_VERSION:
            self.clear_autosave()
            return None
        session_payload = payload.get("session")
        if not isinstance(session_payload, dict):
            self.clear_autosave()
            return None
        session = LocalSourceSession.from_payload(session_payload)
        if not session.source_path.exists():
            self.clear_autosave()
            return None
        self.restore_session(session)
        selected_segment_index = payload.get("selected_segment_index")
        current_position_ms = payload.get("current_position_ms")
        return (
            session,
            _safe_int(selected_segment_index) if selected_segment_index is not None else None,
            _safe_int(current_position_ms) if current_position_ms is not None else None,
        )

    def require_session(self) -> LocalSourceSession:
        if self.session is None:
            raise RuntimeError("로컬 영상 세션이 아직 열리지 않았습니다.")
        return self.session

    def require_segment(self, index: int) -> SegmentDraft:
        session = self.require_session()
        for segment in session.segments:
            if segment.index == index:
                return segment
        raise IndexError(f"세그먼트 {index}번을 찾을 수 없습니다.")

    def _get_setting(self, key: str, default: str = "") -> str:
        if self.settings_store is None:
            return default
        return self.settings_store.get_setting(key, default)

    def _set_setting(self, key: str, value: str) -> None:
        if self.settings_store is None:
            return
        self.settings_store.set_setting(key, value)


def find_rule_mapping(title_prefix: str, rules: Sequence[RuleMapping]) -> RuleMapping | None:
    normalized = (title_prefix or "").strip().casefold()
    if not normalized:
        return None
    for rule in rules:
        if rule.title_prefix.strip().casefold() == normalized:
            return rule
    return None


def build_segment_title(
    title_prefix: str,
    title_text: str,
    date_text: str,
    *,
    segment_index: int = 1,
    segment_count: int = 1,
) -> str:
    prefix = title_prefix.strip()
    title = title_text.strip()
    date = date_text.strip()
    parts: list[str] = []
    if prefix:
        parts.append(f"[{prefix}]")
    if title:
        parts.append(title)
    if date:
        core = " ".join(parts).strip() or date
        label = f"{core} - {date}" if core != date else core
    else:
        label = " ".join(parts).strip()
    if segment_count > 1:
        suffix = f"({segment_index}/{segment_count})"
        label = f"{label} {suffix}".strip()
    return label.strip()


def normalize_cut_points(cut_points: Iterable[float], duration_seconds: float, *, epsilon: float = 0.001) -> list[float]:
    normalized: list[float] = []
    for raw_value in sorted(float(value) for value in cut_points):
        if raw_value <= epsilon or raw_value >= max(0.0, duration_seconds - epsilon):
            continue
        if normalized and abs(normalized[-1] - raw_value) <= epsilon:
            continue
        normalized.append(raw_value)
    return normalized


def upload_local_video_segment(
    youtube_client: Any,
    *,
    title: str,
    description: str,
    tags: Sequence[str],
    privacy_status: str,
    media_path: Path,
) -> dict[str, Any]:
    return youtube_client.upload_video(
        title=title,
        description=description,
        tags=list(tags),
        privacy_status=privacy_status,
        media_path=media_path,
    )


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
