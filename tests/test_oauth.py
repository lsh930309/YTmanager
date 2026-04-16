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


if __name__ == "__main__":
    unittest.main()
