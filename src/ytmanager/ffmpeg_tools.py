from __future__ import annotations

import json
import locale
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from hashlib import sha1
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ytmanager.local_upload import DEFAULT_FRAME_RATE, LocalVideoProbe, SegmentDraft
from ytmanager.paths import user_cache_dir

FFMPEG_MANAGED_VERSION = "managed-latest"
FFMPEG_ARCHIVE_URLS = {
    "darwin": {
        "ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    },
    "windows": {
        "bundle": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
    },
    "linux": {
        "x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "amd64": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "arm64": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
        "aarch64": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    },
}


class FFmpegToolsError(RuntimeError):
    """ffmpeg/ffprobe 준비 또는 실행 실패."""


@dataclass(frozen=True)
class FFmpegToolchain:
    ffmpeg_path: Path
    ffprobe_path: Path
    version: str
    managed: bool


@dataclass(frozen=True)
class FFmpegStatus:
    available: bool
    ffmpeg_path: Path | None
    ffprobe_path: Path | None
    version: str
    managed: bool
    message: str


def current_platform_key() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system.startswith("win"):
        return "windows"
    if system == "linux":
        return "linux"
    return system


def current_architecture() -> str:
    return platform.machine().lower()


def ffmpeg_cache_dir(platform_key: str | None = None, version: str = FFMPEG_MANAGED_VERSION) -> Path:
    platform_key = platform_key or current_platform_key()
    return user_cache_dir() / "tools" / "ffmpeg" / version / platform_key


def ffmpeg_status() -> FFmpegStatus:
    try:
        toolchain = resolve_ffmpeg_toolchain(allow_download=False)
    except FFmpegToolsError as exc:
        return FFmpegStatus(False, None, None, "", False, str(exc))
    return FFmpegStatus(
        True,
        toolchain.ffmpeg_path,
        toolchain.ffprobe_path,
        toolchain.version,
        toolchain.managed,
        f"ffmpeg 준비됨: {toolchain.ffmpeg_path}",
    )


def resolve_ffmpeg_toolchain(allow_download: bool = True) -> FFmpegToolchain:
    managed = _find_cached_toolchain()
    if managed is not None:
        return managed
    system = _find_system_toolchain()
    if system is not None:
        return system
    if not allow_download:
        raise FFmpegToolsError("ffmpeg/ffprobe를 찾을 수 없습니다. 시스템 설치 또는 자동 다운로드가 필요합니다.")
    return prepare_ffmpeg_binaries()


def prepare_ffmpeg_binaries(*, downloader: Callable[[str, Path], None] | None = None) -> FFmpegToolchain:
    managed = _find_cached_toolchain()
    if managed is not None:
        return managed
    system = _find_system_toolchain()
    if system is not None:
        return system
    downloader = downloader or download_file
    platform_key = current_platform_key()
    cache_dir = ffmpeg_cache_dir(platform_key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytmanager-ffmpeg-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        extract_root = tmp_root / "extract"
        if platform_key == "darwin":
            ffmpeg_archive = tmp_root / "ffmpeg.zip"
            ffprobe_archive = tmp_root / "ffprobe.zip"
            downloader(FFMPEG_ARCHIVE_URLS["darwin"]["ffmpeg"], ffmpeg_archive)
            downloader(FFMPEG_ARCHIVE_URLS["darwin"]["ffprobe"], ffprobe_archive)
            safe_extract_archive(ffmpeg_archive, extract_root / "ffmpeg")
            safe_extract_archive(ffprobe_archive, extract_root / "ffprobe")
        elif platform_key == "windows":
            archive = tmp_root / "ffmpeg.zip"
            downloader(FFMPEG_ARCHIVE_URLS["windows"]["bundle"], archive)
            safe_extract_archive(archive, extract_root)
        elif platform_key == "linux":
            arch = current_architecture()
            try:
                url = FFMPEG_ARCHIVE_URLS["linux"][arch]
            except KeyError as exc:
                raise FFmpegToolsError(f"지원하지 않는 Linux 아키텍처입니다: {arch}") from exc
            archive = tmp_root / "ffmpeg.tar.xz"
            downloader(url, archive)
            safe_extract_archive(archive, extract_root)
        else:
            raise FFmpegToolsError(f"지원하지 않는 ffmpeg 플랫폼입니다: {platform_key}")

        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        shutil.copytree(extract_root, cache_dir)

    ffmpeg_path, ffprobe_path = find_ffmpeg_binaries(cache_dir)
    _ensure_executable_permission(ffmpeg_path)
    _ensure_executable_permission(ffprobe_path)
    return FFmpegToolchain(
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        version=inspect_ffmpeg_version(ffmpeg_path),
        managed=True,
    )


def find_ffmpeg_binaries(root: Path) -> tuple[Path, Path]:
    ffmpeg_name = "ffmpeg.exe" if current_platform_key() == "windows" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if current_platform_key() == "windows" else "ffprobe"
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.name == ffmpeg_name:
            ffmpeg_path = candidate
        elif candidate.name == ffprobe_name:
            ffprobe_path = candidate
    if ffmpeg_path is None or ffprobe_path is None:
        raise FFmpegToolsError("다운로드한 압축 파일에서 ffmpeg/ffprobe 실행 파일을 찾지 못했습니다.")
    return ffmpeg_path, ffprobe_path


def inspect_ffmpeg_version(ffmpeg_path: Path) -> str:
    completed = subprocess.run([str(ffmpeg_path), "-version"], capture_output=True, check=False)
    if completed.returncode != 0:
        raise FFmpegToolsError((_decode_process_output(completed.stderr) or _decode_process_output(completed.stdout) or "ffmpeg 버전 확인 실패").strip())
    first_line = (_decode_process_output(completed.stdout) or "").splitlines()[0].strip()
    return first_line or FFMPEG_MANAGED_VERSION


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def safe_extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    suffixes = archive_path.suffixes
    if suffixes[-2:] == [".tar", ".xz"] or archive_path.name.endswith(".tar.xz"):
        safe_extract_tar(archive_path, destination)
        return
    if archive_path.suffix.lower() == ".zip":
        safe_extract_zip(archive_path, destination)
        return
    raise FFmpegToolsError(f"지원하지 않는 압축 형식입니다: {archive_path.name}")


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination_resolved)
            except ValueError as exc:
                raise FFmpegToolsError(f"안전하지 않은 압축 경로입니다: {member.filename}") from exc
        archive.extractall(destination)


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination_resolved)
            except ValueError as exc:
                raise FFmpegToolsError(f"안전하지 않은 압축 경로입니다: {member.name}") from exc
        archive.extractall(destination)


