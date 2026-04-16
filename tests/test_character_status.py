import unittest

from ytmanager.character_status import extract_video_date, format_party_status, game_key_from_title_prefix, parse_party_status


class CharacterStatusTests(unittest.TestCase):
    def test_game_prefix_mapping(self):
        self.assertEqual(game_key_from_title_prefix("젠존제"), "zenless_zone_zero")
        self.assertEqual(game_key_from_title_prefix("스타레일"), "honkai_starrail")
        self.assertEqual(game_key_from_title_prefix("명조"), "wuthering_waves")
        self.assertEqual(game_key_from_title_prefix("엔드필드"), "endfield")

    def test_parse_zzz_character_and_engine(self):
        parsed = parse_party_status("1돌전엔", "zenless_zone_zero")
        self.assertEqual(parsed.character_rank, "1돌")
        self.assertEqual(parsed.character_rank_value, 1)
        self.assertEqual(parsed.equipment_type, "전엔")
        self.assertEqual(parsed.equipment_rank_value, 1)
        self.assertEqual(format_party_status(parsed, "zenless_zone_zero"), "1돌전엔")

    def test_parse_short_signature(self):
        parsed = parse_party_status("명전", "honkai_starrail")
        self.assertEqual(parsed.character_rank, "명함")
        self.assertEqual(parsed.equipment_type, "전광")
        self.assertEqual(format_party_status(parsed, "honkai_starrail"), "명전")

    def test_parse_refinement_only_with_default_equipment(self):
        parsed = parse_party_status("명함2재", "wuthering_waves")
        self.assertEqual(parsed.character_rank, "명함")
        self.assertEqual(parsed.equipment_type, "전무")
        self.assertEqual(parsed.equipment_rank, "2재")
        self.assertEqual(format_party_status(parsed, "wuthering_waves"), "명함2재")

    def test_parse_full_character_and_full_refinement(self):
        parsed = parse_party_status("풀돌풀재", "wuthering_waves")
        self.assertEqual(parsed.character_rank, "풀돌")
        self.assertEqual(parsed.equipment_rank, "풀재")
        self.assertEqual(format_party_status(parsed, "wuthering_waves"), "풀돌풀재")

    def test_parse_endfield_potential(self):
        parsed = parse_party_status("1잠전무", "endfield")
        self.assertEqual(parsed.character_rank, "1잠")
        self.assertEqual(parsed.equipment_type, "전무")
        self.assertEqual(format_party_status(parsed, "endfield"), "1잠전무")
        full = parse_party_status("풀잠풀재", "endfield")
        self.assertEqual(full.character_rank, "풀잠")
        self.assertEqual(full.character_rank_value, 5)
        self.assertEqual(format_party_status(full, "endfield"), "풀잠풀재")

    def test_extract_video_date_from_title(self):
        self.assertEqual(extract_video_date("[젠존제] 테스트 - 2026 04 15"), "2026-04-15")
        self.assertEqual(extract_video_date("제목", "2026-04-16T00:00:00Z"), "2026-04-16")


if __name__ == "__main__":
    unittest.main()
