from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ytmanager.character_status import UNKNOWN_RANK_VALUE, extract_video_date, game_key_from_title_prefix
from ytmanager.models import VideoSummary
from ytmanager.paths import default_database_path
from ytmanager.rules import extract_title_prefix

DRAFT_STATUS_SKIPPED = "skipped"
DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_REVIEWED = "reviewed"
DRAFT_STATUS_APPLIED = "applied"
DRAFT_STATUS_ERROR = "error"
PROTECTED_DRAFT_STATUSES = {DRAFT_STATUS_REVIEWED, DRAFT_STATUS_APPLIED}

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    thumbnail_url TEXT NOT NULL,
    duration TEXT NOT NULL,
    privacy_status TEXT NOT NULL,
    published_at TEXT NOT NULL,
    category_id TEXT NOT NULL,
    width_pixels INTEGER NOT NULL DEFAULT 0,
    height_pixels INTEGER NOT NULL DEFAULT 0,
    display_aspect_ratio REAL NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metadata_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS description_drafts (
    video_id TEXT PRIMARY KEY,
    template_name TEXT NOT NULL,
    status TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    timestamps_json TEXT NOT NULL,
    top_tags_json TEXT NOT NULL,
    rendered_description TEXT NOT NULL,
    parse_confidence TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    unmatched_json TEXT NOT NULL,
    error_message TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    applied_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_aliases (
    game_key TEXT NOT NULL,
    alias TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (game_key, alias)
);

CREATE TABLE IF NOT EXISTS character_roster (
    game_key TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    character_rank_value INTEGER NOT NULL DEFAULT -1,
    character_rank_label TEXT NOT NULL DEFAULT '',
    equipment_type TEXT NOT NULL DEFAULT '',
    equipment_rank_value INTEGER NOT NULL DEFAULT -1,
    equipment_rank_label TEXT NOT NULL DEFAULT '',
    first_observed_date TEXT NOT NULL DEFAULT '',
    last_observed_date TEXT NOT NULL DEFAULT '',
    source_video_id TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT '',
    needs_alias_review INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (game_key, canonical_name)
);

CREATE TABLE IF NOT EXISTS character_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_key TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    observed_date TEXT NOT NULL DEFAULT '',
    character_rank_value INTEGER NOT NULL DEFAULT -1,
    character_rank_label TEXT NOT NULL DEFAULT '',
    equipment_type TEXT NOT NULL DEFAULT '',
    equipment_rank_value INTEGER NOT NULL DEFAULT -1,
    equipment_rank_label TEXT NOT NULL DEFAULT '',
    raw_status TEXT NOT NULL DEFAULT '',
    needs_alias_review INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class DescriptionDraftRecord:
    video_id: str
    template_name: str = "combat"
    status: str = DRAFT_STATUS_DRAFT
    fields: dict[str, str] = field(default_factory=dict)
    sections: list[dict[str, object]] = field(default_factory=list)
    timestamps: list[dict[str, object]] = field(default_factory=list)
    top_tags: list[str] = field(default_factory=list)
    rendered_description: str = ""
    parse_confidence: str = ""
    warnings: list[str] = field(default_factory=list)
    unmatched_lines: list[str] = field(default_factory=list)
    error_message: str = ""
    reviewed_at: str | None = None
    applied_at: str | None = None
    updated_at: str = ""

    @property
    def is_reviewed(self) -> bool:
        return self.status == DRAFT_STATUS_REVIEWED

    @property
    def is_applied(self) -> bool:
        return self.status == DRAFT_STATUS_APPLIED


@dataclass(frozen=True)
class CharacterRosterRecord:
    game_key: str
    canonical_name: str
    display_name: str
    character_rank_value: int = UNKNOWN_RANK_VALUE
    character_rank_label: str = ""
    equipment_type: str = ""
    equipment_rank_value: int = UNKNOWN_RANK_VALUE
    equipment_rank_label: str = ""
    first_observed_date: str = ""
    last_observed_date: str = ""
    source_video_id: str = ""
    source_title: str = ""
    needs_alias_review: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AppDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.connection.executescript(SCHEMA)
        self._ensure_video_columns()
        self._ensure_description_draft_columns()
        self._ensure_character_roster_columns()
        self.connection.commit()

    def _ensure_video_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(videos)").fetchall()}
        migrations = {
            "width_pixels": "ALTER TABLE videos ADD COLUMN width_pixels INTEGER NOT NULL DEFAULT 0",
            "height_pixels": "ALTER TABLE videos ADD COLUMN height_pixels INTEGER NOT NULL DEFAULT 0",
            "display_aspect_ratio": "ALTER TABLE videos ADD COLUMN display_aspect_ratio REAL NOT NULL DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.connection.execute(sql)

    def _ensure_description_draft_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(description_drafts)").fetchall()}
        migrations = {
            "top_tags_json": "ALTER TABLE description_drafts ADD COLUMN top_tags_json TEXT NOT NULL DEFAULT '[]'",
            "error_message": "ALTER TABLE description_drafts ADD COLUMN error_message TEXT NOT NULL DEFAULT ''",
            "reviewed_at": "ALTER TABLE description_drafts ADD COLUMN reviewed_at TEXT",
            "applied_at": "ALTER TABLE description_drafts ADD COLUMN applied_at TEXT",
            "updated_at": "ALTER TABLE description_drafts ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.connection.execute(sql)

    def _ensure_character_roster_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(character_roster)").fetchall()}
        migrations = {
            "needs_alias_review": "ALTER TABLE character_roster ADD COLUMN needs_alias_review INTEGER NOT NULL DEFAULT 1",
            "source_title": "ALTER TABLE character_roster ADD COLUMN source_title TEXT NOT NULL DEFAULT ''",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.connection.execute(sql)

    def close(self) -> None:
        self.connection.close()

    def save_videos(self, videos: Iterable[VideoSummary]) -> None:
        with self.connection:
            for video in videos:
                self.connection.execute(
                    """
                    INSERT INTO videos (
                        video_id, title, description, tags_json, thumbnail_url,
                        duration, privacy_status, published_at, category_id,
                        width_pixels, height_pixels, display_aspect_ratio, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        tags_json = excluded.tags_json,
                        thumbnail_url = excluded.thumbnail_url,
                        duration = excluded.duration,
                        privacy_status = excluded.privacy_status,
                        published_at = excluded.published_at,
                        category_id = excluded.category_id,
                        width_pixels = excluded.width_pixels,
                        height_pixels = excluded.height_pixels,
                        display_aspect_ratio = excluded.display_aspect_ratio,
                        synced_at = CURRENT_TIMESTAMP
                    """,
                    (
                        video.video_id,
                        video.title,
                        video.description,
                        json.dumps(list(video.tags), ensure_ascii=False),
                        video.thumbnail_url,
                        video.duration,
                        video.privacy_status,
                        video.published_at,
                        video.category_id,
                        video.width_pixels,
                        video.height_pixels,
                        video.display_aspect_ratio,
                    ),
                )

    def list_videos(self) -> list[VideoSummary]:
        rows = self.connection.execute("SELECT * FROM videos ORDER BY published_at DESC, synced_at DESC").fetchall()
        return [self._video_from_row(row) for row in rows]

    def get_video(self, video_id: str) -> Optional[VideoSummary]:
        row = self.connection.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return self._video_from_row(row) if row else None

    def _video_from_row(self, row: sqlite3.Row) -> VideoSummary:
        return VideoSummary(
            video_id=row["video_id"],
            title=row["title"],
            description=row["description"],
            tags=tuple(json.loads(row["tags_json"])),
            thumbnail_url=row["thumbnail_url"],
            duration=row["duration"],
            privacy_status=row["privacy_status"],
            published_at=row["published_at"],
            category_id=row["category_id"],
            width_pixels=row["width_pixels"],
            height_pixels=row["height_pixels"],
            display_aspect_ratio=row["display_aspect_ratio"],
        )

    def save_snapshot(self, video: VideoSummary) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO metadata_snapshots (video_id, title, description, tags_json)
                VALUES (?, ?, ?, ?)
                """,
                (video.video_id, video.title, video.description, json.dumps(list(video.tags), ensure_ascii=False)),
            )

    def save_description_draft(self, draft: DescriptionDraftRecord, preserve_reviewed: bool = True) -> bool:
        existing = self.get_description_draft(draft.video_id)
        if preserve_reviewed and existing and existing.status in PROTECTED_DRAFT_STATUSES:
            return False
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO description_drafts (
                    video_id, template_name, status, fields_json, sections_json,
                    timestamps_json, top_tags_json, rendered_description, parse_confidence,
                    warnings_json, unmatched_json, error_message, reviewed_at, applied_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    template_name = excluded.template_name,
                    status = excluded.status,
                    fields_json = excluded.fields_json,
                    sections_json = excluded.sections_json,
                    timestamps_json = excluded.timestamps_json,
                    top_tags_json = excluded.top_tags_json,
                    rendered_description = excluded.rendered_description,
                    parse_confidence = excluded.parse_confidence,
                    warnings_json = excluded.warnings_json,
                    unmatched_json = excluded.unmatched_json,
                    error_message = excluded.error_message,
                    reviewed_at = excluded.reviewed_at,
                    applied_at = excluded.applied_at,
                    updated_at = excluded.updated_at
                """,
                (
                    draft.video_id,
                    draft.template_name,
                    draft.status,
                    _json_dumps(draft.fields),
                    _json_dumps(draft.sections),
                    _json_dumps(draft.timestamps),
                    _json_dumps(draft.top_tags),
                    draft.rendered_description,
                    draft.parse_confidence,
                    _json_dumps(draft.warnings),
                    _json_dumps(draft.unmatched_lines),
                    draft.error_message,
                    draft.reviewed_at,
                    draft.applied_at,
                    now,
                ),
            )
        return True

    def get_description_draft(self, video_id: str) -> Optional[DescriptionDraftRecord]:
        row = self.connection.execute("SELECT * FROM description_drafts WHERE video_id = ?", (video_id,)).fetchone()
        return self._draft_from_row(row) if row else None

    def list_description_drafts(self) -> list[DescriptionDraftRecord]:
        rows = self.connection.execute("SELECT * FROM description_drafts ORDER BY updated_at DESC").fetchall()
        return [self._draft_from_row(row) for row in rows]

    def draft_status_map(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT video_id, status FROM description_drafts").fetchall()
        return {row["video_id"]: row["status"] for row in rows}

    def list_apply_ready_drafts(self) -> list[tuple[VideoSummary, DescriptionDraftRecord]]:
        rows = self.connection.execute(
            """
            SELECT videos.*, description_drafts.*
            FROM description_drafts
            JOIN videos ON videos.video_id = description_drafts.video_id
            WHERE description_drafts.status = ?
              AND trim(description_drafts.rendered_description) != trim(videos.description)
            ORDER BY videos.published_at DESC, description_drafts.updated_at DESC
            """,
            (DRAFT_STATUS_REVIEWED,),
        ).fetchall()
        return [(self._video_from_joined_row(row), self._draft_from_row(row)) for row in rows]

    def mark_draft_reviewed(self, video_id: str) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE description_drafts
                SET status = ?, reviewed_at = ?, error_message = '', updated_at = ?
                WHERE video_id = ?
                """,
                (DRAFT_STATUS_REVIEWED, now, now, video_id),
            )

    def mark_draft_status(self, video_id: str, status: str, error_message: str = "") -> None:
        now = utc_now_iso()
        applied_at = now if status == DRAFT_STATUS_APPLIED else None
        with self.connection:
            self.connection.execute(
                """
                UPDATE description_drafts
                SET status = ?, error_message = ?, applied_at = COALESCE(?, applied_at), updated_at = ?
                WHERE video_id = ?
                """,
                (status, error_message, applied_at, now, video_id),
            )

    def upsert_character_alias(self, game_key: str, canonical_name: str, aliases: Iterable[str], source: str = "manual") -> None:
        now = utc_now_iso()
        with self.connection:
            for alias in {canonical_name, *aliases}:
                alias = str(alias).strip()
                if not alias:
                    continue
                self.connection.execute(
                    """
                    INSERT INTO character_aliases (game_key, alias, canonical_name, source, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(game_key, alias) DO UPDATE SET
                        canonical_name = excluded.canonical_name,
                        source = excluded.source,
                        updated_at = excluded.updated_at
                    """,
                    (game_key, alias, canonical_name, source, now),
                )

    def load_character_aliases_from_file(self, path: Path) -> int:
        if not path.exists():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for game_key, characters in raw.items():
            if not isinstance(characters, dict):
                continue
            for canonical_name, aliases in characters.items():
                alias_list = aliases if isinstance(aliases, list) else []
                self.upsert_character_alias(str(game_key), str(canonical_name), [str(alias) for alias in alias_list], source=str(path))
                count += 1
        return count

    def resolve_character_alias(self, game_key: str, raw_name: str) -> tuple[str, bool]:
        row = self.connection.execute(
            "SELECT canonical_name FROM character_aliases WHERE game_key = ? AND alias = ?",
            (game_key, raw_name),
        ).fetchone()
        if row:
            return row["canonical_name"], False
        return raw_name, True

    def observe_draft_roster(self, video: VideoSummary, draft: DescriptionDraftRecord) -> int:
        game_key = game_key_from_title_prefix(extract_title_prefix(video.title))
        if not game_key:
            return 0
        observed_date = extract_video_date(video.title, video.published_at)
        count = 0
        for section in draft.sections:
            if not isinstance(section, dict):
                continue
            party = section.get("party", [])
            if not isinstance(party, list):
                continue
            for member in party:
                if isinstance(member, dict) and self._insert_character_observation(video, game_key, observed_date, member):
                    count += 1
        return count

    def _insert_character_observation(self, video: VideoSummary, game_key: str, observed_date: str, member: dict[str, object]) -> bool:
        raw_name = str(member.get("raw_name") or member.get("character") or "").strip()
        if not raw_name:
            return False
        canonical_name, needs_alias_review = self.resolve_character_alias(game_key, raw_name)
        character_rank_value = _safe_int(member.get("character_rank_value"), UNKNOWN_RANK_VALUE)
        equipment_rank_value = _safe_int(member.get("equipment_rank_value"), UNKNOWN_RANK_VALUE)
        character_rank_label = str(member.get("character_rank") or "").strip()
        equipment_type = str(member.get("equipment_type") or "").strip()
        equipment_rank_label = str(member.get("equipment_rank") or "").strip()
        raw_status = str(member.get("raw_status") or member.get("m_level") or "").strip()
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO character_observations (
                    game_key, raw_name, canonical_name, video_id, title, observed_date,
                    character_rank_value, character_rank_label, equipment_type,
                    equipment_rank_value, equipment_rank_label, raw_status,
                    needs_alias_review, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_key,
                    raw_name,
                    canonical_name,
                    video.video_id,
                    video.title,
                    observed_date,
                    character_rank_value,
                    character_rank_label,
                    equipment_type,
                    equipment_rank_value,
                    equipment_rank_label,
                    raw_status,
                    int(needs_alias_review),
                    now,
                ),
            )
            self._upsert_character_roster(
                game_key=game_key,
                canonical_name=canonical_name,
                display_name=canonical_name,
                character_rank_value=character_rank_value,
                character_rank_label=character_rank_label,
                equipment_type=equipment_type,
                equipment_rank_value=equipment_rank_value,
                equipment_rank_label=equipment_rank_label,
                observed_date=observed_date,
                source_video_id=video.video_id,
                source_title=video.title,
                needs_alias_review=needs_alias_review,
                now=now,
            )
        return True

    def _upsert_character_roster(
        self,
        game_key: str,
        canonical_name: str,
        display_name: str,
        character_rank_value: int,
        character_rank_label: str,
        equipment_type: str,
        equipment_rank_value: int,
        equipment_rank_label: str,
        observed_date: str,
        source_video_id: str,
        source_title: str,
        needs_alias_review: bool,
        now: str,
    ) -> None:
        existing = self.connection.execute(
            "SELECT * FROM character_roster WHERE game_key = ? AND canonical_name = ?",
            (game_key, canonical_name),
        ).fetchone()
        if not existing:
            self.connection.execute(
                """
                INSERT INTO character_roster (
                    game_key, canonical_name, display_name, character_rank_value,
                    character_rank_label, equipment_type, equipment_rank_value,
                    equipment_rank_label, first_observed_date, last_observed_date,
                    source_video_id, source_title, needs_alias_review, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_key,
                    canonical_name,
                    display_name,
                    character_rank_value,
                    character_rank_label,
                    equipment_type,
                    equipment_rank_value,
                    equipment_rank_label,
                    observed_date,
                    observed_date,
                    source_video_id,
                    source_title,
                    int(needs_alias_review),
                    now,
                ),
            )
            return

        best_character_value = max(existing["character_rank_value"], character_rank_value)
        best_equipment_value = max(existing["equipment_rank_value"], equipment_rank_value)
        character_label = character_rank_label if character_rank_value > existing["character_rank_value"] else existing["character_rank_label"]
        equipment_label = equipment_rank_label if equipment_rank_value > existing["equipment_rank_value"] else existing["equipment_rank_label"]
        equipment_type_value = equipment_type if equipment_rank_value > existing["equipment_rank_value"] and equipment_type else existing["equipment_type"]
        if not equipment_type_value and equipment_type:
            equipment_type_value = equipment_type
        first_date = min(filter(None, [existing["first_observed_date"], observed_date]), default="")
        last_date = max(filter(None, [existing["last_observed_date"], observed_date]), default="")
        source_is_newer = observed_date and observed_date >= (existing["last_observed_date"] or "")
        self.connection.execute(
            """
            UPDATE character_roster
            SET character_rank_value = ?,
                character_rank_label = ?,
                equipment_type = ?,
                equipment_rank_value = ?,
                equipment_rank_label = ?,
                first_observed_date = ?,
                last_observed_date = ?,
                source_video_id = CASE WHEN ? THEN ? ELSE source_video_id END,
                source_title = CASE WHEN ? THEN ? ELSE source_title END,
                needs_alias_review = CASE WHEN needs_alias_review = 1 AND ? = 0 THEN 0 ELSE needs_alias_review END,
                updated_at = ?
            WHERE game_key = ? AND canonical_name = ?
            """,
            (
                best_character_value,
                character_label,
                equipment_type_value,
                best_equipment_value,
                equipment_label,
                first_date,
                last_date,
                int(source_is_newer),
                source_video_id,
                int(source_is_newer),
                source_title,
                int(needs_alias_review),
                now,
                game_key,
                canonical_name,
            ),
        )

    def list_character_roster(self, game_key: str | None = None) -> list[CharacterRosterRecord]:
        if game_key:
            rows = self.connection.execute(
                "SELECT * FROM character_roster WHERE game_key = ? ORDER BY canonical_name",
                (game_key,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM character_roster ORDER BY game_key, canonical_name").fetchall()
        return [
            CharacterRosterRecord(
                game_key=row["game_key"],
                canonical_name=row["canonical_name"],
                display_name=row["display_name"],
                character_rank_value=row["character_rank_value"],
                character_rank_label=row["character_rank_label"],
                equipment_type=row["equipment_type"],
                equipment_rank_value=row["equipment_rank_value"],
                equipment_rank_label=row["equipment_rank_label"],
                first_observed_date=row["first_observed_date"],
                last_observed_date=row["last_observed_date"],
                source_video_id=row["source_video_id"],
                source_title=row["source_title"],
                needs_alias_review=bool(row["needs_alias_review"]),
            )
            for row in rows
        ]

    def _video_from_joined_row(self, row: sqlite3.Row) -> VideoSummary:
        # JOIN 결과에서 videos.* 컬럼명은 동일하게 접근 가능하다.
        return self._video_from_row(row)

    def _draft_from_row(self, row: sqlite3.Row) -> DescriptionDraftRecord:
        return DescriptionDraftRecord(
            video_id=row["video_id"],
            template_name=row["template_name"],
            status=row["status"],
            fields=_json_loads(row["fields_json"], {}),
            sections=_json_loads(row["sections_json"], []),
            timestamps=_json_loads(row["timestamps_json"], []),
            top_tags=_json_loads(row["top_tags_json"], []),
            rendered_description=row["rendered_description"],
            parse_confidence=row["parse_confidence"],
            warnings=_json_loads(row["warnings_json"], []),
            unmatched_lines=_json_loads(row["unmatched_json"], []),
            error_message=row["error_message"],
            reviewed_at=row["reviewed_at"],
            applied_at=row["applied_at"],
            updated_at=row["updated_at"],
        )


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: str, fallback):
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _safe_int(value: object, fallback: int = UNKNOWN_RANK_VALUE) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
