import tempfile
import unittest
from pathlib import Path

from ytmanager.character_master import CharacterMasterEntry, load_character_master_entries
from ytmanager.storage import AppDatabase


class CharacterMasterTests(unittest.TestCase):
    def test_entry_from_mapping_and_aliases(self):
        entry = CharacterMasterEntry.from_mapping(
            {
                "game_key": "honkai_starrail",
                "canonical_name_ko": "카스토리스",
                "canonical_name_en": "Castorice",
                "aliases_ko": ["카스", "김곰팡", "카스"],
            }
        )
        self.assertEqual(entry.aliases_ko, ("카스", "김곰팡"))
        self.assertIn("카스토리스", entry.aliases_for_resolution)
        self.assertIn("Castorice", entry.aliases_for_resolution)

    def test_load_character_master_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.json"
            path.write_text(
                '{"version":1,"characters":[{"game_key":"zenless_zone_zero","canonical_name_ko":"시시아","aliases_ko":["뱀댕이"]}]}',
                encoding="utf-8",
            )
            entries = load_character_master_entries(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].canonical_name_ko, "시시아")

    def test_storage_import_syncs_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.json"
            path.write_text(
                '{"version":1,"characters":[{"game_key":"honkai_starrail","canonical_name_ko":"카스토리스","aliases_ko":["카스","김곰팡"],"rarity":"5"}]}',
                encoding="utf-8",
            )
            db = AppDatabase(Path(tmp) / "app.sqlite3")
            try:
                count = db.load_character_master_from_file(path)
                self.assertEqual(count, 1)
                master = db.list_character_master("honkai_starrail")
                self.assertEqual(master[0].canonical_name_ko, "카스토리스")
                self.assertEqual(master[0].rarity, "5")
                self.assertEqual(db.resolve_character_alias("honkai_starrail", "김곰팡"), ("카스토리스", False))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
