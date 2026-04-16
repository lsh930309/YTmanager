import unittest

from ytmanager.models import VideoSummary, extract_video_dimensions


class VideoSummaryModelTests(unittest.TestCase):
    def test_extract_video_dimensions_uses_largest_stream(self):
        resource = {
            "fileDetails": {
                "videoStreams": [
                    {"widthPixels": 1280, "heightPixels": 720},
                    {"widthPixels": 2560, "heightPixels": 1440},
                ]
            }
        }
        width, height, aspect = extract_video_dimensions(resource)
        self.assertEqual((width, height), (2560, 1440))
        self.assertAlmostEqual(aspect, 16 / 9)

    def test_from_youtube_resource_carries_aspect_ratio(self):
        resource = {
            "id": "abc",
            "snippet": {
                "title": "테스트",
                "description": "설명",
                "categoryId": "20",
                "thumbnails": {"high": {"url": "https://example.com/high.jpg"}},
            },
            "contentDetails": {"duration": "PT1M"},
            "status": {"privacyStatus": "private"},
            "fileDetails": {"videoStreams": [{"widthPixels": 2560, "heightPixels": 1440}]},
        }
        video = VideoSummary.from_youtube_resource(resource)
        self.assertEqual(video.width_pixels, 2560)
        self.assertEqual(video.height_pixels, 1440)
        self.assertAlmostEqual(video.effective_aspect_ratio(), 16 / 9)
        self.assertEqual(video.resolution_label(), "2560×1440")

    def test_effective_aspect_ratio_defaults_to_sixteen_by_nine(self):
        video = VideoSummary(video_id="abc", title="테스트")
        self.assertAlmostEqual(video.effective_aspect_ratio(), 16 / 9)
        self.assertEqual(video.resolution_label(), "16:9 기본 비율")


if __name__ == "__main__":
    unittest.main()
