import subprocess
import tempfile
import unittest
from pathlib import Path

from ytmanager.local_upload import (
    LocalUploadController,
    LocalVideoProbe,
    build_segment_title,
    normalize_cut_points,
)
from ytmanager.models import RuleMapping
from ytmanager.storage import AppDatabase


class LocalUploadTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = AppDatabase(Path(self.tempdir.name) / "app.sqlite3")
        self.addCleanup(self.db.close)
        self.rules = [RuleMapping("젠존제", ("#zenlesszonezero",), "젠레스 존 제로")]
        self.video_path = Path(self.tempdir.name) / "sample.mp4"
        self.video_path.write_bytes(b"test")

    def _build_controller(self, uploader=None):
        def prober(path, ffprobe_path=None):
            self.assertEqual(Path(path), self.video_path)
            return LocalVideoProbe(
                duration_seconds=120.0,
                width_pixels=1920,
                height_pixels=1080,
                created_at="2026-04-25",
                modified_at="2026-04-26",
                keyframes=(30.0, 60.0, 90.0),
            )

        def splitter(source_path, segments, output_dir, ffmpeg_path):
            outputs = []
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            for segment in segments:
                target = Path(output_dir) / f"segment-{segment.index}.mp4"
                target.write_bytes(f"segment-{segment.index}".encode("utf-8"))
                outputs.append(target)
            return outputs

        def default_uploader(youtube_client, *, title, description, tags, privacy_status, media_path):
            return {"id": media_path.stem}

        return LocalUploadController(
            self.rules,
            self.db,
            prober=prober,
            splitter=splitter,
            uploader=uploader or default_uploader,
        )

    def test_build_segment_title(self):
        self.assertEqual(build_segment_title("젠존제", "위험한 강습전", "2026-04-25"), "[젠존제] 위험한 강습전 - 2026-04-25")
        self.assertEqual(
            build_segment_title("젠존제", "위험한 강습전", "2026-04-25", segment_index=2, segment_count=3),
            "[젠존제] 위험한 강습전 - 2026-04-25 (2/3)",
        )

    def test_normalize_cut_points(self):
        self.assertEqual(normalize_cut_points([0, 30, 30.0001, 90, 120], 120), [30.0, 90.0])

    def test_load_source_sets_default_date_and_last_dir(self):
        controller = self._build_controller()
        session = controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        self.assertEqual(session.date_text, "2026-04-25")
        self.assertEqual(self.db.get_setting("last_media_dir"), str(self.video_path.parent))
        self.assertEqual(len(session.segments), 1)

    def test_cutpoints_create_segments_and_keep_discard(self):
        controller = self._build_controller()
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        segments = controller.rebuild_segments([30, 60])
        self.assertEqual([(segment.start_seconds, segment.end_seconds) for segment in segments], [(0.0, 30.0), (30.0, 60.0), (60.0, 120.0)])
        controller.update_segment(2, keep=False)
        queue = controller.build_queue()
        self.assertEqual([item.segment.index for item in queue], [1, 3])

    def test_common_draft_copy_then_segment_override(self):
        controller = self._build_controller()
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        controller.rebuild_segments([60])
        controller.update_common_metadata(
            game_title_prefix="젠존제",
            title_text="위험한 강습전",
            date_text="2026-04-25",
            description="공통 설명",
            tags=["#zenlesszonezero", "#boss"],
            privacy_status="unlisted",
        )
        controller.overwrite_segment_defaults()
        self.assertEqual(controller.require_segment(1).title, "[젠존제] 위험한 강습전 - 2026-04-25 (1/2)")
        self.assertEqual(controller.require_segment(2).title, "[젠존제] 위험한 강습전 - 2026-04-25 (2/2)")
        controller.update_segment(2, title="[젠존제] 위험한 강습전 - 2026-04-25 후반", tags=["#custom"])
        self.assertEqual(controller.require_segment(2).title, "[젠존제] 위험한 강습전 - 2026-04-25 후반")
        self.assertEqual(controller.require_segment(2).tags, ["#custom"])

    def test_queue_processing_continues_after_failure(self):
        uploaded_titles = []

        def uploader(youtube_client, *, title, description, tags, privacy_status, media_path):
            uploaded_titles.append(title)
            if "(2/3)" in title:
                raise RuntimeError("두 번째 업로드 실패")
            return {"id": media_path.stem}

        controller = self._build_controller(uploader=uploader)
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        controller.rebuild_segments([30, 60])
        controller.update_common_metadata(
            game_title_prefix="젠존제",
            title_text="세그먼트 테스트",
            date_text="2026-04-25",
            description="설명",
            tags=["#zenlesszonezero"],
            privacy_status="private",
        )
        controller.overwrite_segment_defaults()
        controller.build_queue()
        summary = controller.process_queue(object(), ffmpeg_path=Path("ffmpeg"), output_dir=Path(self.tempdir.name) / "out")
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.succeeded, 2)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(uploaded_titles, [
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (1/3)",
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (2/3)",
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (3/3)",
        ])
        self.assertEqual([item.status for item in summary.items], ["uploaded", "failed", "uploaded"])


if __name__ == "__main__":
    unittest.main()
