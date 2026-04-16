from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "YTmanager"


def user_data_dir() -> Path:
    """OS별 사용자 데이터 디렉터리를 반환한다."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_database_path() -> Path:
    return user_data_dir() / "ytmanager.sqlite3"


def default_client_secret_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("YTMANAGER_OAUTH_CLIENT_SECRET")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(user_data_dir() / "client_secret.json")
    candidates.append(Path.cwd() / "client_secret.json")
    return candidates


def find_client_secret() -> Path | None:
    for candidate in default_client_secret_candidates():
        if candidate.exists():
            return candidate
    return None
