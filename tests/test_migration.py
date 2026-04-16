import unittest

from ytmanager.migration import build_normalized_description, candidate_to_draft_record, is_managed_title
from ytmanager.storage import DRAFT_STATUS_DRAFT
from ytmanager.models import VideoSummary

TEMPLATE = """//Template: combat//
{[tags]}
[{game_version} {game_content_name} {game_content_season_in_current_version}]

//Section Start//
*{optional: stage_number} {boss_name} - {party_composition}*
- {party[i].canonical_name} {party[i].status_label}
//Section End//

//Template: gacha//
{[tags]}
[{game_version} {pickup_character_name} 가챠]
- 캐릭터 스택: {character_is_guaranteed} {character_stack}
- {equipment_type} 스택: {equipment_is_guaranteed} {equipment_stack}
"""


class MigrationTests(unittest.TestCase):
    def test_is_managed_title(self):
        self.assertTrue(is_managed_title("[젠존제] 테스트"))
        self.assertFalse(is_managed_title("젠존제 테스트"))

    def test_build_normalized_description_skips_unmanaged_title(self):
        video = VideoSummary(video_id="1", title="그냥 영상", description="본문")
        candidate = build_normalized_description(video, TEMPLATE)
        self.assertFalse(candidate.target)
        self.assertFalse(candidate.changed)

    def test_build_normalized_description_for_combat(self):
        video = VideoSummary(
            video_id="1",
            title="[젠존제] 테스트",
            description="#zenlesszonezero\n[2.7 강습전 2차]\n\n*침식체 - 시드 전기 강공팟*\n- 시시아 1돌전엔\n- 시드 1돌전엔",
        )
        candidate = build_normalized_description(video, TEMPLATE)
        self.assertTrue(candidate.target)
        self.assertEqual(candidate.template_name, "combat")
        self.assertIn("*침식체 - 시드 전기 강공팟*", candidate.normalized_description)
        self.assertIn("- 시시아 1돌전엔", candidate.normalized_description)

    def test_build_normalized_description_for_gacha(self):
        video = VideoSummary(
            video_id="1",
            title="[젠존제] 뽑기",
            description="#zenlesszonezero #gacha\n[2.7 시시아 가챠]\n\n*시작 스택*\n- 캐릭터 반천 0스택\n- 엔진 반천 0스택",
        )
        candidate = build_normalized_description(video, TEMPLATE)
        self.assertEqual(candidate.template_name, "gacha")
        self.assertIn("#zenlesszonezero #gacha", candidate.normalized_description)
        self.assertIn("[2.7 시시아 가챠]", candidate.normalized_description)
        self.assertIn("- 캐릭터 스택: 반천 0", candidate.normalized_description)
        self.assertIn("- 엔진 스택: 반천 0", candidate.normalized_description)
        # 전용 필드가 채워졌는지 확인
        self.assertEqual(candidate.fields.get("character_is_guaranteed"), "반천")
        self.assertEqual(candidate.fields.get("character_stack"), "0")
        self.assertEqual(candidate.fields.get("equipment_type"), "엔진")

    def test_candidate_to_draft_record(self):
        video = VideoSummary(
            video_id="1",
            title="[젠존제] 테스트",
            description="#zenlesszonezero\n[2.7 강습전 2차]\n\n*침식체 - 시드 전기 강공팟*\n- 시시아 1돌전엔",
        )
        candidate = build_normalized_description(video, TEMPLATE)
        draft = candidate_to_draft_record(candidate)
        self.assertEqual(draft.video_id, "1")
        self.assertEqual(draft.status, DRAFT_STATUS_DRAFT)
        self.assertEqual(draft.template_name, "combat")
        self.assertEqual(draft.fields["game_version"], "2.7")
        self.assertEqual(draft.sections[0]["boss_name"], "침식체")
        self.assertEqual(draft.sections[0]["party"][0]["character_rank"], "1돌")
        self.assertEqual(draft.sections[0]["party"][0]["equipment_type"], "전엔")
        self.assertEqual(draft.top_tags, ["#zenlesszonezero"])


if __name__ == "__main__":
    unittest.main()
