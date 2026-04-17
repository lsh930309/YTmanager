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
    DEFAULT_WAIFU2X_NOISE,
    TARGET_THUMBNAIL_WIDTH,
    TARGET_THUMBNAIL_HEIGHT,
    ThumbnailUpscaleError,
    Waifu2xStatus,
    apply_subtle_unsharp,
    build_waifu2x_command,
    executable_names,
    finalize_jpeg,
    finalize_image_pillow,
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

    def test_default_denoise_is_conservative(self):
        self.assertEqual(DEFAULT_WAIFU2X_NOISE, 0)

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

    def test_finalize_jpeg_outputs_uploadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "final.jpg"
            write_test_image(source)
            width, height, quality, size = finalize_jpeg(source, output)
            self.assertEqual((width, height), (TARGET_THUMBNAIL_WIDTH, TARGET_THUMBNAIL_HEIGHT))
            self.assertEqual(quality, 100)
            self.assertGreater(size, 0)
            self.assertTrue(validate_thumbnail_file(output).can_upload)

    def test_pillow_finalization_supports_png_hook(self):
        try:
            import PIL  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("Pillow is required for PNG finalization hook test")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "final.png"
            write_test_image(source)
            width, height, quality, size = finalize_image_pillow(source, output, output_format="png")
            self.assertEqual((width, height, quality), (TARGET_THUMBNAIL_WIDTH, TARGET_THUMBNAIL_HEIGHT, 100))
            self.assertGreater(size, 0)

    def test_subtle_unsharp_preserves_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            write_test_image(source, 16, 9)
            image = QImage(str(source))
            sharpened = apply_subtle_unsharp(image)
            self.assertEqual((sharpened.width(), sharpened.height()), (16, 9))

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

    def test_upscale_can_keep_waifu2x_png_without_downscale(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            output = Path(tmp) / "final.png"
            write_test_image(source)

            def fake_run(input_path, output_path, **kwargs):
                write_test_image(output_path, 2560, 1440)

            with mock.patch("ytmanager.thumbnail_upscale.run_waifu2x", side_effect=fake_run):
                result = upscale_thumbnail_candidate(source, output, mode="waifu2x", keep_upscaled_png=True)
            self.assertFalse(result.fallback_used)
            self.assertEqual(result.engine, "waifu2x")
            self.assertEqual((result.output_width, result.output_height), (2560, 1440))
            self.assertEqual(result.jpeg_quality, 100)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
