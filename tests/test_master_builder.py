import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ytmanager.character_master import CharacterMasterEntry, load_character_master_entries
from ytmanager.master_builder import build_character_master, merge_master_entries
from ytmanager.storage import AppDatabase


class MasterBuilderTests(unittest.TestCase):
    def test_merge_master_entries_combines_aliases_and_missing_fields(self):
        merged = merge_master_entries(
            [
                CharacterMasterEntry("game", "캐릭터", aliases_ko=("별칭1",), source_name="a"),
                CharacterMasterEntry("game", "캐릭터", aliases_ko=("별칭2",), rarity="5", source_name="b"),
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].aliases_ko, ("별칭1", "별칭2"))
        self.assertEqual(merged[0].rarity, "5")
        self.assertEqual(merged[0].source_name, "a,b")

    def test_merge_prefers_korean_hsr_path(self):
        merged = merge_master_entries(
            [
                CharacterMasterEntry("honkai_starrail", "카스토리스", element="양자", role_or_path="Warlock", source_name="hoyodb"),
                CharacterMasterEntry("honkai_starrail", "카스토리스", role_or_path="기억", source_name="namu"),
            ]
        )
        self.assertEqual(merged[0].element, "양자")
        self.assertEqual(merged[0].role_or_path, "기억")

    def test_build_character_master_with_mocked_collectors(self):
        def fake_collect(source_key):
            return [CharacterMasterEntry(source_key, "캐릭터", aliases_ko=(source_key,), source_name=source_key)]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with mock.patch("ytmanager.master_builder.collect_source", side_effect=fake_collect):
                result = build_character_master(("a", "b"), Path(tmp) / "out", apply=True, database=db_path)
            self.assertEqual(result.merged_count, 2)
            self.assertEqual(result.imported_count, 2)
            self.assertTrue(Path(result.merged_path).exists())
            self.assertTrue(Path(result.report_path).exists())
            db = AppDatabase(db_path)
            try:
                self.assertEqual(len(db.list_character_master()), 2)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
