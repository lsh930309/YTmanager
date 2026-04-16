from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ytmanager.description import (
    DescriptionSection,
    ParsedDescription,
    load_template_library,
    parse_description,
    parse_gacha_fields,
    render_description_template,
)
from ytmanager.models import RuleMapping, TimestampEntry, VideoSummary
from ytmanager.rules import DEFAULT_RULES, extract_title_prefix, top_tags_for_title, unique_tags
from ytmanager.storage import DRAFT_STATUS_DRAFT, DRAFT_STATUS_SKIPPED, DescriptionDraftRecord


@dataclass(frozen=True)
class DescriptionMigrationCandidate:
    video: VideoSummary
    target: bool
    template_name: str
    parsed: ParsedDescription | None
    normalized_description: str
    changed: bool
    fields: Mapping[str, str] | None = None
    sections: Sequence[DescriptionSection] = ()
    timestamps: Sequence[TimestampEntry] = ()
    top_tags: Sequence[str] = ()
    skip_reason: str = ""
    diff: str = ""


def is_managed_title(title: str) -> bool:
    return extract_title_prefix(title) is not None


def choose_template_name(video: VideoSummary, parsed: ParsedDescription | None = None) -> str:
    haystack_parts = [video.title]
    if parsed is not None:
        fields = parsed.fields
        haystack_parts.extend(str(value) for value in fields.values())
        haystack_parts.extend(parsed.top_tags)
    haystack = " ".join(haystack_parts).casefold()
    if any(keyword in haystack for keyword in ("가챠", "픽업", "#gacha", "뽑기", "반천")):
        return "gacha"
    return "combat"


def build_normalized_description(
    video: VideoSummary,
    template_text: str,
    rules: Iterable[RuleMapping] = DEFAULT_RULES,
) -> DescriptionMigrationCandidate:
    if not is_managed_title(video.title):
        return DescriptionMigrationCandidate(
            video=video,
            target=False,
            template_name="",
            parsed=None,
            normalized_description=video.description,
            changed=False,
            fields={},
            sections=(),
            timestamps=(),
            top_tags=(),
            skip_reason="제목이 [] 글머리로 시작하지 않아 작업 대상이 아닙니다.",
        )

    title_prefix = extract_title_prefix(video.title)
    parsed = parse_description(template_text, video.description, title_prefix=title_prefix)
    template_name = choose_template_name(video, parsed)
    library = load_template_library(template_text)
    if template_name not in library:
        template_name = "combat" if "combat" in library else next(iter(library.keys()))

    fields = _fields_for_render(video, parsed, template_name)
    sections = _sections_for_render(parsed) if template_name != "gacha" else ()
    timestamps = _timestamps_for_render(parsed)
    tags = _tags_for_render(video, parsed, rules)
    normalized = render_description_template(
        template_text,
        template_name,
        fields=fields,
        top_tags=tags,
        timestamps=timestamps,
        sections=sections,
    )
    diff = "\n".join(
        difflib.unified_diff(
            video.description.splitlines(),
            normalized.splitlines(),
            fromfile="현재 설명",
            tofile="정규화 설명",
            lineterm="",
        )
    )
    return DescriptionMigrationCandidate(
        video=video,
        target=True,
        template_name=template_name,
        parsed=parsed,
        normalized_description=normalized,
        changed=normalized.strip() != video.description.strip(),
        fields=fields,
        sections=sections,
        timestamps=timestamps,
        top_tags=tags,
        diff=diff,
    )


def build_migration_candidates(
    videos: Sequence[VideoSummary],
    template_text: str,
    rules: Iterable[RuleMapping] = DEFAULT_RULES,
) -> list[DescriptionMigrationCandidate]:
    return [build_normalized_description(video, template_text, rules) for video in videos]


def _fields_for_render(video: VideoSummary, parsed: ParsedDescription, template_name: str = "combat") -> Mapping[str, str]:
    fields = dict(parsed.fields)
    if not fields:
        inferred = infer_fields_from_title(video.title)
        fields.update(inferred)
    if template_name == "gacha":
        # gacha 헤더 "[버전 캐릭터명 가챠]"에서 파싱된 game_content_name을 pickup_character_name으로 복사
        if "game_content_name" in fields and "pickup_character_name" not in fields:
            fields["pickup_character_name"] = fields["game_content_name"]
        fields.update(parse_gacha_fields(video.description))
    return fields


