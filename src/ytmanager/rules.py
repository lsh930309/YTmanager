from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from ytmanager.models import RuleMapping
from ytmanager.paths import user_data_dir

PREFIX_RE = re.compile(r"^\s*\[([^\]]+)\]")
HASHTAG_RE = re.compile(r"(?<!\w)#[\w가-힣_]+", re.UNICODE)

DEFAULT_RULES: tuple[RuleMapping, ...] = (
    RuleMapping("젠존제", ("#zenlesszonezero",), "젠레스 존 제로"),
)


def extract_title_prefix(title: str) -> Optional[str]:
    match = PREFIX_RE.match(title or "")
    if not match:
        return None
    return match.group(1).strip()


def find_rule_for_title(title: str, rules: Iterable[RuleMapping] = DEFAULT_RULES) -> Optional[RuleMapping]:
    prefix = extract_title_prefix(title)
    if not prefix:
        return None
    for rule in rules:
        if rule.title_prefix == prefix:
            return rule
    return None


def normalize_hashtag(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return ""
    return tag if tag.startswith("#") else f"#{tag}"


def unique_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        normalized = normalize_hashtag(tag)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def top_tags_for_title(title: str, rules: Iterable[RuleMapping] = DEFAULT_RULES) -> list[str]:
    rule = find_rule_for_title(title, rules)
    if not rule:
        return []
    return unique_tags(rule.description_tags)


def merge_top_tags(description: str, top_tags: Iterable[str]) -> str:
    tags = unique_tags(top_tags)
    if not tags:
        return description
    body = (description or "").lstrip("\ufeff")
    first_line = body.split("\n", 1)[0] if body else ""
    existing = set(tag.casefold() for tag in HASHTAG_RE.findall(first_line))
    missing = [tag for tag in tags if tag.casefold() not in existing]
    if not missing:
        return description
    tag_line = " ".join(missing)
    if not body.strip():
        return tag_line
    return f"{tag_line}\n{body}"


def default_rules_path() -> Path:
    return user_data_dir() / "rules.json"


def load_rule_mappings(path: Path | None = None) -> list[RuleMapping]:
    """사용자 규칙 파일을 읽고, 없으면 기본 규칙을 반환한다."""
    rule_path = path or default_rules_path()
    if not rule_path.exists():
        return list(DEFAULT_RULES)
    raw = json.loads(rule_path.read_text(encoding="utf-8"))
    rules: list[RuleMapping] = []
    for item in raw:
        prefix = str(item.get("title_prefix", "")).strip()
        tags = tuple(unique_tags(item.get("description_tags", []) or []))
        if not prefix or not tags:
            continue
        rules.append(RuleMapping(prefix, tags, str(item.get("display_name", ""))))
    return rules or list(DEFAULT_RULES)


def save_rule_mappings(rules: Iterable[RuleMapping], path: Path | None = None) -> Path:
    """GUI 설정 화면이 붙기 전에도 편집 가능한 JSON 규칙 파일을 저장한다."""
    rule_path = path or default_rules_path()
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "title_prefix": rule.title_prefix,
            "description_tags": list(rule.description_tags),
            "display_name": rule.display_name,
        }
        for rule in rules
    ]
    rule_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return rule_path
