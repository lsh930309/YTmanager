import unittest
import tempfile
from pathlib import Path

from ytmanager.rules import extract_title_prefix, load_rule_mappings, merge_top_tags, top_tags_for_title, unique_tags


class RuleTests(unittest.TestCase):
    def test_extract_title_prefix(self):
        self.assertEqual(extract_title_prefix("[젠존제] 2.7 위험한 강습전"), "젠존제")
        self.assertIsNone(extract_title_prefix("젠존제 플레이"))

    def test_top_tags_for_title(self):
        self.assertEqual(top_tags_for_title("[젠존제] 플레이"), ["#zenlesszonezero"])

    def test_unique_tags(self):
        self.assertEqual(unique_tags(["zenlesszonezero", "#ZenlessZoneZero", "#zzz"]), ["#zenlesszonezero", "#zzz"])

    def test_merge_top_tags(self):
        self.assertEqual(merge_top_tags("본문", ["#tag"]), "#tag\n본문")
        self.assertEqual(merge_top_tags("#tag\n본문", ["#tag"]), "#tag\n본문")

    def test_load_rule_mappings_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text('[{"title_prefix":"테스트","description_tags":["tag"],"display_name":"테스트 게임"}]', encoding="utf-8")
            rules = load_rule_mappings(path)
            self.assertEqual(rules[0].title_prefix, "테스트")
            self.assertEqual(rules[0].description_tags, ("#tag",))


if __name__ == "__main__":
    unittest.main()
