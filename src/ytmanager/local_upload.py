from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence

from ytmanager.models import RuleMapping
from ytmanager.rules import unique_tags

QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_PROCESSING = "processing"
QUEUE_STATUS_UPLOADED = "uploaded"
QUEUE_STATUS_FAILED = "failed"
DEFAULT_PRIVACY_STATUS = "private"


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

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


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
        kept_titles: dict[int, tuple[bool, str, str, list[str], str]] = {}
        for segment in session.segments:
            kept_titles[segment.index] = (
                segment.keep,
                segment.title,
                segment.description,
                list(segment.tags),
                segment.privacy_status,
            )
        boundaries = [0.0, *[cut.seconds for cut in session.cuts], session.probe.duration_seconds]
        session.segments = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            segment = SegmentDraft(index=index, start_seconds=start, end_seconds=end)
            previous = kept_titles.get(index)
            if previous is not None:
                segment.keep, segment.title, segment.description, segment.tags, segment.privacy_status = previous
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
            except Exception as exc:  # 개별 실패는 기록 후 계속한다.
                item.status = QUEUE_STATUS_FAILED
                item.error_message = str(exc)
                failed += 1
        return UploadProcessSummary(total=len(self.queue), succeeded=succeeded, failed=failed, items=list(self.queue))

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
