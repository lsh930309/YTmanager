import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ytmanager.oauth import TokenStore


class TokenStoreTests(unittest.TestCase):
    def test_file_fallback_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore()
            with mock.patch.object(store, "_token_file", return_value=Path(tmp) / "token.json"):
                store._save_file_token({"token": "abc"})
                self.assertEqual(store._load_file_token(Path(tmp) / "token.json"), {"token": "abc"})

    def test_exists_uses_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TokenStore()
            token_path = Path(tmp) / "token.json"
            with mock.patch.object(store, "_token_file", return_value=token_path):
                with mock.patch("keyring.get_password", return_value=None):
                    self.assertFalse(store.exists())
                    store._save_file_token({"token": "abc"})
                    self.assertTrue(store.exists())


if __name__ == "__main__":
    unittest.main()
