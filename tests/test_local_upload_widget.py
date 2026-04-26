import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ytmanager.ffmpeg_tools import FFmpegToolchain
from ytmanager.local_upload import LocalVideoProbe
from ytmanager.models import RuleMapping
from ytmanager.storage import AppDatabase
from ytmanager.ui.local_upload_widget import LocalUploadWidget, SegmentCardWidget


class LocalUploadWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.video_path = Path(self.tempdir.name) / "sample.mp4"
        self.video_path.write_bytes(b"test")
        self.db = AppDatabase(Path(self.tempdir.name) / "app.sqlite3")
        self.addCleanup(self.db.close)
        self.widget = LocalUploadWidget(
            rules=[RuleMapping("젠존제", ("#zenlesszonezero",), "젠레스 존 제로")],
            settings_store=self.db,
            ensure_youtube_client=lambda: None,
            status_message=lambda message: None,
        )
        self.addCleanup(self.widget.close)
        self.widget.toolchain = FFmpegToolchain(Path("ffmpeg"), Path("ffprobe"), "test", False)
        self.widget.controller.prober = lambda path, ffprobe_path=None: LocalVideoProbe(
            duration_seconds=120.0,
            width_pixels=1920,
            height_pixels=1080,
            created_at="2026-04-25",
            modified_at="2026-04-26",
            keyframes=(30.0, 60.0, 90.0),
            frame_rate=30.0,
        )
        self.widget.load_media_file(self.video_path)
        self.app.processEvents()

    def test_segment_editor_applies_only_on_button(self):
        original_title = self.widget.controller.require_segment(1).title
        self.widget.segment_title_input.setText("새 세그먼트 제목")
        self.app.processEvents()
        self.assertEqual(self.widget.segment_dirty_label.text(), "적용 대기")
        self.assertEqual(self.widget.controller.require_segment(1).title, original_title)

        self.widget.apply_segment_changes_btn.click()
        self.app.processEvents()
        self.assertEqual(self.widget.controller.require_segment(1).title, "새 세그먼트 제목")
        self.assertEqual(self.widget.segment_dirty_label.text(), "변경 없음")

    def test_card_checkbox_toggles_queue_immediately(self):
        item = self.widget.segment_card_list.item(0)
        card = self.widget.segment_card_list.itemWidget(item)
        self.assertIsInstance(card, SegmentCardWidget)
        assert isinstance(card, SegmentCardWidget)

        card.keep_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertFalse(self.widget.controller.require_segment(1).keep)
        self.assertEqual(len(self.widget.controller.queue), 0)
        self.assertFalse(self.widget.keep_checkbox.isChecked())

    def test_text_input_focus_detection_only_blocks_text_fields(self):
        self.widget.segment_title_input.setFocus()
        self.app.processEvents()
        self.assertTrue(self.widget.is_text_input_focused())

        self.widget.play_btn.setFocus()
        self.app.processEvents()
        self.assertFalse(self.widget.is_text_input_focused())

    def test_upload_progress_updates_widgets(self):
        self.widget._on_upload_progress(1, 4, 0.5, "업로드 중 · 테스트")
        self.assertEqual(self.widget.upload_progress_bar.value(), 12)
        self.assertIn("업로드 중", self.widget.upload_progress_label.text())


if __name__ == "__main__":
    unittest.main()
