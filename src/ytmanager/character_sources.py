from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable

from ytmanager.character_master import CharacterMasterEntry


@dataclass(frozen=True)
class CharacterSourceDefinition:
    key: str
    game_key: str
    url: str
    source_name: str
    parser: str
    description: str = ""
    fetch_fn: str = "html"  # "html" | "json_embed"


SOURCE_CATALOG: dict[str, CharacterSourceDefinition] = {
    "zzz_gg_ko": CharacterSourceDefinition(
        key="zzz_gg_ko",
        game_key="zenless_zone_zero",
        url="https://zzz.gg/ko/characters/",
        source_name="zzz.gg-ko",
        parser="zzz_gg_cards",
        description="ZZZ.GG 한국어 젠레스 존 제로 캐릭터 목록",
    ),
    "hoyodb_hsr_ko": CharacterSourceDefinition(
        key="hoyodb_hsr_ko",
        game_key="honkai_starrail",
        url="https://hoyodb.wiki/ko/hsr/characters",
        source_name="hoyodb-hsr-ko",
        parser="hoyodb_hsr_cards",
        description="HoYoDB/BitTopup Wiki 한국어 붕괴: 스타레일 캐릭터 목록",
    ),
    "namu_hsr_ko": CharacterSourceDefinition(
        key="namu_hsr_ko",
        game_key="honkai_starrail",
        url="https://namu.wiki/w/%EB%B6%95%EA%B4%B4%3A%20%EC%8A%A4%ED%83%80%EB%A0%88%EC%9D%BC%2F%EC%BA%90%EB%A6%AD%ED%84%B0",
        source_name="namuwiki-hsr-ko",
        parser="namu_hsr_cards",
        description="나무위키 한국어 붕괴: 스타레일 캐릭터 문서",
    ),
    "namu_ww_ko": CharacterSourceDefinition(
        key="namu_ww_ko",
        game_key="wuthering_waves",
        url="https://namu.wiki/w/%EB%AA%85%EC%A1%B0%3A%20%EC%9B%8C%EB%8D%94%EB%A7%81%20%EC%9B%A8%EC%9D%B4%EB%B8%8C%2F%EA%B3%B5%EB%AA%85%EC%9E%90",
        source_name="namuwiki-ww-ko",
        parser="namu_ww_cards",
        description="나무위키 한국어 명조: 워더링 웨이브 공명자 문서",
    ),
    "endfield_wiki_en": CharacterSourceDefinition(
        key="endfield_wiki_en",
        game_key="endfield",
        url="https://arknightsendfield.wiki/characters/",
        source_name="arknightsendfield-wiki-en",
        parser="endfield_wiki_cards",
        description="Arknights: Endfield Wiki 영어 오퍼레이터 목록",
    ),
    "nanoka_hsr_ko": CharacterSourceDefinition(
        key="nanoka_hsr_ko",
        game_key="honkai_starrail",
        url="https://hsr.nanoka.cc/",
        source_name="nanoka-hsr-ko",
        parser="nanoka_hsr_cards",
        description="nanoka.cc 한국어 붕괴: 스타레일 캐릭터 목록",
        fetch_fn="json_embed",
    ),
    "nanoka_ww_ko": CharacterSourceDefinition(
        key="nanoka_ww_ko",
        game_key="wuthering_waves",
        url="https://ww.nanoka.cc/",
        source_name="nanoka-ww-ko",
        parser="nanoka_ww_cards",
        description="nanoka.cc 한국어 명조: 워더링 웨이브 공명자 목록",
        fetch_fn="json_embed",
    ),
    "nanoka_zzz_ko": CharacterSourceDefinition(
        key="nanoka_zzz_ko",
        game_key="zenless_zone_zero",
        url="https://zzz.nanoka.cc/",
        source_name="nanoka-zzz-ko",
        parser="nanoka_zzz_cards",
        description="nanoka.cc 한국어 젠레스 존 제로 캐릭터 목록",
        fetch_fn="json_embed",
    ),
}

