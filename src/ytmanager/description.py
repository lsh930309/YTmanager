from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ytmanager.models import TimestampEntry
from ytmanager.rules import unique_tags
from ytmanager.timestamps import parse_timestamp, render_timestamps

DEFAULT_TEMPLATE = """{[tags]}
[{game_version} {game_content_name} {game_content_season_in_current_version}]

//Section Start//
**{optional: stage_number} {boss_name} - {party_composition}**
- {party[i].character}: {party[i].character.M_level}{optional: party[i].character.equip}
//Section End//

-------------------

{[timestamps]}
"""

SECTION_START = "//Section Start//"
SECTION_END = "//Section End//"
SPECIAL_TAGS_TOKEN = "{[tags]}"
SPECIAL_TIMESTAMPS_TOKEN = "{[timestamps]}"
SPECIAL_TIMESTAMP_TOKEN = "{[timestamp]}"
SPECIAL_TAGS_NAME = "[tags]"
SPECIAL_TIMESTAMPS_NAME = "[timestamps]"
SPECIAL_TIMESTAMP_NAME = "[timestamp]"
TEMPLATE_MARKER_RE = re.compile(r"^//Template:\s*(?P<name>[a-zA-Z0-9_-]+)\s*//\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
OPTIONAL_RE = re.compile(r"^optional:\s*(.+)$")
INDEXED_RE = re.compile(r"^(?P<list>[a-zA-Z_][a-zA-Z0-9_]*)\[i\]\.(?P<field>.+)$")
SPECIAL_OPT_TIMESTAMPS_TOKEN = "{optional: [timestamps]}"


@dataclass(frozen=True)
class PartyMember:
    character: str = ""
    m_level: str = ""
    equip: str = ""


@dataclass(frozen=True)
class DescriptionSection:
    stage_number: str = ""
    boss_name: str = ""
    party_composition: str = ""
    party: tuple[PartyMember, ...] = ()


@dataclass(frozen=True)
class DescriptionData:
    fields: Mapping[str, str] = field(default_factory=dict)
    sections: tuple[DescriptionSection, ...] = ()
    timestamps: tuple[TimestampEntry, ...] = ()
    top_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDescription:
    top_tags: tuple[str, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)
    sections: tuple[DescriptionSection, ...] = ()
    timestamps: tuple[TimestampEntry, ...] = ()
    unmatched_lines: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    confidence: str = "low"


def load_template(path: Path | None = None) -> str:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.append(Path.cwd() / "DESCRIPTION_TEMPLATE.md")
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return DEFAULT_TEMPLATE


def load_template_library(template_text: str) -> dict[str, str]:
    """DESCRIPTION_TEMPLATE.md의 다중 템플릿 블록을 읽는다.

    `//Template: combat//` 같은 마커가 없으면 전체 문서를 combat 템플릿으로
    취급해 기존 단일 템플릿 파일과 호환한다.
    """
    matches = list(TEMPLATE_MARKER_RE.finditer(template_text))
    if not matches:
        return {"combat": template_text}

    templates: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group("name").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(template_text)
        body = template_text[start:end].strip("\n")
        body = re.sub(r"^#{10,}\s*$", "", body, flags=re.MULTILINE)
        body = re.sub(r"^optional:\s*(-{5,})\s*$", r"\1", body, flags=re.MULTILINE)
        if name and body.strip():
            templates[name] = body
    return templates or {"combat": template_text}


def select_template(template_text: str, name: str, fallback: str = "combat") -> str:
    library = load_template_library(template_text)
    if name in library:
        return library[name]
    if fallback in library:
        return library[fallback]
    return next(iter(library.values()))


def split_template_sections(template_text: str) -> tuple[str, str, str]:
    start = template_text.find(SECTION_START)
    end = template_text.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        return template_text, "", ""
    prefix = template_text[:start]
    section = template_text[start + len(SECTION_START):end].strip("\n")
    suffix = template_text[end + len(SECTION_END):]
    return prefix, section, suffix


def extract_placeholders(template_text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in PLACEHOLDER_RE.finditer("\n".join(load_template_library(template_text).values())):
        name = match.group(1).strip()
        optional = OPTIONAL_RE.match(name)
        if optional:
            name = optional.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def parse_key_value_lines(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def parse_party_members(text: str) -> tuple[PartyMember, ...]:
    members: list[PartyMember] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        parts += [""] * (3 - len(parts))
        members.append(PartyMember(character=parts[0], m_level=parts[1], equip=parts[2]))
    return tuple(members)


def parse_sections_text(text: str) -> tuple[DescriptionSection, ...]:
    blocks = re.split(r"\n\s*---\s*\n", text.strip()) if text.strip() else []
    sections: list[DescriptionSection] = []
    for block in blocks:
        fields: dict[str, str] = {}
        party_lines: list[str] = []
        in_party = False
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.casefold() == "party:":
                in_party = True
                continue
            if in_party:
                party_lines.append(line)
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key.strip()] = value.strip()
        if fields or party_lines:
            sections.append(
                DescriptionSection(
                    stage_number=fields.get("stage_number", ""),
                    boss_name=fields.get("boss_name", ""),
                    party_composition=fields.get("party_composition", ""),
                    party=parse_party_members("\n".join(party_lines)),
                )
            )
    return tuple(sections)


def parse_description(template_text: str, description: str) -> ParsedDescription:
    """현재 DESCRIPTION_TEMPLATE.md 규칙에 맞춰 기존 YouTube 설명을 역파싱한다.

    템플릿 문법 전체를 일반화한 파서라기보다는, 현재 프로젝트의 설명 구조
    `{[tags]}` → `[버전 콘텐츠 시즌]` → 반복 섹션 → 구분선 → `{[timestamps]}`
    흐름을 안정적으로 분석하는 도메인 파서다.
    """
    del template_text  # 현재 템플릿 마커 존재 여부보다 실제 설명 형태를 우선 분석한다.
    raw_lines = [line.rstrip() for line in description.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in raw_lines if line.strip()]

    top_tags: list[str] = []
    unmatched: list[str] = []
    warnings: list[str] = []
    fields: dict[str, str] = {}

    header_index = _find_header_line(lines)
    if header_index is None:
        warnings.append("대괄호 헤더를 찾지 못했습니다.")
        header_index = -1
    else:
        top_tags = _extract_tags_from_lines(lines[: min(len(lines), header_index + 4)])
        fields.update(_parse_header_line(lines[header_index]))

    divider_index = _find_divider_line(lines, start=max(header_index + 1, 0))
    section_start = max(header_index + 1, 0)
    if divider_index is None:
        body_lines = lines[section_start:]
        timestamp_lines = [line for line in body_lines if _is_timestamp_like_line(line)]
        section_lines = [line for line in body_lines if not _is_timestamp_like_line(line)]
    else:
        section_lines = lines[section_start:divider_index]
        timestamp_lines = lines[divider_index + 1:]

    sections, section_unmatched = _parse_rendered_sections(section_lines)
    unmatched.extend(section_unmatched)

    timestamps, timestamp_unmatched = _parse_rendered_timestamps(timestamp_lines)
    unmatched.extend(timestamp_unmatched)

    if not top_tags:
        warnings.append("상단 해시태그를 찾지 못했습니다.")
    if not fields:
        warnings.append("헤더 필드를 파싱하지 못했습니다.")
    if divider_index is None and timestamp_lines:
        warnings.append("타임스탬프 구분선을 찾지 못했습니다.")

    confidence = _parse_confidence(fields, sections, timestamps, unmatched, warnings)
    return ParsedDescription(
        top_tags=tuple(top_tags),
        fields=fields,
        sections=sections,
        timestamps=timestamps,
        unmatched_lines=tuple(unmatched),
        warnings=tuple(warnings),
        confidence=confidence,
    )


def _find_header_line(lines: Sequence[str]) -> int | None:
    for index, line in enumerate(lines):
        if re.match(r"^\[[^\]]+\]$", line.strip()):
            return index
    return None


def _extract_tags_from_lines(lines: Sequence[str]) -> list[str]:
    tags: list[str] = []
    for line in lines:
        tags.extend(re.findall(r"(?<!\w)#[\w가-힣_]+", line, flags=re.UNICODE))
    return unique_tags(tags)


def _parse_header_line(line: str) -> dict[str, str]:
    content = line.strip()[1:-1].strip()
    tokens = content.split()
    if not tokens:
        return {}
    if len(tokens) == 1:
        return {"game_version": tokens[0]}
    if len(tokens) == 2:
        return {"game_version": tokens[0], "game_content_name": tokens[1]}
    return {
        "game_version": tokens[0],
        "game_content_name": " ".join(tokens[1:-1]),
        "game_content_season_in_current_version": tokens[-1],
    }


def _find_divider_line(lines: Sequence[str], start: int = 0) -> int | None:
    for index in range(start, len(lines)):
        if re.match(r"^-{5,}$", lines[index].strip()):
            return index
    return None


def _contains_timestamp_like_line(lines: Sequence[str]) -> bool:
    return any(_is_timestamp_like_line(line) for line in lines)


def _is_timestamp_like_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}", line))


def _parse_rendered_sections(lines: Sequence[str]) -> tuple[tuple[DescriptionSection, ...], list[str]]:
    sections: list[DescriptionSection] = []
    unmatched: list[str] = []
    current_fields: dict[str, str] | None = None
    current_party: list[PartyMember] = []

    def flush() -> None:
        nonlocal current_fields, current_party
        if current_fields is not None:
            sections.append(
                DescriptionSection(
                    stage_number=current_fields.get("stage_number", ""),
                    boss_name=current_fields.get("boss_name", ""),
                    party_composition=current_fields.get("party_composition", ""),
                    party=tuple(current_party),
                )
            )
        current_fields = None
        current_party = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_hashtag_only_line(stripped):
            continue
        headline = re.match(r"^\*{1,2}(?P<headline>.+?)\*{1,2}$", stripped)
        if headline:
            flush()
            current_fields = _parse_section_headline(headline.group("headline"))
            continue
        party_member = _parse_rendered_party_line(stripped)
        if party_member:
            if current_fields is None:
                current_fields = {}
            current_party.append(party_member)
            continue
        unmatched.append(stripped)

    flush()
    return tuple(sections), unmatched


def _parse_section_headline(headline: str) -> dict[str, str]:
    left, separator, party_composition = headline.partition(" - ")
    if not separator and ":" in left:
        stage_candidate, _, boss_candidate = left.partition(":")
        if _looks_like_stage_token(stage_candidate.strip()):
            return {
                "stage_number": stage_candidate.strip(),
                "boss_name": boss_candidate.strip(),
                "party_composition": "",
            }
    tokens = left.strip().split()
    stage_number = ""
    boss_name = left.strip()
    if tokens and _looks_like_stage_token(tokens[0]):
        stage_number = tokens[0]
        boss_name = " ".join(tokens[1:]).strip()
    return {
        "stage_number": stage_number,
        "boss_name": boss_name,
        "party_composition": party_composition.strip() if separator else "",
    }


def _looks_like_stage_token(token: str) -> bool:
    return bool(
        re.match(r"^\d+(?:차|단계|페이즈|층)?$", token)
        or re.match(r"^\d+[~-]\d+층$", token)
        or re.match(r"^\d+-\d+$", token)
        or re.match(r"^(?:전초전|최종전|전반|후반)(?:\s*\d+)?$", token)
    )


def _parse_rendered_party_line(line: str) -> PartyMember | None:
    match = re.match(r"^-\s*(?P<character>[^:]+):\s*(?P<rest>.*)$", line)
    if not match:
        match = re.match(r"^-\s*(?P<character>\S+)\s*(?P<rest>.*)$", line)
    if not match:
        return None
    character = match.group("character").strip()
    rest = match.group("rest").strip()
    if not character:
        return None
    tokens = rest.split(maxsplit=1)
    m_level = tokens[0] if tokens else ""
    equip = tokens[1] if len(tokens) > 1 else ""
    return PartyMember(character=character, m_level=m_level, equip=equip)


def _is_hashtag_only_line(line: str) -> bool:
    tokens = line.split()
    return bool(tokens) and all(token.startswith("#") for token in tokens)


def _parse_rendered_timestamps(lines: Sequence[str]) -> tuple[tuple[TimestampEntry, ...], list[str]]:
    timestamps: list[TimestampEntry] = []
    unmatched: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?P<stamp>(?:\d{1,2}:)?\d{1,2}:\d{2})(?:\s*[-–—]\s*|\s+)?(?P<label>.*)$", stripped)
        if not match:
            unmatched.append(stripped)
            continue
        try:
            seconds = parse_timestamp(match.group("stamp"))
        except ValueError:
            unmatched.append(stripped)
            continue
        timestamps.append(TimestampEntry(seconds=seconds, label=match.group("label").strip()))
    return tuple(timestamps), unmatched


