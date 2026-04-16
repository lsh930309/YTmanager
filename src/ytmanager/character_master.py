from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CharacterMasterEntry:
    game_key: str
    canonical_name_ko: str
    canonical_name_en: str = ""
    display_name: str = ""
    aliases_ko: tuple[str, ...] = ()
    rarity: str = ""
    element: str = ""
    role_or_path: str = ""
    source_name: str = "manual"
    source_url: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def aliases_for_resolution(self) -> tuple[str, ...]:
        values = [self.canonical_name_ko, self.display_name, *self.aliases_ko]
        if self.canonical_name_en:
            values.append(self.canonical_name_en)
        return tuple(_unique_non_empty(values))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CharacterMasterEntry":
        aliases = raw.get("aliases_ko") or raw.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        extra = raw.get("extra") or {}
        if not isinstance(extra, Mapping):
            extra = {"value": extra}
        return cls(
            game_key=str(raw.get("game_key", "")).strip(),
            canonical_name_ko=str(raw.get("canonical_name_ko") or raw.get("name_ko") or raw.get("canonical_name") or "").strip(),
            canonical_name_en=str(raw.get("canonical_name_en") or raw.get("name_en") or "").strip(),
            display_name=str(raw.get("display_name") or raw.get("canonical_name_ko") or raw.get("name_ko") or raw.get("canonical_name") or "").strip(),
            aliases_ko=tuple(_unique_non_empty(str(alias).strip() for alias in aliases)),
            rarity=str(raw.get("rarity", "")).strip(),
            element=str(raw.get("element", "")).strip(),
            role_or_path=str(raw.get("role_or_path") or raw.get("role") or raw.get("path") or "").strip(),
            source_name=str(raw.get("source_name") or raw.get("source") or "manual").strip(),
            source_url=str(raw.get("source_url", "")).strip(),
            extra=dict(extra),
        )

    def validate(self) -> None:
        if not self.game_key:
            raise ValueError("game_key가 필요합니다.")
        if not self.canonical_name_ko:
            raise ValueError("canonical_name_ko가 필요합니다.")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "game_key": self.game_key,
            "canonical_name_ko": self.canonical_name_ko,
            "canonical_name_en": self.canonical_name_en,
            "display_name": self.display_name or self.canonical_name_ko,
            "aliases_ko": list(self.aliases_ko),
            "rarity": self.rarity,
            "element": self.element,
            "role_or_path": self.role_or_path,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "extra": dict(self.extra),
        }


def load_character_master_entries(path: Path) -> list[CharacterMasterEntry]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "characters" in raw:
        items = raw["characters"]
    elif isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = _entries_from_game_mapping(raw)
    else:
        raise ValueError("지원하지 않는 character master JSON 형식입니다.")
    entries = [CharacterMasterEntry.from_mapping(item) for item in items]
    for entry in entries:
        entry.validate()
    return entries


def dump_character_master_entries(entries: Iterable[CharacterMasterEntry], path: Path) -> None:
    payload = {"version": 1, "characters": [entry.to_json_dict() for entry in entries]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _entries_from_game_mapping(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    for game_key, game_payload in raw.items():
        if game_key == "version":
            continue
        if isinstance(game_payload, Mapping) and "characters" in game_payload:
            for item in game_payload["characters"]:
                merged = dict(item)
                merged.setdefault("game_key", game_key)
                entries.append(merged)
        elif isinstance(game_payload, Mapping):
            for canonical_name, aliases in game_payload.items():
                entries.append({"game_key": game_key, "canonical_name_ko": canonical_name, "aliases_ko": aliases})
    return entries


def _unique_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
