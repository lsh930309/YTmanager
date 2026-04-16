import unittest

from ytmanager.youtube_api import YouTubeApiClient


class YouTubePayloadTests(unittest.TestCase):
    def test_update_payload_preserves_snippet_fields(self):
        existing = {
            "id": "abc123",
            "snippet": {
                "title": "이전 제목",
                "description": "이전 설명",
                "tags": ["old"],
                "categoryId": "20",
                "defaultLanguage": "ko",
            },
        }
        payload = YouTubeApiClient.build_snippet_update_payload(
            existing,
            title="새 제목",
            description="새 설명",
            tags=["#new"],
        )
        self.assertEqual(payload["id"], "abc123")
        self.assertEqual(payload["snippet"]["categoryId"], "20")
        self.assertEqual(payload["snippet"]["defaultLanguage"], "ko")
        self.assertEqual(payload["snippet"]["title"], "새 제목")
        self.assertEqual(payload["snippet"]["description"], "새 설명")
        self.assertEqual(payload["snippet"]["tags"], ["#new"])

    def test_update_payload_requires_video_id(self):
        with self.assertRaises(ValueError):
            YouTubeApiClient.build_snippet_update_payload({"snippet": {"title": "x"}})


if __name__ == "__main__":
    unittest.main()