def _parse_confidence(
    fields: Mapping[str, str],
    sections: Sequence[DescriptionSection],
    timestamps: Sequence[TimestampEntry],
    unmatched: Sequence[str],
    warnings: Sequence[str],
) -> str:
    score = 0
    if fields.get("game_version") and fields.get("game_content_name"):
        score += 2
    if fields.get("game_content_season_in_current_version"):
        score += 1
    if sections:
        score += 2
    if timestamps:
        score += 1
    if unmatched:
        score -= 1
    severe_warnings = [warning for warning in warnings if "타임스탬프 구분선" not in warning]
    if severe_warnings:
        score -= 1
    if score >= 5:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def render_description(
    template_text: str,
    fields: Mapping[str, object] | None = None,
    top_tags: Iterable[str] = (),
    timestamps: Sequence[TimestampEntry] = (),
    sections: Sequence[DescriptionSection] = (),
) -> str:
    data = DescriptionData(
        fields={key: "" if value is None else str(value) for key, value in (fields or {}).items()},
        sections=tuple(sections),
        timestamps=tuple(timestamps),
        top_tags=tuple(unique_tags(top_tags)),
    )
    return render_structured_description(template_text, data)


def render_description_template(
    template_text: str,
    template_name: str,
    fields: Mapping[str, object] | None = None,
    top_tags: Iterable[str] = (),
    timestamps: Sequence[TimestampEntry] = (),
    sections: Sequence[DescriptionSection] = (),
) -> str:
    return render_description(select_template(template_text, template_name), fields, top_tags, timestamps, sections)


