from __future__ import annotations

from typing import Iterable

from ytmanager.models import TimestampEntry


def format_timestamp(seconds: float) -> str:
    """YouTube 설명에 넣기 좋은 MM:SS 또는 HH:MM:SS 문자열로 변환한다."""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_timestamp(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError("타임스탬프는 MM:SS 또는 HH:MM:SS 형식이어야 합니다.")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("타임스탬프에는 숫자만 사용할 수 있습니다.") from exc
    if any(number < 0 for number in numbers):
        raise ValueError("타임스탬프 값은 음수가 될 수 없습니다.")
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        raise ValueError("분과 초는 60보다 작아야 합니다.")
    return hours * 3600 + minutes * 60 + seconds


def render_timestamps(entries: Iterable[TimestampEntry]) -> str:
    lines: list[str] = []
    for entry in sorted(entries, key=lambda item: item.seconds):
        stamp = format_timestamp(entry.seconds)
        label = entry.label.strip()
        lines.append(f"{stamp} - {label}" if label else stamp)
    return "\n".join(lines)
