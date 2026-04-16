from __future__ import annotations

import html
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


def fetch_source_html(source: CharacterSourceDefinition, timeout: int = 20) -> str:
    request = urllib.request.Request(source.url, headers={"User-Agent": "Mozilla/5.0 YTmanager/0.1 character-master-builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - known source catalog URL
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def collect_source(source_key: str, html_text: str | None = None) -> list[CharacterMasterEntry]:
    source = SOURCE_CATALOG[source_key]
    text = html_text if html_text is not None else fetch_source_html(source)
    parser = _parser_for(source.parser)
    return parser(text, source)


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


def _parser_for(name: str) -> Callable[[str, CharacterSourceDefinition], list[CharacterMasterEntry]]:
    parsers = {
        "zzz_gg_cards": parse_zzz_gg_cards,
        "hoyodb_hsr_cards": parse_hoyodb_hsr_cards,
        "namu_hsr_cards": parse_namu_hsr_cards,
        "namu_ww_cards": parse_namu_ww_cards,
        "endfield_wiki_cards": parse_endfield_wiki_cards,
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