def render_structured_description(template_text: str, data: DescriptionData) -> str:
    prefix, section_template, suffix = split_template_sections(template_text)
    rendered_prefix = _render_non_section(prefix, data)
    rendered_sections = _render_sections(section_template, data.sections) if section_template else ""
    has_ts_token = SPECIAL_TIMESTAMPS_TOKEN in suffix or SPECIAL_OPT_TIMESTAMPS_TOKEN in suffix
    rendered_suffix = "" if has_ts_token and not data.timestamps else _render_non_section(suffix, data)
    return trim_excess_blank_lines("\n".join(part for part in (rendered_prefix, rendered_sections, rendered_suffix) if part.strip())).strip()


def _render_non_section(template: str, data: DescriptionData) -> str:
    has_ts = SPECIAL_TIMESTAMPS_TOKEN in template or SPECIAL_TIMESTAMP_TOKEN in template or SPECIAL_OPT_TIMESTAMPS_TOKEN in template
    if not data.timestamps and has_ts:
        template = _remove_empty_timestamp_block(template)
    text = template.replace(SPECIAL_TAGS_TOKEN, " ".join(data.top_tags))
    text = text.replace(SPECIAL_TIMESTAMPS_TOKEN, render_timestamps(data.timestamps))
    text = text.replace(SPECIAL_TIMESTAMP_TOKEN, render_timestamps(data.timestamps))
    text = text.replace(SPECIAL_OPT_TIMESTAMPS_TOKEN, render_timestamps(data.timestamps))
    # 이전 기본 템플릿과의 호환성 유지
    text = text.replace("{top_tags}", " ".join(data.top_tags))
    text = text.replace("{timestamps}", render_timestamps(data.timestamps))
    return _render_placeholders(text, data.fields)


