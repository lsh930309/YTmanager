from __future__ import annotations

import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from ytmanager.paths import user_cache_dir
from ytmanager.thumbnail import MAX_THUMBNAIL_BYTES

WAIFU2X_VERSION = "20250915"
WAIFU2X_ARCHIVE_URLS = {
    "darwin": (
        "https://sourceforge.net/projects/waifu2x-ncnn-vulkan.mirror/files/"
        "20250915/waifu2x-ncnn-vulkan-20250915-macos.zip/download"
    ),
    "windows": (
        "https://sourceforge.net/projects/waifu2x-ncnn-vulkan.mirror/files/"
        "20250915/waifu2x-ncnn-vulkan-20250915-windows.zip/download"
    ),
    "linux": (
        "https://sourceforge.net/projects/waifu2x-ncnn-vulkan.mirror/files/"
        "20250915/waifu2x-ncnn-vulkan-20250915-linux.zip/download"
    ),
}
JPEG_QUALITY_STEPS = (92, 88, 84, 80, 76)
TARGET_THUMBNAIL_WIDTH = 1280
TARGET_THUMBNAIL_HEIGHT = 720


class ThumbnailUpscaleError(RuntimeError):
    """썸네일 업스케일 처리 실패."""


@dataclass(frozen=True)
class UpscaleResult:
    output_path: Path
    mode: str
    engine: str
    fallback_used: bool
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    jpeg_quality: int
    size_bytes: int
    message: str


@dataclass(frozen=True)
class Waifu2xStatus:
    available: bool
    platform_key: str
    cache_dir: Path
    executable_path: Path | None
    archive_url: str
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


def waifu2x_cache_dir(platform_key: str | None = None, version: str = WAIFU2X_VERSION) -> Path:
    platform_key = platform_key or current_platform_key()
    return user_cache_dir() / "tools" / "waifu2x-ncnn-vulkan" / version / platform_key


def waifu2x_archive_url(platform_key: str | None = None) -> str:
    platform_key = platform_key or current_platform_key()
    try:
        return WAIFU2X_ARCHIVE_URLS[platform_key]
    except KeyError as exc:
        raise ThumbnailUpscaleError(f"지원하지 않는 waifu2x 플랫폼입니다: {platform_key}") from exc


def executable_names(platform_key: str | None = None) -> tuple[str, ...]:
    platform_key = platform_key or current_platform_key()
    if platform_key == "windows":
        return ("waifu2x-ncnn-vulkan.exe",)
    return ("waifu2x-ncnn-vulkan",)


def find_executable(root: Path, platform_key: str | None = None) -> Path | None:
    names = set(executable_names(platform_key))
    if not root.exists():
        return None
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.name in names:
            return candidate
    return None