def _ensure_executable_permission(path: Path) -> None:
    if current_platform_key() == "windows":
        return
    mode = path.stat().st_mode
    if mode & stat.S_IXUSR:
        return
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _find_cached_toolchain() -> FFmpegToolchain | None:
    cache_dir = ffmpeg_cache_dir()
    if not cache_dir.exists():
        return None
    try:
        ffmpeg_path, ffprobe_path = find_ffmpeg_binaries(cache_dir)
    except FFmpegToolsError:
        return None
    _ensure_executable_permission(ffmpeg_path)
    _ensure_executable_permission(ffprobe_path)
    return FFmpegToolchain(
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        version=inspect_ffmpeg_version(ffmpeg_path),
        managed=True,
    )


def _find_system_toolchain() -> FFmpegToolchain | None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return None
    ffmpeg_path = Path(ffmpeg)
    ffprobe_path = Path(ffprobe)
    try:
        version = inspect_ffmpeg_version(ffmpeg_path)
    except FFmpegToolsError:
        version = "system"
    return FFmpegToolchain(ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, version=version, managed=False)


def probe_local_video(
    source_path: Path | str,
    *,
    ffprobe_path: Path | str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LocalVideoProbe:
    source = Path(source_path)
    if not source.exists():
        raise FFmpegToolsError(f"영상 파일을 찾을 수 없습니다: {source}")
    toolchain = resolve_ffmpeg_toolchain(allow_download=True) if ffprobe_path is None else None
    ffprobe = Path(ffprobe_path) if ffprobe_path is not None else toolchain.ffprobe_path

    metadata = _run_ffprobe_json(
        ffprobe,
        ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(source)],
        runner=runner,
    )
    keyframes_payload = _run_ffprobe_json(
        ffprobe,
        [
            "-v",
            "error",
            "-skip_frame",
            "nokey",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,pkt_pts_time,pkt_dts_time,key_frame",
            "-print_format",
            "json",
            str(source),
        ],
        runner=runner,
    )
    streams = metadata.get("streams", []) if isinstance(metadata, dict) else []
    video_stream = next((stream for stream in streams if str(stream.get("codec_type", "")) == "video"), {})
    duration_seconds = _safe_float((metadata.get("format", {}) or {}).get("duration"))
    width_pixels = _safe_int(video_stream.get("width"))
    height_pixels = _safe_int(video_stream.get("height"))
    frame_rate = read_video_frame_rate(video_stream)
    keyframes = tuple(parse_ffprobe_keyframes(keyframes_payload))
    created_at = read_probe_created_at(metadata, source)
    modified_at = datetime.fromtimestamp(source.stat().st_mtime).astimezone().date().isoformat()
    return LocalVideoProbe(
        duration_seconds=duration_seconds,
        width_pixels=width_pixels,
        height_pixels=height_pixels,
        created_at=created_at,
        modified_at=modified_at,
        keyframes=keyframes,
        frame_rate=frame_rate,
    )


def parse_ffprobe_keyframes(payload: Mapping[str, Any]) -> list[float]:
    frames = payload.get("frames", []) if isinstance(payload, Mapping) else []
    keyframes: list[float] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        if str(frame.get("key_frame", "1")) not in {"1", "True", "true"}:
            continue
        value = frame.get("best_effort_timestamp_time")
        if value in (None, ""):
            value = frame.get("pkt_pts_time")
        if value in (None, ""):
            value = frame.get("pkt_dts_time")
        seconds = _safe_float(value)
        if seconds < 0:
            continue
        if keyframes and abs(keyframes[-1] - seconds) < 0.001:
            continue
        keyframes.append(seconds)
    return keyframes