def _remove_empty_timestamp_block(template: str) -> str:
    lines = template.splitlines()
    token_index = next(
        (
            index
            for index, line in enumerate(lines)
            if SPECIAL_TIMESTAMPS_TOKEN in line or SPECIAL_TIMESTAMP_TOKEN in line or SPECIAL_OPT_TIMESTAMPS_TOKEN in line
        ),
        None,
    )
    if token_index is None:
        return template
    start = token_index
    cursor = token_index - 1
    while cursor >= 0 and (not lines[cursor].strip() or re.match(r"^-{5,}$", lines[cursor].strip())):
        start = cursor
        cursor -= 1
    del lines[start : token_index + 1]
    return "\n".join(lines)


def _render_sections(section_template: str, sections: Sequence[DescriptionSection]) -> str:
    rendered: list[str] = []
    for section in sections:
        section_fields = {
            "stage_number": section.stage_number,
            "boss_name": section.boss_name,
            "party_composition": section.party_composition,
        }
        rendered_section = _render_section(section_template, section_fields, section.party)
        if rendered_section.strip():
            rendered.append(rendered_section)
    return "\n\n".join(rendered)


def _render_section(template: str, section_fields: Mapping[str, str], party: Sequence[PartyMember]) -> str:
    output_lines: list[str] = []
    for line in template.splitlines():
        if "[i]" in line:
            for member in party:
                rendered = _render_placeholders(line, section_fields, member)
                if rendered.strip():
                    output_lines.append(rendered)
            continue
        rendered = _render_placeholders(line, section_fields)
        if rendered.strip():
            output_lines.append(rendered)
    return "\n".join(output_lines)