def waifu2x_status(platform_key: str | None = None) -> Waifu2xStatus:
    platform_key = platform_key or current_platform_key()
    cache_dir = waifu2x_cache_dir(platform_key)
    archive_url = waifu2x_archive_url(platform_key)
    executable = find_executable(cache_dir, platform_key)
    if executable is None:
        return Waifu2xStatus(
            available=False,
            platform_key=platform_key,
            cache_dir=cache_dir,
            executable_path=None,
            archive_url=archive_url,
            message=f"waifu2x 미설치 · 캐시: {cache_dir}",
        )
    executable_ok = platform_key == "windows" or executable.stat().st_mode & stat.S_IXUSR
    if not executable_ok:
        return Waifu2xStatus(
            available=False,
            platform_key=platform_key,
            cache_dir=cache_dir,
            executable_path=executable,
            archive_url=archive_url,
            message=f"waifu2x 실행 권한 없음: {executable}",
        )
    return Waifu2xStatus(
        available=True,
        platform_key=platform_key,
        cache_dir=cache_dir,
        executable_path=executable,
        archive_url=archive_url,
        message=f"waifu2x 준비됨: {executable}",
    )


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination_resolved)
            except ValueError as exc:
                raise ThumbnailUpscaleError(f"안전하지 않은 압축 경로입니다: {member.filename}") from exc
        archive.extractall(destination)


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _ensure_executable_permission(path: Path) -> None:
    if current_platform_key() == "windows":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def prepare_waifu2x_binary(
    *,
    platform_key: str | None = None,
    downloader: Callable[[str, Path], None] = download_file,
) -> Path:
    platform_key = platform_key or current_platform_key()
    cache_dir = waifu2x_cache_dir(platform_key)
    executable = find_executable(cache_dir, platform_key)
    if executable:
        _ensure_executable_permission(executable)
        return executable

    url = waifu2x_archive_url(platform_key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytmanager-waifu2x-") as tmp:
        archive_path = Path(tmp) / f"waifu2x-ncnn-vulkan-{WAIFU2X_VERSION}-{platform_key}.zip"
        extract_dir = Path(tmp) / "extract"
        downloader(url, archive_path)
        safe_extract_zip(archive_path, extract_dir)
        executable = find_executable(extract_dir, platform_key)
        if executable is None:
            raise ThumbnailUpscaleError("waifu2x 실행 파일을 압축 파일에서 찾지 못했습니다.")
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        shutil.copytree(extract_dir, cache_dir)

    executable = find_executable(cache_dir, platform_key)
    if executable is None:
        raise ThumbnailUpscaleError("waifu2x 실행 파일 캐시 준비에 실패했습니다.")
    _ensure_executable_permission(executable)
    return executable


def build_waifu2x_command(
    executable: Path,
    input_path: Path,
    output_path: Path,
    *,
    noise: int = 1,
    scale: int = 2,
) -> list[str]:
    command = [
        str(executable),
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-n",
        str(noise),
        "-s",
        str(scale),
        "-f",
        "png",
    ]
    model_path = executable.parent / "models-cunet"
    if model_path.exists():
        command.extend(["-m", str(model_path)])
    return command


def run_waifu2x(
    input_path: Path,
    output_path: Path,
    *,
    noise: int = 1,
    scale: int = 2,
    timeout_seconds: int = 30,
    executable: Path | None = None,
) -> None:
    executable = executable or prepare_waifu2x_binary()
    command = build_waifu2x_command(executable, input_path, output_path, noise=noise, scale=scale)
    completed = subprocess.run(
        command,
        cwd=str(executable.parent),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise ThumbnailUpscaleError(f"waifu2x 실행 실패: {stderr[:300] or completed.returncode}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ThumbnailUpscaleError("waifu2x 출력 파일이 생성되지 않았습니다.")


def image_dimensions(path: Path) -> tuple[int, int]:
    image = QImage(str(path))
    if image.isNull():
        raise ThumbnailUpscaleError(f"이미지를 열 수 없습니다: {path}")
    return image.width(), image.height()


def _cover_to_target(image: QImage, width: int, height: int) -> QImage:
    scaled = image.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    return scaled.copy(x, y, width, height)


def finalize_jpeg(
    input_path: Path,
    output_path: Path,
    *,
    target_width: int = TARGET_THUMBNAIL_WIDTH,
    target_height: int = TARGET_THUMBNAIL_HEIGHT,
    qualities: Sequence[int] = JPEG_QUALITY_STEPS,
) -> tuple[int, int, int, int]:
    image = QImage(str(input_path))
    if image.isNull():
        raise ThumbnailUpscaleError(f"이미지를 열 수 없습니다: {input_path}")
    final = _cover_to_target(image, target_width, target_height)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_quality = qualities[-1]
    for quality in qualities:
        if not final.save(str(output_path), "JPG", quality):
            raise ThumbnailUpscaleError("최종 JPEG 저장에 실패했습니다.")
        last_quality = quality
        if output_path.stat().st_size <= MAX_THUMBNAIL_BYTES:
            break
    return final.width(), final.height(), last_quality, output_path.stat().st_size


def upscale_thumbnail_candidate(
    input_path: Path,
    output_path: Path,
    *,
    mode: str = "waifu2x",
    noise: int = 1,
    scale: int = 2,
    timeout_seconds: int = 30,
) -> UpscaleResult:
    input_width, input_height = image_dimensions(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "off":
        output_width, output_height, quality, size = finalize_jpeg(input_path, output_path)
        return UpscaleResult(
            output_path=output_path,
            mode=mode,
            engine="off",
            fallback_used=False,
            input_width=input_width,
            input_height=input_height,
            output_width=output_width,
            output_height=output_height,
            jpeg_quality=quality,
            size_bytes=size,
            message=f"처리: off · q{quality}",
        )

    if mode == "waifu2x":
        with tempfile.TemporaryDirectory(prefix="ytmanager-upscale-") as tmp:
            waifu_output = Path(tmp) / "waifu2x-output.png"
            try:
                run_waifu2x(
                    input_path,
                    waifu_output,
                    noise=noise,
                    scale=scale,
                    timeout_seconds=timeout_seconds,
                )
                output_width, output_height, quality, size = finalize_jpeg(waifu_output, output_path)
                return UpscaleResult(
                    output_path=output_path,
                    mode=mode,
                    engine="waifu2x",
                    fallback_used=False,
                    input_width=input_width,
                    input_height=input_height,
                    output_width=output_width,
                    output_height=output_height,
                    jpeg_quality=quality,
                    size_bytes=size,
                    message=f"처리: waifu2x -n {noise} -s {scale} → downscale · q{quality}",
                )
            except Exception as exc:
                output_width, output_height, quality, size = finalize_jpeg(input_path, output_path)
                return UpscaleResult(
                    output_path=output_path,
                    mode=mode,
                    engine="fast",
                    fallback_used=True,
                    input_width=input_width,
                    input_height=input_height,
                    output_width=output_width,
                    output_height=output_height,
                    jpeg_quality=quality,
                    size_bytes=size,
                    message=f"처리: fast fallback ({str(exc)[:120]}) · q{quality}",
                )

    output_width, output_height, quality, size = finalize_jpeg(input_path, output_path)
    return UpscaleResult(
        output_path=output_path,
        mode="fast",
        engine="fast",
        fallback_used=(mode != "fast"),
        input_width=input_width,
        input_height=input_height,
        output_width=output_width,
        output_height=output_height,
        jpeg_quality=quality,
        size_bytes=size,
        message=f"처리: fast · q{quality}",
    )
