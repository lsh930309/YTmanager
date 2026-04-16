from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from ytmanager.description import load_template
from ytmanager.migration import build_migration_candidates, candidate_summary, candidate_to_draft_record
from ytmanager.models import VideoSummary
from ytmanager.oauth import OAuthManager
from ytmanager.paths import user_data_dir
from ytmanager.rules import load_rule_mappings
from ytmanager.storage import AppDatabase
from ytmanager.youtube_api import YouTubeApiClient


def execute(request: Any) -> Mapping[str, Any]:
    return request.execute()


def fetch_current_videos(service: Any, limit: Optional[int]) -> list[VideoSummary]:
    client = YouTubeApiClient(service)
    return client.list_uploaded_videos(limit=limit or 10_000)


def write_report(payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = Path(".local") / "migration"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"description-migration-{stamp}.json"
    md_path = output_dir / f"description-migration-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    rows = payload["candidates"]
    lines: list[str] = []
    lines.append("# 설명란 정규화 마이그레이션 리포트")
    lines.append("")
    lines.append(f"- 생성 시각: {meta['generated_at']}")
    lines.append(f"- 모드: {'실제 적용' if meta['applied'] else 'dry-run'}")
    lines.append(f"- 전체 영상: {meta['total_count']}")
    lines.append(f"- 작업 대상([] 글머리): {meta['target_count']}")
    lines.append(f"- 변경 후보: {meta['changed_count']}")
    lines.append(f"- 적용 완료: {meta['applied_count']}")
    lines.append(f"- 템플릿 분포: {meta['template_counts']}")
    lines.append(f"- 파싱 신뢰도 분포: {meta['confidence_counts']}")
    lines.append("")
    lines.append("## 후보 요약")
    lines.append("")
    lines.append("| # | 제목 | 대상 | 템플릿 | 변경 | 신뢰도 | 필드 | 섹션 | 파티원 | 경고 |")
    lines.append("|---:|---|---|---|---|---|---|---:|---:|---|")
    for idx, row in enumerate(rows, 1):
        fields = row["fields"]
        field_text = " / ".join(filter(None, [fields.get("game_version"), fields.get("game_content_name"), fields.get("game_content_season_in_current_version")]))
        lines.append(
            "| {idx} | {title} | {target} | {template} | {changed} | {confidence} | {fields} | {sections} | {members} | {warnings} |".format(
                idx=idx,
                title=_escape(str(row["title"]))[:120],
                target="Y" if row["target"] else "-",
                template=row["template_name"] or "-",
                changed="Y" if row["changed"] else "-",
                confidence=row["parse_confidence"] or "-",
                fields=_escape(field_text),
                sections=row["section_count"],
                members=row["party_member_count"],
                warnings=len(row["warnings"]) + len(row["unmatched_lines"]),
            )
        )
    lines.append("")
    lines.append("## 변경 diff 샘플")
    lines.append("")
    changed_rows = [row for row in rows if row["changed"] and row["target"]]
    for row in changed_rows[:20]:
        lines.append(f"### {row['title']}")
        lines.append("```diff")
        lines.append(row["diff"][:6000])
        lines.append("```")
        lines.append("")
    if not changed_rows:
        lines.append("- 변경 후보가 없습니다.")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="[] 글머리 영상 설명란을 최신 템플릿으로 정규화합니다.")
    parser.add_argument("--limit", type=int, default=0, help="조회할 최대 영상 수. 0이면 전체 조회")
    parser.add_argument("--apply", action="store_true", help="dry-run이 아니라 실제 YouTube 설명을 업데이트합니다.")
    parser.add_argument("--yes", action="store_true", help="--apply 실행 확인 플래그")
    parser.add_argument("--min-confidence", choices=["low", "medium", "high"], default="medium", help="실제 적용 최소 파싱 신뢰도")
    parser.add_argument("--no-save-drafts", action="store_true", help="정규화 초안을 로컬 DB에 저장하지 않습니다.")
    args = parser.parse_args()

    if args.apply and not args.yes:
        raise SystemExit("실제 적용에는 --apply --yes가 모두 필요합니다.")

    service = OAuthManager().build_youtube_service(write_access=args.apply)
    client = YouTubeApiClient(service)
    videos = fetch_current_videos(service, args.limit if args.limit > 0 else None)
    template_text = load_template(Path("DESCRIPTION_TEMPLATE.md"))
    rules = load_rule_mappings()
    candidates = build_migration_candidates(videos, template_text, rules)

    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    min_rank = confidence_rank[args.min_confidence]
    applied_count = 0
    db = AppDatabase()
    try:
        for alias_path in (Path.cwd() / "character_aliases.json", user_data_dir() / "character_aliases.json"):
            db.load_character_aliases_from_file(alias_path)
        if not args.no_save_drafts:
            for candidate in candidates:
                draft = candidate_to_draft_record(candidate)
                if db.save_description_draft(draft, preserve_reviewed=True):
                    db.observe_draft_roster(candidate.video, draft)
        if args.apply:
            for candidate in candidates:
                parsed = candidate.parsed
                if not candidate.target or not candidate.changed or parsed is None:
                    continue
                if confidence_rank.get(parsed.confidence, 0) < min_rank:
                    continue
                db.save_snapshot(candidate.video)
                client.update_video_snippet(
                    candidate.video.video_id,
                    candidate.video.title,
                    candidate.normalized_description,
                    list(candidate.video.tags),
                )
                updated = VideoSummary(
                    video_id=candidate.video.video_id,
                    title=candidate.video.title,
                    description=candidate.normalized_description,
                    tags=candidate.video.tags,
                    thumbnail_url=candidate.video.thumbnail_url,
                    duration=candidate.video.duration,
                    privacy_status=candidate.video.privacy_status,
                    published_at=candidate.video.published_at,
                    category_id=candidate.video.category_id,
                    width_pixels=candidate.video.width_pixels,
                    height_pixels=candidate.video.height_pixels,
                    display_aspect_ratio=candidate.video.display_aspect_ratio,
                )
                db.save_videos([updated])
                applied_count += 1
    finally:
        db.close()

    summaries = [candidate_summary(candidate) for candidate in candidates]
    template_counts = Counter(row["template_name"] or "skipped" for row in summaries)
    confidence_counts = Counter(row["parse_confidence"] or "skipped" for row in summaries)
    payload = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "applied": args.apply,
            "min_confidence": args.min_confidence,
            "total_count": len(candidates),
            "target_count": sum(1 for candidate in candidates if candidate.target),
            "changed_count": sum(1 for candidate in candidates if candidate.target and candidate.changed),
            "applied_count": applied_count,
            "template_counts": dict(template_counts),
            "confidence_counts": dict(confidence_counts),
        },
        "candidates": summaries,
    }
    json_path, md_path = write_report(payload)
    print(f"전체 영상: {payload['meta']['total_count']}")
    print(f"작업 대상: {payload['meta']['target_count']}")
    print(f"변경 후보: {payload['meta']['changed_count']}")
    print(f"적용 완료: {applied_count}")
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