def _render_placeholders(text: str, fields: Mapping[str, str], member: PartyMember | None = None) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        optional = OPTIONAL_RE.match(expression)
        is_optional = optional is not None
        if optional:
            expression = optional.group(1).strip()
        value = _lookup_value(expression, fields, member)
        if is_optional and not value:
            return ""
        return value

    rendered = PLACEHOLDER_RE.sub(replace, text)
    return _normalize_rendered_line(rendered)


def _lookup_value(expression: str, fields: Mapping[str, str], member: PartyMember | None) -> str:
    if expression in {SPECIAL_TAGS_NAME, SPECIAL_TIMESTAMPS_NAME, SPECIAL_TIMESTAMP_NAME}:
        return ""
    indexed = INDEXED_RE.match(expression)
    if indexed and indexed.group("list") == "party" and member is not None:
        return _lookup_party_member_value(indexed.group("field"), member)
    return str(fields.get(expression, ""))


def _lookup_party_member_value(field_name: str, member: PartyMember) -> str:
    normalized = field_name.strip()
    mapping = {
        "character": member.character,
        "character.M_level": member.m_level,
        "character.equip": f" {member.equip}" if member.equip else "",
        "equip": f" {member.equip}" if member.equip else "",
        "M_level": member.m_level,
    }
    return mapping.get(normalized, "")


def _normalize_rendered_line(line: str) -> str:
    line = re.sub(r"[ \t]+", " ", line).strip()
    line = re.sub(r"\s+([,.:;])", r"\1", line)
    line = re.sub(r"\s+-\s*$", "", line)
    # bold **...** 마커 정규화
    line = re.sub(r"\s+-\s*\*\*$", "**", line)
    line = re.sub(r"\*\*\s+", "**", line)
    line = re.sub(r"\s+\*\*", "**", line)
    # italic *...* 마커 정규화 (optional stage_number 비어있을 때 발생하는 공백 처리)
    line = re.sub(r"^\*\s+", "*", line)
    line = re.sub(r"\s+-\s*\*$", "*", line)
    line = re.sub(r"\s+\*$", "*", line)
    return line


def parse_gacha_fields(description: str) -> dict[str, str]:
    """gacha 설명에서 전용 스택 필드를 역파싱한다.

    신형(새 템플릿 렌더 결과)과 구형(섹션 기반 렌더 결과) 두 형식을 모두 처리한다.
    - 신형: "- 캐릭터 스택: 반천 0" / "- 엔진 스택: 반천 0"
    - 구형: "- 캐릭터 반천 0스택" / "- 엔진 반천 0스택"
    """
    fields: dict[str, str] = {}
    for raw_line in description.splitlines():
        line = raw_line.strip()
        # 신형 캐릭터: "- 캐릭터 스택: <is_guaranteed> <stack>"
        m = re.match(r"^-\s*캐릭터\s+스택:\s*(\S+)\s+(\S+)", line)
        if m:
            fields["character_is_guaranteed"] = m.group(1)
            fields["character_stack"] = m.group(2)
            continue
        # 구형 캐릭터: "- 캐릭터 <is_guaranteed> <N>스택"
        m = re.match(r"^-\s*캐릭터\s+(\S+)\s+(\d+)스택", line)
        if m:
            fields["character_is_guaranteed"] = m.group(1)
            fields["character_stack"] = m.group(2)
            continue
        # 신형 장비: "- <equipment_type> 스택: <is_guaranteed> <stack>"
        m = re.match(r"^-\s*(\S+)\s+스택:\s*(\S+)\s+(\S+)", line)
        if m and m.group(1) != "캐릭터":
            fields["equipment_type"] = m.group(1)
            fields["equipment_is_guaranteed"] = m.group(2)
            fields["equipment_stack"] = m.group(3)
            continue
        # 구형 장비: "- <equipment_type> <is_guaranteed> <N>스택"
        m = re.match(r"^-\s*(\S+)\s+(\S+)\s+(\d+)스택", line)
        if m and m.group(1) != "캐릭터":
            fields["equipment_type"] = m.group(1)
            fields["equipment_is_guaranteed"] = m.group(2)
            fields["equipment_stack"] = m.group(3)
    return fields


def trim_excess_blank_lines(text: str, max_blank_lines: int = 2) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            blank_count = 0
            output.append(line.rstrip())
        else:
            blank_count += 1
            if blank_count <= max_blank_lines:
                output.append("")
    return "\n".join(output)