ZZZ_ROLES = ("강공", "격파", "이상", "지원", "방어", "명파")
HSR_ATTRIBUTE_MAP = {
    "Physical": "물리",
    "Fire": "화염",
    "Ice": "얼음",
    "Thunder": "번개",
    "Wind": "바람",
    "Quantum": "양자",
    "Imaginary": "허수",
}
HSR_PATH_MAP = {
    "Destruction": "파멸",
    "Hunt": "수렵",
    "Erudition": "지식",
    "Harmony": "화합",
    "Nihility": "공허",
    "Preservation": "보존",
    "Abundance": "풍요",
    "Memory": "기억",
    "Remembrance": "기억",
}
ENDFIELD_ELEMENT_MAP = {
    "Heat": "열",
    "Nature": "자연",
    "Physical": "물리",
    "Cryo": "빙결",
    "Electric": "전기",
}
WW_ELEMENT_MAP = {
    "응결": "응결",
    "용융": "용융",
    "전도": "전도",
    "기류": "기류",
    "회절": "회절",
    "인멸": "인멸",
}
NANOKA_HSR_RANK_MAP = {
    "CombatPowerAvatarRarityType4": "4",
    "CombatPowerAvatarRarityType5": "5",
}
NANOKA_HSR_BASETYPE_MAP = {
    "Knight": "보존",
    "Rogue": "수렵",
    "Mage": "지식",
    "Warlock": "공허",
    "Shaman": "화합",
    "Warrior": "파멸",
    "Priest": "풍요",
    "Memory": "기억",
}
NANOKA_WW_ELEMENT_MAP = {1: "응결", 2: "용융", 3: "전도", 4: "기류", 5: "회절", 6: "인멸"}
NANOKA_WW_WEAPON_MAP  = {1: "도검", 2: "장검", 3: "권총", 4: "권갑", 5: "정류기"}
NANOKA_ZZZ_RANK_MAP    = {3: "A", 4: "S"}
NANOKA_ZZZ_ELEMENT_MAP = {200: "", 201: "화염", 202: "빙속", 203: "전격", 204: "에테르", 205: "물리"}


