from __future__ import annotations

import argparse
from pathlib import Path

from ytmanager.storage import AppDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="캐릭터 마스터 JSON을 로컬 DB에 가져옵니다.")
    parser.add_argument("path", type=Path, help="character_master JSON 경로")
    parser.add_argument("--database", type=Path, help="테스트/개발용 SQLite DB 경로")
    parser.add_argument("--no-sync-aliases", action="store_true", help="character_aliases 동기화를 건너뜁니다.")
    args = parser.parse_args()

    db = AppDatabase(args.database)
    try:
        count = db.load_character_master_from_file(args.path, sync_aliases=not args.no_sync_aliases)
        print(f"가져온 캐릭터: {count}")
        print(f"마스터 총계: {len(db.list_character_master())}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
