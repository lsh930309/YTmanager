from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class GameProfile:
    game_key: str
    title_prefixes: tuple[str, ...]
    display_name: str
    default_equipment_type: str
    character_rank_kind: str = "돌"
    max_character_rank: int = 6


GAME_PROFILES: tuple[GameProfile, ...] = (
    GameProfile("zenless_zone_zero", ("젠존제", "ZZZ"), "젠레스 존 제로", "전엔"),
    GameProfile("honkai_starrail", ("스타레일", "붕스", "HSR"), "붕괴: 스타레일", "전광"),
    GameProfile("wuthering_waves", ("명조", "WW"), "명조", "전무"),
    GameProfile("endfield", ("엔드필드", "명일방주 엔드필드"), "명일방주: 엔드필드", "전무", "잠", 5),
)

EQUIPMENT_TYPES = ("전광", "전엔", "전무")
UNKNOWN_RANK_VALUE = -1
BASE_EQUIPMENT_RANK_VALUE = 1
FULL_EQUIPMENT_RANK_VALUE = 5


@dataclass(frozen=True)
class ParsedPartyStatus:
    raw_status: str
    character_rank: str = ""
    character_rank_value: int = UNKNOWN_RANK_VALUE
    equipment_type: str = ""
    equipment_rank: str = ""
    equipment_rank_value: int = UNKNOWN_RANK_VALUE
    warnings: tuple[str, ...] = ()

    @property
    def has_character_rank(self) -> bool:
        return self.character_rank_value >= 0

    @property
    def has_equipment(self) -> bool:
        return bool(self.equipment_type) or self.equipment_rank_value >= 0


def game_profile_from_key(game_key: str | None) -> Optional[GameProfile]:
    if not game_key:
        return None
    normalized = game_key.casefold()
    for profile in GAME_PROFILES:
        if profile.game_key == normalized:
            return profile
    return None


def game_profile_from_prefix(prefix: str | None) -> Optional[GameProfile]:
    if not prefix:
        return None
    normalized = prefix.strip().casefold()
    for profile in GAME_PROFILES:
        if any(normalized == item.casefold() for item in profile.title_prefixes):
            return profile
    return None


def game_key_from_title_prefix(prefix: str | None) -> str:
    profile = game_profile_from_prefix(prefix)
    return profile.game_key if profile else ""


def default_equipment_type(game_key: str | None) -> str:
    profile = game_profile_from_key(game_key)
    return profile.default_equipment_type if profile else ""


def parse_party_status(raw_status: str, game_key: str | None = None) -> ParsedPartyStatus:
    status = (raw_status or "").strip()
    compact = re.sub(r"\s+", "", status)
    warnings: list[str] = []
    if not compact:
        return ParsedPartyStatus(raw_status=status)

    profile = game_profile_from_key(game_key)
    character_rank, character_rank_value = _parse_character_rank(compact, profile)
    equipment_type = _parse_equipment_type(compact) or (default_equipment_type(game_key) if _implies_equipment(compact) else "")
    equipment_rank, equipment_rank_value = _parse_equipment_rank(compact)

    # 전용 장비를 의미하지만 재련 표기가 없으면 1재/기본 전용 장비로 취급한다.
    if equipment_type and equipment_rank_value < 0:
        equipment_rank_value = BASE_EQUIPMENT_RANK_VALUE
        equipment_rank = equipment_type

    # 명전은 캐릭터 명함 + 기본 전용 장비의 강한 축약형이다.
    if compact.startswith("명전"):
        character_rank = "명함"
        character_rank_value = 0
        if not equipment_type:
            equipment_type = default_equipment_type(game_key)
        if equipment_rank_value < 0:
            equipment_rank_value = BASE_EQUIPMENT_RANK_VALUE
            equipment_rank = equipment_type

    # 재련만 보이는 경우도 기본 전용 장비 유형을 추정한다.
    if equipment_rank_value >= 0 and not equipment_type:
        equipment_type = default_equipment_type(game_key)

    if character_rank_value < 0 and equipment_rank_value < 0 and not equipment_type:
        warnings.append("돌파/장비 표기를 인식하지 못했습니다.")

    return ParsedPartyStatus(
        raw_status=status,
        character_rank=character_rank,
        character_rank_value=character_rank_value,
        equipment_type=equipment_type,
        equipment_rank=equipment_rank,
        equipment_rank_value=equipment_rank_value,
        warnings=tuple(warnings),
    )


def format_party_status(parsed: ParsedPartyStatus, game_key: str | None = None) -> str:
    if not parsed.has_character_rank and not parsed.has_equipment:
        return parsed.raw_status

    character = parsed.character_rank
    equipment_type = parsed.equipment_type or default_equipment_type(game_key)
    equipment_rank = parsed.equipment_rank
    equipment_rank_value = parsed.equipment_rank_value

    if not parsed.has_equipment:
        return character

    if parsed.character_rank_value == 0 and equipment_rank_value == BASE_EQUIPMENT_RANK_VALUE:
        return "명전"

    if equipment_rank_value == BASE_EQUIPMENT_RANK_VALUE:
        if character:
            return f"{character}{equipment_type}" if equipment_type else character
        return equipment_type

    rank_label = equipment_rank or _equipment_rank_label(equipment_rank_value)
    if character:
        return f"{character}{rank_label}"
    return rank_label


def extract_video_date(title: str, published_at: str = "") -> str:
    match = re.search(r"-\s*(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\s*$", title or "")
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if published_at:
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return published_at[:10]
    return ""


def _parse_character_rank(compact: str, profile: Optional[GameProfile]) -> tuple[str, int]:
    kind = profile.character_rank_kind if profile else "돌"
    max_rank = profile.max_character_rank if profile else 6

    if "명함" in compact or compact.startswith("명전"):
        return "명함", 0

    if kind == "잠":
        if "풀잠" in compact:
            return "풀잠", max_rank
        match = re.search(r"([1-4])잠", compact)
        if match:
            value = int(match.group(1))
            return f"{value}잠", value
        # 엔드필드라도 과거 데이터가 돌 표기를 쓸 경우를 허용한다.

    if "풀돌" in compact:
        return "풀돌", 6
    match = re.search(r"([0-5])돌", compact)
    if match:
        value = int(match.group(1))
        return ("명함", 0) if value == 0 else (f"{value}돌", value)
    return "", UNKNOWN_RANK_VALUE


def _parse_equipment_type(compact: str) -> str:
    for equipment_type in EQUIPMENT_TYPES:
        if equipment_type in compact:
            return equipment_type
    if "명전" in compact:
        return ""
    return ""


def _parse_equipment_rank(compact: str) -> tuple[str, int]:
    if "풀재" in compact:
        return "풀재", FULL_EQUIPMENT_RANK_VALUE
    match = re.search(r"([2-4])재", compact)
    if match:
        value = int(match.group(1))
        return f"{value}재", value
    return "", UNKNOWN_RANK_VALUE


def _equipment_rank_label(value: int) -> str:
    if value == FULL_EQUIPMENT_RANK_VALUE:
        return "풀재"
    if value > BASE_EQUIPMENT_RANK_VALUE:
        return f"{value}재"
    return ""


def _implies_equipment(compact: str) -> bool:
    return any(token in compact for token in ("명전", "전광", "전엔", "전무", "재"))
