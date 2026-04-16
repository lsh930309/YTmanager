import tempfile
import unittest
from pathlib import Path

from ytmanager.models import VideoSummary
from ytmanager.storage import AppDatabase


class StorageTests(unittest.TestCase):
    def test_save_and_load_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AppDatabase(Path(tmp) / "app.sqlite3")
            try:
                video = VideoSummary(
                    video_id="abc",
                    title="[젠존제] 테스트",
                    description="설명",
                    tags=("tag1", "tag2"),
                    thumbnail_url="https://example.com/thumb.jpg",
                    duration="PT1M",
                    privacy_status="private",
                    published_at="2026-04-16T00:00:00Z",
                    category_id="20",
                )
                db.save_videos([video])
                loaded = db.list_videos()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0].video_id, "abc")
                self.assertEqual(loaded[0].tags, ("tag1", "tag2"))
                db.save_snapshot(video)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
