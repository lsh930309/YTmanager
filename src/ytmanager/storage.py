from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from ytmanager.models import VideoSummary
from ytmanager.paths import default_database_path

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
"""


class AppDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save_videos(self, videos: Iterable[VideoSummary]) -> None:
        with self.connection:
            for video in videos:
                self.connection.execute(
                    """
                    INSERT INTO videos (
                        video_id, title, description, tags_json, thumbnail_url,
                        duration, privacy_status, published_at, category_id, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        tags_json = excluded.tags_json,
                        thumbnail_url = excluded.thumbnail_url,
                        duration = excluded.duration,
                        privacy_status = excluded.privacy_status,
                        published_at = excluded.published_at,
                        category_id = excluded.category_id,
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
                    ),
                )

    def list_videos(self) -> list[VideoSummary]:
        rows = self.connection.execute("SELECT * FROM videos ORDER BY published_at DESC, synced_at DESC").fetchall()
        return [
            VideoSummary(
                video_id=row["video_id"],
                title=row["title"],
                description=row["description"],
                tags=tuple(json.loads(row["tags_json"])),
                thumbnail_url=row["thumbnail_url"],
                duration=row["duration"],
                privacy_status=row["privacy_status"],
                published_at=row["published_at"],
                category_id=row["category_id"],
            )
            for row in rows
        ]

    def save_snapshot(self, video: VideoSummary) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO metadata_snapshots (video_id, title, description, tags_json)
                VALUES (?, ?, ?, ?)
                """,
                (video.video_id, video.title, video.description, json.dumps(list(video.tags), ensure_ascii=False)),
            )
