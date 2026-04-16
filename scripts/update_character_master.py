from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Iterable

from ytmanager.character_master import CharacterMasterEntry, dump_character_master_entries
from ytmanager.character_sources import SOURCE_CATALOG, collect_source
from ytmanager.storage import AppDatabase


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "YTmanager/0.1 character-master-builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - user-provided source URL for local tool
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_entries_from_regex(text: str, game_key: str, pattern: str, source_name: str, source_url: str) -> list[CharacterMasterEntry]:
    regex = re.compile(pattern, re.MULTILINE)
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    for match in regex.finditer(text):
        groups = match.groupdict()
        name = (groups.get("name") or (match.group(1) if match.groups() else "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        aliases = [value.strip() for value in (groups.get("aliases") or "").split(",") if value.strip()]
        entries.append(
            CharacterMasterEntry(
                game_key=game_key,
                canonical_name_ko=name,
                canonical_name_en=(groups.get("name_en") or "").strip(),
                display_name=name,
                aliases_ko=tuple(aliases),
                rarity=(groups.get("rarity") or "").strip(),
                element=(groups.get("element") or "").strip(),
                role_or_path=(groups.get("role_or_path") or groups.get("role") or groups.get("path") or "").strip(),
                source_name=source_name,
                source_url=source_url,
            )
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="URL/정규식 기반 캐릭터 마스터 초안 수집기입니다.")
    parser.add_argument("--list-sources", action="store_true", help="내장 소스 카탈로그를 출력합니다.")
    parser.add_argument("--source", choices=sorted(SOURCE_CATALOG), help="내장 소스 키")
    parser.add_argument("--game-key", help="예: zenless_zone_zero")
    parser.add_argument("--url", help="공식 위키/나무위키 등 수집 대상 URL")
    parser.add_argument("--name-regex", help="캐릭터명을 캡처하는 정규식. named group name 권장")
    parser.add_argument("--source-name", default="web", help="source_name 저장값")
    parser.add_argument("--output", type=Path, help="수집 결과 JSON 저장 경로")
    parser.add_argument("--database", type=Path, help="테스트/개발용 SQLite DB 경로")
    parser.add_argument("--apply", action="store_true", help="수집 결과를 DB에 저장합니다")
    args = parser.parse_args()

    if args.list_sources:
        for key, source in SOURCE_CATALOG.items():
            print(f"{key}: {source.description} ({source.url})")
        return 0

    if args.source:
        entries = collect_source(args.source)
    else:
        if not args.game_key or not args.url or not args.name_regex:
            parser.error("--source를 쓰지 않을 경우 --game-key, --url, --name-regex가 필요합니다.")
        text = fetch_text(args.url)
        entries = extract_entries_from_regex(text, args.game_key, args.name_regex, args.source_name, args.url)
    print(f"수집 후보: {len(entries)}")
    if args.output:
        dump_character_master_entries(entries, args.output)
        print(f"JSON 저장: {args.output}")
    if args.apply:
        db = AppDatabase(args.database)
        try:
            for entry in entries:
                db.upsert_character_master(entry)
            print(f"DB 저장: {len(entries)}")
        finally:
            db.close()
    else:
        print(json.dumps({"characters": [entry.to_json_dict() for entry in entries[:20]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
