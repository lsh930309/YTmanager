import tempfile
import unittest
from pathlib import Path

from ytmanager.local_upload import (
    DEFAULT_FRAME_RATE,
    LocalUploadController,
    LocalVideoProbe,
    build_segment_title,
    prepare_upload_metadata,
    normalize_cut_points,
)
from ytmanager.models import RuleMapping
from ytmanager.storage import AppDatabase
from ytmanager.youtube_api import FALLBACK_RESUMABLE_CHUNK_SIZE, UploadStrategy, YouTubeApiClient


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
                frame_rate=29.97,
            )

        def splitter(source_path, segments, output_dir, ffmpeg_path):
            outputs = []
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            for segment in segments:
                target = Path(output_dir) / f"segment-{segment.index}.mp4"
                target.write_bytes(f"segment-{segment.index}".encode("utf-8"))
                outputs.append(target)
            return outputs

        def default_uploader(youtube_client, *, title, description, tags, privacy_status, media_path, progress_callback=None):
            if progress_callback is not None:
                progress_callback(1.0)
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
        self.assertEqual(session.probe.frame_rate, 29.97)
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

    def test_prepare_upload_metadata_merges_top_tags_once(self):
        metadata = prepare_upload_metadata("본문", ["#zenlesszonezero", "boss", "#zenlesszonezero"])
        self.assertEqual(metadata.tags, ["#zenlesszonezero", "#boss"])
        self.assertEqual(metadata.description, "#zenlesszonezero #boss\n본문")

    def test_prepare_upload_metadata_preserves_existing_first_line_tags(self):
        metadata = prepare_upload_metadata("#zenlesszonezero\n본문", ["#zenlesszonezero"])
        self.assertEqual(metadata.tags, ["#zenlesszonezero"])
        self.assertEqual(metadata.description, "#zenlesszonezero\n본문")

    def test_queue_processing_continues_after_failure(self):
        uploaded_titles = []

        def uploader(youtube_client, *, title, description, tags, privacy_status, media_path, progress_callback=None):
            uploaded_titles.append(title)
            if progress_callback is not None:
                progress_callback(0.5)
            if "(2/3)" in title:
                raise RuntimeError("두 번째 업로드 실패")
            if progress_callback is not None:
                progress_callback(1.0)
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
        controller.prepare_queue_files(ffmpeg_path=Path("ffmpeg"), output_dir=Path(self.tempdir.name) / "out")
        summary = controller.upload_prepared_queue(object())
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.succeeded, 2)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(uploaded_titles, [
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (1/3)",
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (2/3)",
            "[젠존제] 세그먼트 테스트 - 2026-04-25 (3/3)",
        ])
        self.assertEqual([item.status for item in summary.items], ["uploaded", "failed", "uploaded"])

    def test_queue_progress_callback_reports_overall_progress(self):
        events = []

        def uploader(youtube_client, *, title, description, tags, privacy_status, media_path, progress_callback=None):
            if progress_callback is not None:
                progress_callback(0.25)
                progress_callback(1.0)
            return {"id": media_path.stem}

        controller = self._build_controller(uploader=uploader)
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        controller.rebuild_segments([60])
        controller.update_common_metadata(
            game_title_prefix="젠존제",
            title_text="진행률 테스트",
            date_text="2026-04-25",
            description="설명",
            tags=["#zenlesszonezero"],
            privacy_status="private",
        )
        controller.overwrite_segment_defaults()
        controller.build_queue()
        controller.prepare_queue_files(
            ffmpeg_path=Path("ffmpeg"),
            output_dir=Path(self.tempdir.name) / "out",
            progress_callback=lambda current, total, fraction, message: events.append((current, total, round(fraction, 2), message)),
        )
        controller.upload_prepared_queue(
            object(),
            progress_callback=lambda current, total, fraction, message: events.append((current, total, round(fraction, 2), message)),
        )
        self.assertTrue(events)
        self.assertEqual(events[0][0:2], (1, 2))
        self.assertEqual(events[-1][0:3], (2, 2, 1.0))

    def test_thumbnail_upload_warning_does_not_fail_video_upload(self):
        class StubYouTubeClient:
            def __init__(self) -> None:
                self.thumbnail_calls = []

            def upload_thumbnail(self, video_id, image_path):
                self.thumbnail_calls.append((video_id, Path(image_path)))
                raise RuntimeError("썸네일 오류")

        events = []

        def uploader(youtube_client, *, title, description, tags, privacy_status, media_path, progress_callback=None):
            if progress_callback is not None:
                progress_callback(0.5)
                progress_callback(1.0)
            return {"id": f"video-{media_path.stem}"}

        controller = self._build_controller(uploader=uploader)
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        thumb_path = Path(self.tempdir.name) / "thumb.jpg"
        thumb_path.write_bytes(b"jpg")
        controller.set_segment_thumbnail(1, thumb_path)
        controller.build_queue()
        controller.prepare_queue_files(ffmpeg_path=Path("ffmpeg"), output_dir=Path(self.tempdir.name) / "out")

        youtube_client = StubYouTubeClient()
        summary = controller.upload_prepared_queue(
            youtube_client,
            progress_callback=lambda current, total, fraction, message: events.append((current, total, round(fraction, 2), message)),
        )

        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(len(youtube_client.thumbnail_calls), 1)
        self.assertIn("썸네일 업로드 실패", summary.items[0].warning_message)
        self.assertEqual(summary.items[0].status, "uploaded")
        self.assertTrue(any("썸네일 업로드 중" in message for _, _, _, message in events))
        self.assertTrue(any("썸네일 경고" in message for _, _, _, message in events))

    def test_thumbnail_upload_success_marks_queue_item(self):
        class StubYouTubeClient:
            def __init__(self) -> None:
                self.thumbnail_calls = []

            def upload_thumbnail(self, video_id, image_path):
                self.thumbnail_calls.append((video_id, Path(image_path)))
                return {"items": []}

        def uploader(youtube_client, *, title, description, tags, privacy_status, media_path, progress_callback=None):
            return {"id": "video-1"}

        controller = self._build_controller(uploader=uploader)
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        thumb_path = Path(self.tempdir.name) / "thumb.jpg"
        thumb_path.write_bytes(b"jpg")
        controller.set_segment_thumbnail(1, thumb_path)
        controller.build_queue()
        controller.prepare_queue_files(ffmpeg_path=Path("ffmpeg"), output_dir=Path(self.tempdir.name) / "out")

        youtube_client = StubYouTubeClient()
        summary = controller.upload_prepared_queue(youtube_client)

        self.assertEqual(len(youtube_client.thumbnail_calls), 1)
        self.assertTrue(summary.items[0].thumbnail_uploaded)
        self.assertEqual(summary.items[0].warning_message, "")

    def test_autosave_roundtrip_restores_selected_segment_and_position(self):
        controller = self._build_controller()
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        controller.rebuild_segments([30, 60])
        controller.update_segment(2, title="중간 구간")
        controller.set_segment_thumbnail(2, Path(self.tempdir.name) / "thumb.jpg")
        controller.save_autosave(selected_segment_index=2, current_position_ms=45678)

        restored = self._build_controller().restore_autosave()
        self.assertIsNotNone(restored)
        session, selected_index, current_position_ms = restored
        self.assertEqual(selected_index, 2)
        self.assertEqual(current_position_ms, 45678)
        self.assertEqual(session.segments[1].title, "중간 구간")
        self.assertTrue(session.segments[1].thumbnail_path.endswith("thumb.jpg"))

    def test_keyframe_navigation_uses_previous_and_next_boundaries(self):
        controller = self._build_controller()
        controller.load_source(self.video_path, ffprobe_path=Path("ffprobe"))
        self.assertEqual(controller.keyframe_step_seconds(44.0, -1), 30.0)
        self.assertEqual(controller.keyframe_step_seconds(44.0, 1), 60.0)
        self.assertEqual(controller.keyframe_step_seconds(5.0, -1), 0.0)
        self.assertEqual(controller.keyframe_step_seconds(110.0, 1), 120.0)

    def test_effective_frame_rate_falls_back_to_default(self):
        probe = LocalVideoProbe(duration_seconds=1.0, frame_rate=0.0)
        self.assertEqual(probe.effective_frame_rate(), DEFAULT_FRAME_RATE)