def infer_fields_from_title(title: str) -> dict[str, str]:
    """제목만으로 최소 필드를 추정한다.

    기존 설명에 헤더가 없는 과거 영상은 자동 적용 전 검토가 필요하므로 보수적으로
    제목 글머리 뒤 첫 단어를 콘텐츠명 후보로만 둔다.
    """
    prefix = extract_title_prefix(title)
    if not prefix:
        return {}
    rest = title.split("]", 1)[1].strip() if "]" in title else title
    rest = rest.rsplit(" - ", 1)[0].strip()
    first_word = rest.split(maxsplit=1)[0] if rest else ""
    return {"game_content_name": first_word} if first_word else {}


def _sections_for_render(parsed: ParsedDescription) -> Sequence[DescriptionSection]:
    return parsed.sections


def _timestamps_for_render(parsed: ParsedDescription) -> Sequence[TimestampEntry]:
    return parsed.timestamps


def _tags_for_render(video: VideoSummary, parsed: ParsedDescription, rules: Iterable[RuleMapping]) -> list[str]:
    rule_tags = top_tags_for_title(video.title, rules)
    return unique_tags([*rule_tags, *parsed.top_tags])


def candidate_summary(candidate: DescriptionMigrationCandidate) -> dict[str, object]:
    parsed = candidate.parsed
    return {
        "video_id": candidate.video.video_id,
        "title": candidate.video.title,
        "target": candidate.target,
        "template_name": candidate.template_name,
        "changed": candidate.changed,
        "skip_reason": candidate.skip_reason,
        "parse_confidence": parsed.confidence if parsed else "",
        "fields": dict(candidate.fields or (parsed.fields if parsed else {})),
        "tags": list(candidate.top_tags or (parsed.top_tags if parsed else [])),
        "section_count": len(candidate.sections or (parsed.sections if parsed else [])),
        "party_member_count": sum(len(section.party) for section in (candidate.sections or (parsed.sections if parsed else []))),
        "timestamp_count": len(candidate.timestamps or (parsed.timestamps if parsed else [])),
        "warnings": list(parsed.warnings) if parsed else [],
        "unmatched_lines": list(parsed.unmatched_lines) if parsed else [],
        "diff": candidate.diff,
    }


def candidate_to_draft_record(candidate: DescriptionMigrationCandidate) -> DescriptionDraftRecord:
    parsed = candidate.parsed
    return DescriptionDraftRecord(
        video_id=candidate.video.video_id,
        template_name=candidate.template_name or "combat",
        status=DRAFT_STATUS_DRAFT if candidate.target else DRAFT_STATUS_SKIPPED,
        fields=dict(candidate.fields or {}),
        sections=[section_to_dict(section) for section in candidate.sections],
        timestamps=[timestamp_to_dict(timestamp) for timestamp in candidate.timestamps],
        top_tags=list(candidate.top_tags),
        rendered_description=candidate.normalized_description,
        parse_confidence=parsed.confidence if parsed else "",
        warnings=list(parsed.warnings) if parsed else [candidate.skip_reason] if candidate.skip_reason else [],
        unmatched_lines=list(parsed.unmatched_lines) if parsed else [],
    )


def section_to_dict(section: DescriptionSection) -> dict[str, object]:
    return {
        "stage_number": section.stage_number,
        "boss_name": section.boss_name,
        "party_composition": section.party_composition,
        "party": [
            {
                "character": member.character,
                "m_level": member.m_level,
                "equip": member.equip,
                "raw_name": member.raw_name,
                "canonical_name": member.canonical_name,
                "character_rank": member.character_rank,
                "character_rank_value": member.character_rank_value,
                "equipment_type": member.equipment_type,
                "equipment_rank": member.equipment_rank,
                "equipment_rank_value": member.equipment_rank_value,
                "raw_status": member.raw_status,
                "parse_warnings": list(member.parse_warnings),
            }
            for member in section.party
        ],
    }


def timestamp_to_dict(timestamp: TimestampEntry) -> dict[str, object]:
    return {"seconds": timestamp.seconds, "label": timestamp.label}
