from __future__ import annotations

import argparse
from pathlib import Path

from ytmanager.character_sources import SOURCE_CATALOG
from ytmanager.master_builder import DEFAULT_BUILD_SOURCES, build_character_master, result_to_json


def main() -> int:
    parser = argparse.ArgumentParser(description="캐릭터 마스터 사전을 일괄 수집·병합·선택 import합니다.")
    parser.add_argument("--source", action="append", choices=sorted(SOURCE_CATALOG), help="수집할 소스. 여러 번 지정 가능. 생략하면 기본 소스 전체")
    parser.add_argument("--output-dir", type=Path, default=Path(".local") / "master", help="소스별 JSON/병합 JSON/리포트 출력 디렉터리")
    parser.add_argument("--apply", action="store_true", help="병합 결과를 로컬 DB에 import합니다")
    parser.add_argument("--database", type=Path, help="테스트/개발용 SQLite DB 경로")
    parser.add_argument("--fail-fast", action="store_true", help="소스 하나 실패 시 즉시 중단")
    parser.add_argument("--json", action="store_true", help="결과 요약을 JSON으로 출력")
    args = parser.parse_args()

    source_keys = tuple(args.source) if args.source else DEFAULT_BUILD_SOURCES
    result = build_character_master(
        source_keys=source_keys,
        output_dir=args.output_dir,
        apply=args.apply,
        database=args.database,
        continue_on_error=not args.fail_fast,
    )
    if args.json:
        print(result_to_json(result))
    else:
        print(f"소스 수: {len(result.sources)}")
        for source in result.sources:
            print(f"- {source.source_key}: {'OK' if source.ok else 'FAIL'} {source.count if source.ok else source.error}")
        print(f"병합 캐릭터: {result.merged_count}")
        print(f"DB import: {result.imported_count}")
        print(f"병합 JSON: {result.merged_path}")
        print(f"리포트: {result.report_path}")
        if result.quality_warnings:
            print("품질 경고:")
            for warning in result.quality_warnings:
                print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