class YouTubeUploadStrategyTests(unittest.TestCase):
    def test_default_upload_strategies_prefer_single_chunk_then_fallback(self):
        strategies = YouTubeApiClient.default_upload_strategies()
        self.assertEqual(
            strategies,
            (
                UploadStrategy(name="single_chunk_resumable", chunksize=-1),
                UploadStrategy(name="chunked_resumable_fallback", chunksize=FALLBACK_RESUMABLE_CHUNK_SIZE),
            ),
        )

    def test_upload_video_retries_with_fallback_strategy(self):
        class StrategyClient(YouTubeApiClient):
            def __init__(self) -> None:
                super().__init__(service=object())
                self.calls = []

            def _upload_video_with_strategy(self, *, body, media_path, strategy, progress_callback=None):
                self.calls.append(strategy)
                if strategy.chunksize == -1:
                    raise RuntimeError("single chunk failed")
                return {"id": "uploaded", "_ytmanager_upload_metrics": {"strategy": strategy.name}}

        with tempfile.TemporaryDirectory() as tempdir:
            media_path = Path(tempdir) / "video.mp4"
            media_path.write_bytes(b"video")
            client = StrategyClient()
            response = client.upload_video(
                title="제목",
                description="설명",
                tags=["#tag"],
                privacy_status="private",
                media_path=media_path,
            )

        self.assertEqual(response["id"], "uploaded")
        self.assertEqual([strategy.chunksize for strategy in client.calls], [-1, FALLBACK_RESUMABLE_CHUNK_SIZE])


if __name__ == "__main__":
    unittest.main()
