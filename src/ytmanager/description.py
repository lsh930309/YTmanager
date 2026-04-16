from __future__ import annotations

import re
from pathlib import Path
from string import Formatter
from typing import Iterable, Mapping, Sequence

from ytmanager.models import TimestampEntry
from ytmanager.rules import unique_tags
from ytmanager.timestamps import render_timestamps

DEFAULT_TEMPLATE = """[{game_version} {game_content_name} {game_content_season_in_current_version}]
{top_tags}

{timestamps}

{notes}
"""

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def load_template(path: Path | None = None) -> str:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.append(Path.cwd() / "DESCRIPTION_TEMPLATE.md")
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return DEFAULT_TEMPLATE


def extract_placeholders(template_text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for _, name, _, _ in Formatter().parse(template_text):
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def render_description(
    template_text: str,
    fields: Mapping[str, object] | None = None,
    top_tags: Iterable[str] = (),
    timestamps: Sequence[TimestampEntry] = (),
) -> str:
    context = SafeDict()
    if fields:
        context.update({key: "" if value is None else str(value) for key, value in fields.items()})
    context.setdefault("top_tags", " ".join(unique_tags(top_tags)))
    context.setdefault("timestamps", render_timestamps(timestamps))
    rendered = template_text.format_map(context)
    return trim_excess_blank_lines(rendered).strip()


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
