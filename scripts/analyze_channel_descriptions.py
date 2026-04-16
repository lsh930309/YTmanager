from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from googleapiclient.errors import HttpError

from ytmanager.description import load_template, parse_description
from ytmanager.oauth import OAuthManager
from ytmanager.paths import user_data_dir

PREFERRED_PARTS = [
    "snippet",
    "contentDetails",
    "status",
    "statistics",
    "player",
    "recordingDetails",
    "localizations",
    "fileDetails",
    "processingDetails",
]
FALLBACK_PARTS = ["snippet", "contentDetails", "status", "statistics", "player", "recordingDetails", "localizations"]
BASIC_PARTS = ["snippet", "contentDetails", "status"]


def execute(request: Any) -> Mapping[str, Any]:
    return request.execute()


def get_uploads_playlist_id(service: Any) -> str:
    response = execute(service.channels().list(part="contentDetails,snippet", mine=True, maxResults=1))
    items = response.get("items", [])
    if not items:
        raise RuntimeError("로그인한 계정에서 YouTube 채널을 찾지 못했습니다.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_uploaded_video_ids(service: Any, limit: Optional[int]) -> list[str]:
    playlist_id = get_uploads_playlist_id(service)
    video_ids: list[str] = []
    page_token: Optional[str] = None
    while True:
        max_results = 50
        if limit is not None:
            remaining = limit - len(video_ids)
            if remaining <= 0:
                break
            max_results = min(max_results, remaining)
        response = execute(
            service.playlistItems().list(
                part="contentDetails,snippet,status",
                playlistId=playlist_id,
                maxResults=max_results,
                pageToken=page_token,
            )
        )
        for item in response.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def fetch_video_resources(service: Any, video_ids: list[str]) -> tuple[list[Mapping[str, Any]], str, list[str]]:
    resources: list[Mapping[str, Any]] = []
    warnings: list[str] = []
    used_parts = ",".join(PREFERRED_PARTS)
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        response, part, warning = fetch_video_chunk(service, chunk, PREFERRED_PARTS)
        if warning:
            warnings.append(warning)
        used_parts = part
        resources.extend(response.get("items", []))
    return resources, used_parts, warnings


def fetch_video_chunk(service: Any, video_ids: list[str], parts: list[str]) -> tuple[Mapping[str, Any], str, str]:
    attempts = [parts, FALLBACK_PARTS, BASIC_PARTS]
    last_error = ""
    for attempt in attempts:
        part = ",".join(dict.fromkeys(attempt))
        try:
            response = execute(service.videos().list(part=part, id=",".join(video_ids), maxResults=len(video_ids)))
            warning = last_error and f"일부 part 조회 실패 후 {part}로 fallback: {last_error}"
            return response, part, warning
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", "?")
            content = getattr(exc, "content", b"")
            if isinstance(content, bytes):
                content_text = content.decode("utf-8", errors="ignore")[:500]
            else:
                content_text = str(content)[:500]
            last_error = f"HTTP {status} {content_text}"
            if status not in {400, 403}:
                raise
    raise RuntimeError(f"videos.list 메타데이터 조회 실패: {last_error}")


def summarize(resources: list[Mapping[str, Any]], template_text: str) -> tuple[list[dict[str, Any]], Counter[str], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    confidence_counter: Counter[str] = Counter()
    version_counter: Counter[str] = Counter()
    content_counter: Counter[str] = Counter()
    for resource in resources:
        snippet = resource.get("snippet", {}) or {}
        description = str(snippet.get("description", "") or "")
        parsed = parse_description(template_text, description)
        confidence_counter[parsed.confidence] += 1
        if parsed.fields.get("game_version"):
            version_counter[parsed.fields["game_version"]] += 1
        if parsed.fields.get("game_content_name"):
            content_counter[parsed.fields["game_content_name"]] += 1
        rows.append(
            {
                "video_id": resource.get("id", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description_length": len(description),
                "parsed": {
                    "confidence": parsed.confidence,
                    "top_tags": list(parsed.top_tags),
                    "fields": dict(parsed.fields),
                    "section_count": len(parsed.sections),
                    "party_member_count": sum(len(section.party) for section in parsed.sections),
                    "timestamp_count": len(parsed.timestamps),
                    "unmatched_lines": list(parsed.unmatched_lines),
                    "warnings": list(parsed.warnings),
                },
                "metadata_parts_present": sorted(key for key in resource.keys() if key not in {"kind", "etag"}),
            }
        )
    return rows, confidence_counter, version_counter, content_counter


def write_outputs(rows: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = Path(".local") / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"youtube-metadata-parse-{stamp}.json"
    md_path = output_dir / f"youtube-metadata-parse-{stamp}.md"
    json_path.write_text(json.dumps({"meta": meta, "videos": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(rows, meta), encoding="utf-8")
    return json_path, md_path


def render_markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# YouTube 설명란 구조화 파싱 리포트")
    lines.append("")
    lines.append(f"- 생성 시각: {meta['generated_at']}")
    lines.append(f"- 분석 영상 수: {meta['video_count']}")
    lines.append(f"- videos.list part: `{meta['used_parts']}`")
    lines.append(f"- 신뢰도 분포: {meta['confidence_counts']}")
    if meta.get("warnings"):
        lines.append(f"- 메타데이터 조회 경고: {len(meta['warnings'])}건")
    lines.append("")
    lines.append("## 필드 분포")
    lines.append("")
    lines.append(f"- game_version: {meta['top_versions']}")
    lines.append(f"- game_content_name: {meta['top_contents']}")
    lines.append("")
    lines.append("## 영상별 파싱 요약")
    lines.append("")
    lines.append("| # | 제목 | 신뢰도 | 헤더 필드 | 태그 | 섹션 | 파티원 | 타임스탬프 | 경고/미매칭 |")
    lines.append("|---:|---|---|---|---|---:|---:|---:|---|")
    for idx, row in enumerate(rows, 1):
        parsed = row["parsed"]
        fields = parsed["fields"]
        header = " / ".join(filter(None, [fields.get("game_version"), fields.get("game_content_name"), fields.get("game_content_season_in_current_version")]))
        issue_count = len(parsed["warnings"]) + len(parsed["unmatched_lines"])
        issue = "" if issue_count == 0 else f"{issue_count}건"
        lines.append(
            "| {idx} | {title} | {confidence} | {header} | {tags} | {sections} | {members} | {timestamps} | {issue} |".format(
                idx=idx,
                title=_escape_table(str(row["title"]))[:120],
                confidence=parsed["confidence"],
                header=_escape_table(header),
                tags=_escape_table(" ".join(parsed["top_tags"])),
                sections=parsed["section_count"],
                members=parsed["party_member_count"],
                timestamps=parsed["timestamp_count"],
                issue=issue,
            )
        )
    lines.append("")
    lines.append("## 파싱 이슈 샘플")
    lines.append("")
    issue_rows = [row for row in rows if row["parsed"]["warnings"] or row["parsed"]["unmatched_lines"]]
    if not issue_rows:
        lines.append("- 발견된 경고/미매칭 라인이 없습니다.")
    else:
        for row in issue_rows[:20]:
            parsed = row["parsed"]
            lines.append(f"### {row['title']}")
            for warning in parsed["warnings"]:
                lines.append(f"- 경고: {warning}")
            for line in parsed["unmatched_lines"][:10]:
                lines.append(f"- 미매칭: `{line}`")
            lines.append("")
    return "\n".join(lines)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="로그인된 YouTube 채널 설명란을 템플릿 기준으로 파싱합니다.")
    parser.add_argument("--limit", type=int, default=0, help="분석할 최대 영상 수. 0이면 업로드 전체를 조회합니다.")
    args = parser.parse_args()

    service = OAuthManager().build_youtube_service(write_access=False)
    limit = args.limit if args.limit and args.limit > 0 else None
    video_ids = list_uploaded_video_ids(service, limit)
    resources, used_parts, fetch_warnings = fetch_video_resources(service, video_ids)
    template_text = load_template(Path("DESCRIPTION_TEMPLATE.md"))
    rows, confidence_counter, version_counter, content_counter = summarize(resources, template_text)
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "video_count": len(rows),
        "used_parts": used_parts,
        "warnings": fetch_warnings,
        "confidence_counts": dict(confidence_counter),
        "top_versions": version_counter.most_common(20),
        "top_contents": content_counter.most_common(20),
        "user_data_dir": str(user_data_dir()),
    }
    json_path, md_path = write_outputs(rows, meta)
    print(f"분석 영상 수: {len(rows)}")
    print(f"신뢰도 분포: {dict(confidence_counter)}")
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")
    if fetch_warnings:
        print(f"메타데이터 조회 경고: {len(fetch_warnings)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
