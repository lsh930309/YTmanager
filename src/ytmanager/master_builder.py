from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from ytmanager.character_master import CharacterMasterEntry, dump_character_master_entries
from ytmanager.character_sources import SOURCE_CATALOG, collect_source
from ytmanager.storage import AppDatabase

DEFAULT_BUILD_SOURCES = ("zzz_gg_ko", "hoyodb_hsr_ko", "namu_hsr_ko", "namu_ww_ko", "endfield_wiki_en")
KOREAN_HSR_PATHS = {"파멸", "수렵", "지식", "화합", "공허", "보존", "풍요", "기억", "환락"}


@dataclass(frozen=True)
class SourceBuildResult:
    source_key: str
    ok: bool
    count: int = 0
    output_path: str = ""
    error: str = ""


@dataclass(frozen=True)
class MasterBuildResult:
    sources: tuple[SourceBuildResult, ...]
    merged_count: int
    merged_path: str
    report_path: str
    imported_count: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)
    game_counts: dict[str, int] = field(default_factory=dict)
    quality_warnings: tuple[str, ...] = ()


def collect_sources_to_directory(source_keys: Sequence[str], output_dir: Path, continue_on_error: bool = True) -> tuple[list[CharacterMasterEntry], list[SourceBuildResult]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_entries: list[CharacterMasterEntry] = []
    results: list[SourceBuildResult] = []
    for source_key in source_keys:
        try:
            entries = collect_source(source_key)
            source_path = output_dir / f"{source_key}.json"
            dump_character_master_entries(entries, source_path)
            all_entries.extend(entries)
            results.append(SourceBuildResult(source_key=source_key, ok=True, count=len(entries), output_path=str(source_path)))
        except Exception as exc:
            results.append(SourceBuildResult(source_key=source_key, ok=False, error=str(exc)))
            if not continue_on_error:
                raise
    return all_entries, results


def merge_master_entries(entries: Iterable[CharacterMasterEntry]) -> list[CharacterMasterEntry]:
    merged: dict[tuple[str, str], CharacterMasterEntry] = {}
    for entry in entries:
        key = (entry.game_key, entry.canonical_name_ko.casefold())
        if key not in merged:
            merged[key] = entry
            continue
        merged[key] = merge_two_entries(merged[key], entry)
    return sorted(merged.values(), key=lambda item: (item.game_key, item.canonical_name_ko))


def merge_two_entries(existing: CharacterMasterEntry, incoming: CharacterMasterEntry) -> CharacterMasterEntry:
    aliases = tuple(dict.fromkeys([*existing.aliases_ko, *incoming.aliases_ko]))
    source_name = existing.source_name if existing.source_name == incoming.source_name else ",".join(dict.fromkeys([*existing.source_name.split(","), *incoming.source_name.split(",")]))
    source_url = existing.source_url if existing.source_url == incoming.source_url else ",".join(value for value in dict.fromkeys([existing.source_url, incoming.source_url]) if value)
    role_or_path = _choose_role_or_path(existing, incoming)
    return CharacterMasterEntry(
        game_key=existing.game_key,
        canonical_name_ko=existing.canonical_name_ko,
        canonical_name_en=existing.canonical_name_en or incoming.canonical_name_en,
        display_name=existing.display_name or incoming.display_name,
        aliases_ko=aliases,
        rarity=existing.rarity or incoming.rarity,
        element=existing.element or incoming.element,
        role_or_path=role_or_path,
        source_name=source_name,
        source_url=source_url,
        extra={**dict(incoming.extra), **dict(existing.extra)},
    )


def _choose_role_or_path(existing: CharacterMasterEntry, incoming: CharacterMasterEntry) -> str:
    if not existing.role_or_path:
        return incoming.role_or_path
    if not incoming.role_or_path:
        return existing.role_or_path
    if existing.game_key == "honkai_starrail":
        if incoming.role_or_path in KOREAN_HSR_PATHS and existing.role_or_path not in KOREAN_HSR_PATHS:
            return incoming.role_or_path
        if existing.role_or_path in KOREAN_HSR_PATHS:
            return existing.role_or_path
    return existing.role_or_path


def build_quality_warnings(entries: Sequence[CharacterMasterEntry]) -> tuple[str, ...]:
    warnings: list[str] = []
    by_game: dict[str, list[CharacterMasterEntry]] = defaultdict(list)
    for entry in entries:
        by_game[entry.game_key].append(entry)
    for game_key, game_entries in by_game.items():
        missing_element = sum(1 for entry in game_entries if not entry.element)
        missing_role = sum(1 for entry in game_entries if not entry.role_or_path)
        missing_rarity = sum(1 for entry in game_entries if not entry.rarity)
        if missing_element:
            warnings.append(f"{game_key}: element 누락 {missing_element}건")
        if missing_role:
            warnings.append(f"{game_key}: role_or_path 누락 {missing_role}건")
        if missing_rarity:
            warnings.append(f"{game_key}: rarity 누락 {missing_rarity}건")
    return tuple(warnings)


def write_master_report(entries: Sequence[CharacterMasterEntry], source_results: Sequence[SourceBuildResult], report_path: Path, imported_count: int = 0) -> None:
    game_counts = Counter(entry.game_key for entry in entries)
    source_counts = Counter(entry.source_name for entry in entries)
    warnings = build_quality_warnings(entries)
    lines: list[str] = []
    lines.append("# 캐릭터 마스터 사전 빌드 리포트")
    lines.append("")
    lines.append(f"- 병합 캐릭터 수: {len(entries)}")
    lines.append(f"- DB import 수: {imported_count}")
    lines.append(f"- 게임별 수: {dict(game_counts)}")
    lines.append(f"- 소스별 수: {dict(source_counts)}")
    lines.append("")
    lines.append("## 소스 결과")
    lines.append("")
    for result in source_results:
        if result.ok:
            lines.append(f"- {result.source_key}: {result.count}건 → `{result.output_path}`")
        else:
            lines.append(f"- {result.source_key}: 실패 — {result.error}")
    lines.append("")
    lines.append("## 품질 경고")
    lines.append("")
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append("## 샘플")
    lines.append("")
    for entry in entries[:30]:
        lines.append(f"- `{entry.game_key}` {entry.canonical_name_ko} / {entry.rarity} / {entry.element} / {entry.role_or_path} / aliases={list(entry.aliases_ko)}")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def build_character_master(source_keys: Sequence[str], output_dir: Path, apply: bool = False, database: Path | None = None, continue_on_error: bool = True) -> MasterBuildResult:
    entries, source_results = collect_sources_to_directory(source_keys, output_dir, continue_on_error=continue_on_error)
    merged = merge_master_entries(entries)
    merged_path = output_dir / "character_master.merged.json"
    report_path = output_dir / "character_master.report.md"
    dump_character_master_entries(merged, merged_path)
    imported_count = 0
    if apply:
        db = AppDatabase(database)
        try:
            for entry in merged:
                db.upsert_character_master(entry)
            imported_count = len(merged)
        finally:
            db.close()
    write_master_report(merged, source_results, report_path, imported_count=imported_count)
    return MasterBuildResult(
        sources=tuple(source_results),
        merged_count=len(merged),
        merged_path=str(merged_path),
        report_path=str(report_path),
        imported_count=imported_count,
        source_counts=dict(Counter(entry.source_name for entry in merged)),
        game_counts=dict(Counter(entry.game_key for entry in merged)),
        quality_warnings=build_quality_warnings(merged),
    )


def result_to_json(result: MasterBuildResult) -> str:
    payload = {
        "sources": [result_item.__dict__ for result_item in result.sources],
        "merged_count": result.merged_count,
        "merged_path": result.merged_path,
        "report_path": result.report_path,
        "imported_count": result.imported_count,
        "source_counts": result.source_counts,
        "game_counts": result.game_counts,
        "quality_warnings": list(result.quality_warnings),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