def read_video_frame_rate(stream: Mapping[str, Any]) -> float:
    avg = parse_frame_rate(stream.get("avg_frame_rate"))
    if avg > 0:
        return avg
    rate = parse_frame_rate(stream.get("r_frame_rate"))
    if rate > 0:
        return rate
    return DEFAULT_FRAME_RATE


def parse_frame_rate(value: Any) -> float:
    if value in (None, "", "0/0"):
        return 0.0
    text = str(value).strip()
    if "/" in text:
        numerator_text, denominator_text = text.split("/", 1)
        numerator = _safe_float(numerator_text)
        denominator = _safe_float(denominator_text)
        if denominator == 0:
            return 0.0
        return numerator / denominator
    return _safe_float(text)


def read_probe_created_at(payload: Mapping[str, Any], source_path: Path) -> str:
    format_block = payload.get("format", {}) if isinstance(payload, Mapping) else {}
    tags = format_block.get("tags", {}) if isinstance(format_block, Mapping) else {}
    created = _normalize_date_text(tags.get("creation_time")) if isinstance(tags, Mapping) else ""
    if created:
        return created
    stat_result = source_path.stat()
    birthtime = getattr(stat_result, "st_birthtime", 0) or 0
    if birthtime > 0:
        return datetime.fromtimestamp(birthtime).astimezone().date().isoformat()
    return datetime.fromtimestamp(stat_result.st_mtime).astimezone().date().isoformat()


def split_video_segments(
    source_path: Path | str,
    segments: Sequence[SegmentDraft],
    output_dir: Path | str,
    ffmpeg_path: Path | str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Path]:
    source = Path(source_path)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    ffmpeg = Path(ffmpeg_path)
    outputs: list[Path] = []
    for segment in segments:
        if segment.duration_seconds <= 0:
            raise FFmpegToolsError(f"세그먼트 길이가 0초 이하입니다: {segment.index}")
        suffix = source.suffix or ".mp4"
        filename = build_safe_segment_filename(source, segment.index, suffix)
        target = output_root / filename
        command = build_ffmpeg_split_command(ffmpeg, source, target, segment.start_seconds, segment.duration_seconds)
        completed = runner(command, capture_output=True, check=False)
        if completed.returncode != 0:
            stderr = (_decode_process_output(completed.stderr) or _decode_process_output(completed.stdout) or "").strip()
            raise FFmpegToolsError(f"ffmpeg 분할 실패: {stderr[:400] or completed.returncode}")
        if not target.exists():
            raise FFmpegToolsError(f"분할 결과 파일이 생성되지 않았습니다: {target}")
        outputs.append(target)
    return outputs


def build_ffmpeg_split_command(
    ffmpeg_path: Path,
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
) -> list[str]:
    return [
        str(ffmpeg_path),
        "-y",
        "-ss",
        format_seconds(start_seconds),
        "-i",
        str(source_path),
        "-t",
        format_seconds(duration_seconds),
        "-c",
        "copy",
        "-map",
        "0",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]


def build_ffmpeg_frame_capture_command(
    ffmpeg_path: Path,
    source_path: Path,
    output_path: Path,
    seconds: float,
) -> list[str]:
    return [
        str(ffmpeg_path),
        "-y",
        "-ss",
        format_seconds(seconds),
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]


def capture_video_frame(
    source_path: Path | str,
    output_path: Path | str,
    seconds: float,
    ffmpeg_path: Path | str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    source = Path(source_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_frame_capture_command(Path(ffmpeg_path), source, target, seconds)
    completed = runner(command, capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = (_decode_process_output(completed.stderr) or _decode_process_output(completed.stdout) or "").strip()
        raise FFmpegToolsError(f"ffmpeg 프레임 캡처 실패: {stderr[:400] or completed.returncode}")
    if not target.exists():
        raise FFmpegToolsError(f"프레임 캡처 파일이 생성되지 않았습니다: {target}")
    return target


def format_seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"


def sanitize_filename(value: str) -> str:
    text = "".join("_" if char in '<>:"/\\|?*' else char for char in value.strip())
    text = " ".join(text.split())
    return text[:80].rstrip(" .")


def build_safe_segment_filename(source_path: Path, segment_index: int, suffix: str) -> str:
    digest = sha1(str(source_path).encode("utf-8")).hexdigest()[:10]
    return f"segment-{digest}-{segment_index:02d}{suffix}"


def _run_ffprobe_json(
    ffprobe_path: Path,
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Mapping[str, Any]:
    completed = runner([str(ffprobe_path), *arguments], capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = (_decode_process_output(completed.stderr) or _decode_process_output(completed.stdout) or "").strip()
        raise FFmpegToolsError(f"ffprobe 실행 실패: {stderr[:400] or completed.returncode}")
    try:
        return json.loads(_decode_process_output(completed.stdout) or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegToolsError("ffprobe JSON 파싱에 실패했습니다.") from exc


def _normalize_date_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().date().isoformat()
    except ValueError:
        return text[:10]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _decode_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        preferred = locale.getpreferredencoding(False) or "utf-8"
        try:
            return value.decode(preferred)
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="replace")
    return str(value)
