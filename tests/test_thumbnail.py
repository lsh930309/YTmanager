import tempfile
import unittest
from pathlib import Path

from ytmanager.thumbnail import detect_image_mime, public_thumbnail_url, public_watch_url, validate_thumbnail_file


class ThumbnailTests(unittest.TestCase):
    def test_detect_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "thumb.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
            self.assertEqual(detect_image_mime(path), "image/png")
            self.assertTrue(validate_thumbnail_file(path).can_upload)

    def test_reject_missing(self):
        result = validate_thumbnail_file(Path("missing.png"))
        self.assertFalse(result.can_upload)

    def test_public_preview_urls(self):
        self.assertEqual(
            public_thumbnail_url("abc123"),
            "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
        )
        self.assertTrue(public_thumbnail_url("abc123", cache_bust=True).startswith(
            "https://i.ytimg.com/vi/abc123/maxresdefault.jpg?ytmanager_preview="
        ))
        self.assertEqual(public_watch_url("abc123"), "https://www.youtube.com/watch?v=abc123")


if __name__ == "__main__":
    unittest.main()