def fetch_source_html(source: CharacterSourceDefinition, timeout: int = 20) -> str:
    request = urllib.request.Request(source.url, headers={"User-Agent": "Mozilla/5.0 YTmanager/0.1 character-master-builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - known source catalog URL
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _fetch_nanoka_embed(source: CharacterSourceDefinition, timeout: int = 20) -> str:
    page_html = fetch_source_html(source, timeout)
    m = re.search(
        r'<script[^>]+data-url="[^"]*static\.nanoka\.cc/[^"]+/character\.json"[^>]*>(.*?)</script>',
        page_html,
        re.DOTALL,
    )
    if m:
        raw = m.group(1).strip()
        # SvelteKit은 {"status":200,"statusText":"OK","headers":{},"body":"..."} 래퍼로 감쌈
        try:
            wrapper = json.loads(raw)
            if isinstance(wrapper, dict) and "body" in wrapper:
                return wrapper["body"] if isinstance(wrapper["body"], str) else json.dumps(wrapper["body"])
        except (json.JSONDecodeError, TypeError):
            pass
        return raw
    url_m = re.search(r'data-url="(https://static\.nanoka\.cc/[^"]+/character\.json)"', page_html)
    if not url_m:
        raise ValueError(f"nanoka.cc: character.json URL을 찾을 수 없음 ({source.url})")
    req = urllib.request.Request(url_m.group(1), headers={"User-Agent": "Mozilla/5.0 YTmanager/0.1 character-master-builder"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - known source catalog URL
        return resp.read().decode("utf-8")


def collect_source(source_key: str, html_text: str | None = None) -> list[CharacterMasterEntry]:
    source = SOURCE_CATALOG[source_key]
    if html_text is not None:
        text = html_text
    elif source.fetch_fn == "json_embed":
        text = _fetch_nanoka_embed(source)
    else:
        text = fetch_source_html(source)
    return _parser_for(source.parser)(text, source)


def parse_zzz_gg_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    for chunk in re.split(r'<li class="item"', text):
        name_match = re.search(r'<div class="name">([^<]+)</div>', chunk)
        if not name_match:
            href_match = re.search(r'href="/ko/characters/([^"#?]+)"', chunk)
            name = _clean_name(href_match.group(1)) if href_match else ""
        else:
            name = _clean_name(name_match.group(1))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        alt_values = [_clean_name(value) for value in re.findall(r'alt="([^"]+)"', chunk)]
        element = _first((value.removesuffix(" 속성") for value in alt_values if value.endswith(" 속성")))
        role = _first(value for value in alt_values if value in ZZZ_ROLES)
        rarity_match = re.search(r'ItemRarity([A-Z])\.png', chunk)
        rarity = rarity_match.group(1) if rarity_match else ""
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name,
                display_name=name,
                rarity=rarity,
                element=element,
                role_or_path=role,
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def parse_hoyodb_hsr_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    chunks = re.split(r'<a href="/ko/starrail/characters/\d+"', text)
    for chunk in chunks[1:]:
        name_match = re.search(r'alt="([^"]+)" class="absolute inset-0', chunk)
        if not name_match:
            name_match = re.search(r'<p class="[^"]*text-center">([^<]+)</p>', chunk)
        name = _clean_name(name_match.group(1)) if name_match else ""
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        attribute_match = re.search(r'IconAttribute([A-Za-z]+)\.png', chunk)
        profession_match = re.search(r'IconProfession([A-Za-z]+)Small\.png', chunk)
        rarity = str(chunk.count('i-heroicons:star-solid')) or ""
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name,
                display_name=name,
                rarity=rarity if rarity != "0" else "",
                element=HSR_ATTRIBUTE_MAP.get(attribute_match.group(1), attribute_match.group(1) if attribute_match else ""),
                role_or_path=HSR_PATH_MAP.get(profession_match.group(1), profession_match.group(1) if profession_match else ""),
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def parse_endfield_wiki_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    chunks = re.split(r'<a href="/characters/[^"]+" class="character-card"', text)
    for chunk in chunks[1:]:
        name_match = re.search(r'<h3 class="character-name"[^>]*>([^<]+)</h3>', chunk)
        if not name_match:
            name_match = re.search(r'alt="([^"]+)"', chunk)
        name = _clean_name(name_match.group(1)) if name_match else ""
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        rarity_match = re.search(r'data-rarity="(\d+)"', chunk)
        element_match = re.search(r'<span class="element-badge"[^>]*>\s*([^<]+?)\s*</span>', chunk)
        class_match = re.search(r'<span class="class-badge"[^>]*>\s*([^<]+?)\s*</span>', chunk)
        element = _clean_name(element_match.group(1)) if element_match else ""
        role = _clean_name(class_match.group(1)) if class_match else ""
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name,
                canonical_name_en=name,
                display_name=name,
                rarity=rarity_match.group(1) if rarity_match else "",
                element=ENDFIELD_ELEMENT_MAP.get(element, element),
                role_or_path=role,
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def parse_namu_hsr_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    return _parse_namu_cards(text, source, mode="hsr")


def parse_namu_ww_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    return _parse_namu_cards(text, source, mode="ww")


def _parse_namu_cards(text: str, source: CharacterSourceDefinition, mode: str) -> list[CharacterMasterEntry]:
    entries: dict[str, CharacterMasterEntry] = {}
    chunks = re.split(r"<a class='V2nYnWpb' href='/w/[^']+' title='([^']+)'", text)
    # split 결과는 [prefix, title1, rest1, title2, rest2, ...]
    for index in range(1, len(chunks), 2):
        raw_name = _clean_name(chunks[index])
        chunk = chunks[index + 1] if index + 1 < len(chunks) else ""
        if not _is_likely_namu_character_card(raw_name, chunk, mode):
            continue
        name, aliases = _normalize_namu_title(raw_name, source.game_key)
        key = name.casefold()
        if not name:
            continue
        if mode == "hsr":
            element = _extract_namu_alt_suffix(chunk, " 속성")
            role = _extract_namu_alt_suffix(chunk, " 운명의 길")
        else:
            element_raw = _first(re.findall(r"alt='명조 속성-([^']+)'", chunk))
            element = WW_ELEMENT_MAP.get(element_raw, element_raw)
            role = ""
        rarity = str(max((len(match) for match in re.findall(r"✦+", chunk)), default=0)) or ""
        new_entry = CharacterMasterEntry(
            game_key=source.game_key,
            canonical_name_ko=name,
            display_name=name,
            aliases_ko=tuple(aliases),
            rarity=rarity if rarity != "0" else "",
            element=element,
            role_or_path=role,
            source_name=source.source_name,
            source_url=source.url,
        )
        existing = entries.get(key)
        if existing:
            new_entry = _merge_entries(existing, new_entry)
        entries[key] = new_entry
    return list(entries.values())


def _is_likely_namu_character_card(name: str, chunk: str, mode: str) -> bool:
    if not name or len(name) > 30:
        return False
    if mode == "hsr":
        return "운명의 길" in chunk and "✦" in chunk
    if mode == "ww":
        return (f"명조 {name} 아이콘" in chunk or "명조 속성-" in chunk) and ("✦" in chunk or "data-src" in chunk)
    return False


def _extract_namu_alt_suffix(chunk: str, suffix: str) -> str:
    values = [_clean_name(value) for value in re.findall(r"alt='([^']+)'", chunk)]
    for value in values:
        if value.endswith(suffix):
            return value.removesuffix(suffix)
    return ""


def _normalize_namu_title(raw_name: str, game_key: str) -> tuple[str, tuple[str, ...]]:
    aliases: list[str] = []
    name = raw_name.strip()
    if not name:
        return "", ()
    if "/" in name:
        aliases.append(name)
        name = name.split("/", 1)[0]
    suffixes = {
        "honkai_starrail": "(붕괴: 스타레일)",
        "wuthering_waves": "(명조: 워더링 웨이브)",
    }
    suffix = suffixes.get(game_key)
    if suffix and suffix in name:
        aliases.append(name)
        name = name.replace(suffix, "")
    name = name.strip()
    aliases = [alias for alias in aliases if alias and alias != name]
    return name, tuple(dict.fromkeys(aliases))


def _merge_entries(existing: CharacterMasterEntry, incoming: CharacterMasterEntry) -> CharacterMasterEntry:
    aliases = tuple(dict.fromkeys([*existing.aliases_ko, *incoming.aliases_ko]))
    return CharacterMasterEntry(
        game_key=existing.game_key,
        canonical_name_ko=existing.canonical_name_ko,
        canonical_name_en=existing.canonical_name_en or incoming.canonical_name_en,
        display_name=existing.display_name or incoming.display_name,
        aliases_ko=aliases,
        rarity=existing.rarity or incoming.rarity,
        element=existing.element or incoming.element,
        role_or_path=existing.role_or_path or incoming.role_or_path,
        source_name=existing.source_name,
        source_url=existing.source_url,
        extra={**dict(incoming.extra), **dict(existing.extra)},
    )


def parse_nanoka_hsr_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    data: dict = json.loads(text)
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    for item in data.values():
        name_ko = _clean_name(item.get("ko", ""))
        if not name_ko or name_ko.casefold() in seen:
            continue
        seen.add(name_ko.casefold())
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name_ko,
                canonical_name_en=_clean_name(item.get("en", "")),
                display_name=name_ko,
                rarity=NANOKA_HSR_RANK_MAP.get(item.get("rank", ""), ""),
                element=HSR_ATTRIBUTE_MAP.get(item.get("damageType", ""), item.get("damageType", "")),
                role_or_path=NANOKA_HSR_BASETYPE_MAP.get(item.get("baseType", ""), item.get("baseType", "")),
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def parse_nanoka_ww_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    data: dict = json.loads(text)
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    for item in data.values():
        name_ko = _clean_name(item.get("ko", ""))
        if not name_ko or name_ko.casefold() in seen:
            continue
        seen.add(name_ko.casefold())
        element_int = item.get("element")
        weapon_int = item.get("weapon")
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name_ko,
                canonical_name_en=_clean_name(item.get("en", "")),
                display_name=name_ko,
                rarity=str(item.get("rank", "")),
                element=NANOKA_WW_ELEMENT_MAP.get(element_int, "") if element_int is not None else "",
                role_or_path=NANOKA_WW_WEAPON_MAP.get(weapon_int, "") if weapon_int is not None else "",
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def parse_nanoka_zzz_cards(text: str, source: CharacterSourceDefinition) -> list[CharacterMasterEntry]:
    data: dict = json.loads(text)
    entries: list[CharacterMasterEntry] = []
    seen: set[str] = set()
    for item in data.values():
        name_ko = _clean_name(item.get("ko", ""))
        if not name_ko or name_ko.casefold() in seen:
            continue
        seen.add(name_ko.casefold())
        element_int = item.get("element")
        entries.append(
            CharacterMasterEntry(
                game_key=source.game_key,
                canonical_name_ko=name_ko,
                canonical_name_en=_clean_name(item.get("en", "")),
                display_name=name_ko,
                rarity=NANOKA_ZZZ_RANK_MAP.get(item.get("rank"), "") if item.get("rank") is not None else "",
                element=NANOKA_ZZZ_ELEMENT_MAP.get(element_int, "") if element_int is not None else "",
                role_or_path="",
                source_name=source.source_name,
                source_url=source.url,
            )
        )
    return entries


def _parser_for(name: str) -> Callable[[str, CharacterSourceDefinition], list[CharacterMasterEntry]]:
    parsers = {
        "zzz_gg_cards": parse_zzz_gg_cards,
        "hoyodb_hsr_cards": parse_hoyodb_hsr_cards,
        "namu_hsr_cards": parse_namu_hsr_cards,
        "namu_ww_cards": parse_namu_ww_cards,
        "endfield_wiki_cards": parse_endfield_wiki_cards,
        "nanoka_hsr_cards": parse_nanoka_hsr_cards,
        "nanoka_ww_cards": parse_nanoka_ww_cards,
        "nanoka_zzz_cards": parse_nanoka_zzz_cards,
    }
    try:
        return parsers[name]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 캐릭터 소스 파서입니다: {name}") from exc


def _clean_name(value: str) -> str:
    return html.unescape(value).replace("\xa0", " ").strip()


def _first(values) -> str:
    for value in values:
        if value:
            return value
    return ""
