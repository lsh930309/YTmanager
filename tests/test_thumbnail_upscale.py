import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtGui import QColor, QImage
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local dev environment
    raise unittest.SkipTest("PySide6 is required for thumbnail_upscale tests") from exc

from ytmanager.thumbnail import validate_thumbnail_file
from ytmanager.thumbnail_upscale import (
    ThumbnailUpscaleError,
    Waifu2xStatus,
    build_waifu2x_command,
    executable_names,
    finalize_jpeg,
    safe_extract_zip,
    upscale_thumbnail_candidate,
    waifu2x_archive_url,
    waifu2x_status,
)


def write_test_image(path: Path, width: int = 640, height: int = 360) -> None:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#3366cc"))
    assert image.save(str(path), "PNG")


class ThumbnailUpscaleTests(unittest.TestCase):
    def test_platform_urls_exist(self):
        self.assertIn("macos.zip", waifu2x_archive_url("darwin"))
        self.assertIn("windows.zip", waifu2x_archive_url("windows"))
        self.assertIn("linux.zip", waifu2x_archive_url("linux"))
        self.assertEqual(executable_names("windows"), ("waifu2x-ncnn-vulkan.exe",))

    def test_build_waifu2x_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "waifu2x-ncnn-vulkan"
            exe.write_text("", encoding="utf-8")
            (root / "models-cunet").mkdir()
            command = build_waifu2x_command(exe, root / "in.png", root / "out.png", noise=1, scale=2)
            self.assertIn("-n", command)
            self.assertIn("1", command)
            self.assertIn("-s", command)
            self.assertIn("2", command)
            self.assertIn("-m", command)
            self.assertIn(str(root / "models-cunet"), command)

    def test_safe_extract_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            destination = Path(tmp) / "out"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../bad.txt", "bad")
            with self.assertRaises(ThumbnailUpscaleError):
                safe_extract_zip(archive, destination)

    def test_waifu2x_status_reports_missing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("ytmanager.thumbnail_upscale.waifu2x_cache_dir", return_value=Path(tmp) / "missing"):
                status = waifu2x_status("darwin")
            self.assertIsInstance(status, Waifu2xStatus)
            self.assertFalse(status.available)
            self.assertIsNone(status.executable_path)

    def test_finalize_jpeg_outputs_uploadable_1280x720(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "final.jpg"
            write_test_image(source)
            width, height, quality, size = finalize_jpeg(source, output)
            self.assertEqual((width, height), (1280, 720))
            self.assertIn(quality, (92, 88, 84, 80, 76))
            self.assertGreater(size, 0)
            self.assertTrue(validate_thumbnail_file(output).can_upload)

    def test_upscale_falls_back_when_waifu2x_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "final.jpg"
            write_test_image(source)
            with mock.patch("ytmanager.thumbnail_upscale.run_waifu2x", side_effect=RuntimeError("boom")):
                result = upscale_thumbnail_candidate(source, output, mode="waifu2x")
            self.assertTrue(result.fallback_used)
            self.assertEqual(result.engine, "fast")
            self.assertTrue(output.exists())
            self.assertTrue(validate_thumbnail_file(output).can_upload)


if __name__ == "__main__":
    unittest.main()
