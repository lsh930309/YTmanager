from __future__ import annotations

import argparse
from pathlib import Path

from ytmanager.character_master import dump_character_master_entries, load_character_master_entries
from ytmanager.master_builder import merge_master_entries


def main() -> int:
    parser = argparse.ArgumentParser(description="여러 character master JSON을 canonical key 기준으로 병합합니다.")
    parser.add_argument("inputs", nargs="+", type=Path, help="입력 character master JSON 경로들")
    parser.add_argument("--output", required=True, type=Path, help="병합 결과 JSON 경로")
    args = parser.parse_args()

    all_entries = []
    for path in args.inputs:
        all_entries.extend(load_character_master_entries(path))
    entries = merge_master_entries(all_entries)
    dump_character_master_entries(entries, args.output)
    print(f"병합 캐릭터: {len(entries)}")
    print(f"JSON 저장: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
