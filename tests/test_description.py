import unittest

from ytmanager.description import extract_placeholders, render_description
from ytmanager.models import TimestampEntry


class DescriptionTests(unittest.TestCase):
    def test_extract_placeholders(self):
        self.assertEqual(extract_placeholders("{a} {b} {a}"), ["a", "b"])

    def test_render_description(self):
        template = "[{game_version} {game_content_name} {game_content_season_in_current_version}]\n{top_tags}\n\n{timestamps}\n\n{notes}"
        rendered = render_description(
            template,
            {
                "game_version": "2.7",
                "game_content_name": "위험한 강습전",
                "game_content_season_in_current_version": "1차",
                "notes": "메모",
            },
            ["#zenlesszonezero"],
            [TimestampEntry(83, "시작")],
        )
        self.assertIn("[2.7 위험한 강습전 1차]", rendered)
        self.assertIn("#zenlesszonezero", rendered)
        self.assertIn("01:23 - 시작", rendered)
        self.assertIn("메모", rendered)


if __name__ == "__main__":
    unittest.main()
