import unittest

from ytmanager.description import (
    DescriptionSection,
    PartyMember,
    extract_placeholders,
    load_template_library,
    parse_gacha_fields,
    parse_sections_text,
    render_description,
    render_description_template,
)
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

    def test_render_structured_template(self):
        template = (
            "{[tags]}\n"
            "[{game_version} {game_content_name} {game_content_season_in_current_version}]\n"
            "\n"
            "//Section Start//\n"
            "**{optional: stage_number} {boss_name} - {party_composition}**\n"
            "- {party[i].character}: {party[i].character.M_level}{optional: party[i].character.equip}\n"
            "//Section End//\n"
            "\n"
            "-------------------\n"
            "\n"
            "{[timestamps]}"
        )
        rendered = render_description(
            template,
            {
                "game_version": "2.7",
                "game_content_name": "위험한 강습전",
                "game_content_season_in_current_version": "1차",
            },
            ["#zenlesszonezero"],
            [TimestampEntry(83, "시작")],
            [
                DescriptionSection(
                    stage_number="1",
                    boss_name="니네베",
                    party_composition="강공 파티",
                    party=(
                        PartyMember("엘렌", "M0", "전용 무기"),
                        PartyMember("리카온", "M1", ""),
                    ),
                )
            ],
        )
        self.assertIn("#zenlesszonezero", rendered)
        self.assertIn("[2.7 위험한 강습전 1차]", rendered)
        self.assertIn("**1 니네베 - 강공 파티**", rendered)
        self.assertIn("- 엘렌: M0 전용 무기", rendered)
        self.assertIn("- 리카온: M1", rendered)
        self.assertIn("-------------------", rendered)
        self.assertIn("01:23 - 시작", rendered)
        self.assertNotIn("//Section Start//", rendered)

    def test_render_structured_template_omits_timestamp_divider_when_empty(self):
        template = "{[tags]}\n[{game_version} {game_content_name} {game_content_season_in_current_version}]\n\n-------------------\n\n{[timestamps]}"
        rendered = render_description(
            template,
            {
                "game_version": "2.7",
                "game_content_name": "위험한 강습전",
                "game_content_season_in_current_version": "1차",
            },
            ["#zenlesszonezero"],
            [],
        )
        self.assertIn("[2.7 위험한 강습전 1차]", rendered)
        self.assertNotIn("-------------------", rendered)

    def test_render_section_without_party_composition_removes_trailing_dash(self):
        template = (
            "//Section Start//\n"
            "**{optional: stage_number} {boss_name} - {party_composition}**\n"
            "//Section End//"
        )
        rendered = render_description(
            template,
            sections=[DescriptionSection(boss_name="이게 겜이지")],
        )
        self.assertEqual(rendered, "**이게 겜이지**")

    def test_parse_sections_text(self):
        sections = parse_sections_text(
            "stage_number=1\n"
            "boss_name=니네베\n"
            "party_composition=강공 파티\n"
            "party:\n"
            "엘렌|M0|전용 무기\n"
            "리카온|M1|\n"
            "---\n"
            "stage_number=2\n"
            "boss_name=다음 보스\n"
            "party_composition=이상 파티\n"
            "party:\n"
            "야나기|M0|장비"
        )
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].boss_name, "니네베")
        self.assertEqual(sections[0].party[0].character, "엘렌")
        self.assertEqual(sections[0].party[0].equip, "전용 무기")

    def test_parse_description_preserves_timestamp_lines_without_divider(self):
        from ytmanager.description import parse_description

        parsed = parse_description(
            "",
            "#zenlesszonezero\n"
            "[2.7 이벤트 1차]\n"
            "*이게 겜이지*\n"
            "00:00 1일차\n"
            "04:13 2일차",
        )
        self.assertEqual(len(parsed.timestamps), 2)
        self.assertEqual(parsed.timestamps[0].label, "1일차")
        self.assertEqual(parsed.unmatched_lines, ())

    def test_load_template_library_and_render_gacha(self):
        template = (
            "//Template: combat//\n"
            "{[tags]}\n[{game_version} {game_content_name} {game_content_season_in_current_version}]\n"
            "//Template: gacha//\n"
            "{[tags]}\n[{game_version} {game_content_name} {game_content_season_in_current_version}]\n\n"
            "//Section Start//\n"
            "**{boss_name}**\n"
            "- {party[i].character} {party[i].character.M_level}{optional: party[i].character.equip}\n"
            "//Section End//"
        )
        self.assertEqual(set(load_template_library(template)), {"combat", "gacha"})
        rendered = render_description_template(
            template,
            "gacha",
            {
                "game_version": "2.7",
                "game_content_name": "시시아",
                "game_content_season_in_current_version": "가챠",
            },
            ["#zenlesszonezero", "#gacha"],
            sections=[
                DescriptionSection(
                    boss_name="시작 스택",
                    party=(PartyMember("캐릭터", "반천", "0스택"), PartyMember("엔진", "반천", "0스택")),
                )
            ],
        )
        self.assertIn("#zenlesszonezero #gacha", rendered)
        self.assertIn("**시작 스택**", rendered)
        self.assertIn("- 캐릭터 반천 0스택", rendered)


    def test_load_template_library_strips_separator_lines(self):
        template = (
            "//Template: combat//\n"
            "{[tags]}\n"
            "############################################\n"
            "//Template: gacha//\n"
            "{[tags]}\n"
        )
        library = load_template_library(template)
        self.assertNotIn("############", library["combat"])
        self.assertNotIn("############", library["gacha"])

    def test_load_template_library_converts_optional_divider(self):
        template = (
            "//Template: combat//\n"
            "{[tags]}\n"
            "optional: -------------------\n"
            "{optional: [timestamps]}\n"
        )
        library = load_template_library(template)
        body = library["combat"]
        self.assertIn("-------------------", body)
        self.assertNotIn("optional: ---", body)

    def test_optional_timestamps_token_renders_when_present(self):
        template = "{[tags]}\n-------------------\n{optional: [timestamps]}"
        rendered = render_description(template, top_tags=["#tag"], timestamps=[TimestampEntry(60, "시작")])
        self.assertIn("01:00 - 시작", rendered)
        self.assertIn("-------------------", rendered)

    def test_optional_timestamps_token_omits_divider_when_empty(self):
        template = "{[tags]}\n-------------------\n{optional: [timestamps]}"
        rendered = render_description(template, top_tags=["#tag"], timestamps=[])
        self.assertNotIn("-------------------", rendered)
        self.assertNotIn("{optional:", rendered)

    def test_render_combat_italic_headline(self):
        template = (
            "//Section Start//\n"
            "*{optional: stage_number} {boss_name} - {party_composition}*\n"
            "- {party[i].character} {party[i].character.M_level}{optional: party[i].character.equip}\n"
            "//Section End//"
        )
        rendered = render_description(
            template,
            sections=[DescriptionSection(stage_number="1", boss_name="니네베", party_composition="강공 파티")],
        )
        self.assertIn("*1 니네베 - 강공 파티*", rendered)
        self.assertNotIn("**", rendered)

    def test_render_combat_italic_headline_no_stage(self):
        template = (
            "//Section Start//\n"
            "*{optional: stage_number} {boss_name} - {party_composition}*\n"
            "//Section End//"
        )
        rendered = render_description(
            template,
            sections=[DescriptionSection(boss_name="니네베", party_composition="강공 파티")],
        )
        self.assertEqual(rendered, "*니네베 - 강공 파티*")

    def test_render_combat_italic_headline_no_party(self):
        template = (
            "//Section Start//\n"
            "*{optional: stage_number} {boss_name} - {party_composition}*\n"
            "//Section End//"
        )
        rendered = render_description(
            template,
            sections=[DescriptionSection(boss_name="니네베")],
        )
        self.assertEqual(rendered, "*니네베*")

    def test_render_combat_no_colon_party_line(self):
        template = (
            "//Section Start//\n"
            "*{boss_name}*\n"
            "- {party[i].character} {party[i].character.M_level}{optional: party[i].character.equip}\n"
            "//Section End//"
        )
        rendered = render_description(
            template,
            sections=[
                DescriptionSection(
                    boss_name="니네베",
                    party=(PartyMember("엘렌", "M0", "전용 무기"),),
                )
            ],
        )
        self.assertIn("- 엘렌 M0 전용 무기", rendered)
        self.assertNotIn("엘렌:", rendered)

    def test_parse_gacha_fields_new_format(self):
        description = (
            "#gacha\n"
            "[2.7 시시아 가챠]\n"
            "- 캐릭터 스택: 반천 0\n"
            "- 엔진 스택: 보장 1\n"
        )
        fields = parse_gacha_fields(description)
        self.assertEqual(fields["character_is_guaranteed"], "반천")
        self.assertEqual(fields["character_stack"], "0")
        self.assertEqual(fields["equipment_type"], "엔진")
        self.assertEqual(fields["equipment_is_guaranteed"], "보장")
        self.assertEqual(fields["equipment_stack"], "1")

    def test_parse_gacha_fields_legacy_format(self):
        description = (
            "#gacha\n"
            "[2.7 시시아 가챠]\n"
            "- 캐릭터 반천 0스택\n"
            "- 엔진 반천 0스택\n"
        )
        fields = parse_gacha_fields(description)
        self.assertEqual(fields["character_is_guaranteed"], "반천")
        self.assertEqual(fields["character_stack"], "0")
        self.assertEqual(fields["equipment_type"], "엔진")
        self.assertEqual(fields["equipment_is_guaranteed"], "반천")
        self.assertEqual(fields["equipment_stack"], "0")

    def test_render_gacha_with_dedicated_fields(self):
        template = (
            "//Template: gacha//\n"
            "{[tags]}\n"
            "[{game_version} {pickup_character_name} 가챠]\n"
            "- 캐릭터 스택: {character_is_guaranteed} {character_stack}\n"
            "- {equipment_type} 스택: {equipment_is_guaranteed} {equipment_stack}\n"
        )
        rendered = render_description_template(
            template,
            "gacha",
            fields={
                "game_version": "2.7",
                "pickup_character_name": "시시아",
                "character_is_guaranteed": "반천",
                "character_stack": "0",
                "equipment_type": "엔진",
                "equipment_is_guaranteed": "보장",
                "equipment_stack": "1",
            },
            top_tags=["#zenlesszonezero", "#gacha"],
        )
        self.assertIn("[2.7 시시아 가챠]", rendered)
        self.assertIn("- 캐릭터 스택: 반천 0", rendered)
        self.assertIn("- 엔진 스택: 보장 1", rendered)


if __name__ == "__main__":
    unittest.main()
