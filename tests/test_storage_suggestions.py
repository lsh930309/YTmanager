import tempfile
import unittest
from pathlib import Path

from ytmanager.character_master import CharacterMasterEntry
from ytmanager.models import VideoSummary
from ytmanager.storage import AppDatabase, DescriptionDraftRecord


class StorageSuggestionTests(unittest.TestCase):
    def test_character_suggestions_merge_master_and_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AppDatabase(Path(tmp) / "app.sqlite3")
            try:
                db.upsert_character_master(CharacterMasterEntry("honkai_starrail", "카스토리스", aliases_ko=("김곰팡",), element="양자"))
                video = VideoSummary(video_id="v", title="[스타레일] 테스트 - 2026 04 15", description="")
                db.save_videos([video])
                db.upsert_character_alias("honkai_starrail", "카스토리스", ["김곰팡"])
                db.observe_draft_roster(
                    video,
                    DescriptionDraftRecord(
                        video_id="v",
                        sections=[{"party": [{"character": "김곰팡", "raw_name": "김곰팡", "character_rank": "명함", "character_rank_value": 0, "equipment_type": "전광", "equipment_rank": "전광", "equipment_rank_value": 1, "raw_status": "명전"}]}],
                    ),
                )
                suggestions = db.character_suggestions("honkai_starrail", "김곰")
                self.assertEqual(len(suggestions), 1)
                self.assertEqual(suggestions[0].canonical_name, "카스토리스")
                self.assertEqual(suggestions[0].owned_status, "명전")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
