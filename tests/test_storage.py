import tempfile
import unittest
from pathlib import Path

from ytmanager.models import VideoSummary
from ytmanager.storage import AppDatabase, DRAFT_STATUS_DRAFT, DRAFT_STATUS_REVIEWED, DescriptionDraftRecord


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
                    width_pixels=2560,
                    height_pixels=1440,
                    display_aspect_ratio=16 / 9,
                )
                db.save_videos([video])
                loaded = db.list_videos()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0].video_id, "abc")
                self.assertEqual(loaded[0].tags, ("tag1", "tag2"))
                self.assertEqual(loaded[0].width_pixels, 2560)
                self.assertEqual(loaded[0].height_pixels, 1440)
                self.assertAlmostEqual(loaded[0].effective_aspect_ratio(), 16 / 9)
                db.save_snapshot(video)
            finally:
                db.close()

    def test_description_draft_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AppDatabase(Path(tmp) / "app.sqlite3")
            try:
                video = VideoSummary(video_id="abc", title="[젠존제] 테스트", description="원본")
                db.save_videos([video])
                draft = DescriptionDraftRecord(
                    video_id="abc",
                    template_name="combat",
                    status=DRAFT_STATUS_DRAFT,
                    fields={"game_version": "2.7"},
                    sections=[{"boss_name": "니네베", "party": []}],
                    timestamps=[{"seconds": 83, "label": "시작"}],
                    top_tags=["#zenlesszonezero"],
                    rendered_description="정규화",
                    parse_confidence="high",
                )
                self.assertTrue(db.save_description_draft(draft))
                loaded = db.get_description_draft("abc")
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.fields["game_version"], "2.7")
                self.assertEqual(loaded.top_tags, ["#zenlesszonezero"])
                db.mark_draft_reviewed("abc")
                reviewed = db.get_description_draft("abc")
                assert reviewed is not None
                self.assertEqual(reviewed.status, DRAFT_STATUS_REVIEWED)
                ready = db.list_apply_ready_drafts()
                self.assertEqual(len(ready), 1)
                self.assertEqual(ready[0][0].video_id, "abc")
                self.assertEqual(ready[0][1].rendered_description, "정규화")
            finally:
                db.close()

    def test_preserve_reviewed_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AppDatabase(Path(tmp) / "app.sqlite3")
            try:
                db.save_videos([VideoSummary(video_id="abc", title="[젠존제] 테스트", description="원본")])
                reviewed = DescriptionDraftRecord(video_id="abc", status=DRAFT_STATUS_REVIEWED, rendered_description="검수됨")
                replacement = DescriptionDraftRecord(video_id="abc", status=DRAFT_STATUS_DRAFT, rendered_description="새 초안")
                self.assertTrue(db.save_description_draft(reviewed, preserve_reviewed=False))
                self.assertFalse(db.save_description_draft(replacement, preserve_reviewed=True))
                loaded = db.get_description_draft("abc")
                assert loaded is not None
                self.assertEqual(loaded.rendered_description, "검수됨")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
