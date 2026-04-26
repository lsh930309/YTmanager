from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from ytmanager.paths import find_client_secret, user_data_dir
from ytmanager.youtube_api import DEFAULT_READ_SCOPES, DEFAULT_WRITE_SCOPES

KEYRING_SERVICE = "YTmanager"
KEYRING_ACCOUNT = "google-oauth-token"


class OAuthSetupError(RuntimeError):
    """OAuth 설정 또는 로그인 실패."""


@dataclass(frozen=True)
class OAuthClientConfig:
    client_secret_path: Path
    scopes: tuple[str, ...]

    @classmethod
    def discover(cls, scopes: Iterable[str]) -> "OAuthClientConfig":
        path = find_client_secret()
        if path is None:
            candidates = "\n".join(str(item) for item in [user_data_dir() / "client_secret.json", Path.cwd() / "client_secret.json"])
            raise OAuthSetupError(
                "OAuth 클라이언트 JSON을 찾을 수 없습니다. Google Cloud Console에서 데스크톱 OAuth 클라이언트를 만든 뒤 "
                f"다음 위치 중 하나에 저장하세요:\n{candidates}"
            )
        return cls(path, tuple(scopes))


class TokenStore:
    def __init__(self, service_name: str = KEYRING_SERVICE, account_name: str = KEYRING_ACCOUNT) -> None:
        self.service_name = service_name
        self.account_name = account_name

    def load(self) -> Optional[dict[str, Any]]:
        file_token = self._token_file()
        try:
            import keyring
        except ImportError:
            return self._load_file_token(file_token)
        try:
            raw = keyring.get_password(self.service_name, self.account_name)
        except Exception:
            raw = None
        if raw:
            return json.loads(raw)
        return self._load_file_token(file_token)

    def save(self, token_info: dict[str, Any]) -> None:
        try:
            import keyring
            keyring.set_password(self.service_name, self.account_name, json.dumps(token_info))
            return
        except Exception:
            # macOS 키체인은 CLI/샌드박스 실행에서 쓰기 실패할 수 있으므로
            # 개발 환경 fallback으로 사용자 데이터 디렉터리의 토큰 파일을 사용한다.
            self._save_file_token(token_info)

    def clear(self) -> None:
        try:
            import keyring
            keyring.delete_password(self.service_name, self.account_name)
        except Exception:
            pass
        try:
            self._token_file().unlink()
        except FileNotFoundError:
            pass

    def exists(self) -> bool:
        file_token = self._token_file()
        try:
            import keyring
        except ImportError:
            return file_token.exists()
        try:
            raw = keyring.get_password(self.service_name, self.account_name)
        except Exception:
            raw = None
        return bool(raw) or file_token.exists()

    def _token_file(self) -> Path:
        return user_data_dir() / "token.json"

    @staticmethod
    def _load_file_token(path: Path) -> Optional[dict[str, Any]]:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_file_token(self, token_info: dict[str, Any]) -> None:
        path = self._token_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(token_info), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


class OAuthManager:
    def __init__(self, token_store: TokenStore | None = None) -> None:
        self.token_store = token_store or TokenStore()

    def login(self, write_access: bool = False) -> Any:
        config = self._discover_config(write_access)
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise OAuthSetupError("Google OAuth 패키지가 설치되어 있지 않습니다.") from exc

        credentials = self._load_cached_credentials(config, Credentials, Request)
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(config.client_secret_path), list(config.scopes))
            credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
            self.token_store.save(json.loads(credentials.to_json()))
        return credentials

    def has_saved_login(self) -> bool:
        return self.token_store.exists()

    def build_cached_youtube_service(self, write_access: bool = False) -> Any | None:
        if not self.token_store.exists():
            return None
        config = self._discover_config(write_access)
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise OAuthSetupError("Google OAuth 패키지가 설치되어 있지 않습니다.") from exc
        credentials = self._load_cached_credentials(config, Credentials, Request)
        if not credentials or not credentials.valid:
            return None
        return build("youtube", "v3", credentials=credentials)

    def build_youtube_service(self, write_access: bool = False) -> Any:
        credentials = self.login(write_access=write_access)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise OAuthSetupError("google-api-python-client가 설치되어 있지 않습니다.") from exc
        return build("youtube", "v3", credentials=credentials)

    def _discover_config(self, write_access: bool) -> OAuthClientConfig:
        scopes = list(DEFAULT_READ_SCOPES)
        if write_access:
            scopes = list(dict.fromkeys(scopes + DEFAULT_WRITE_SCOPES))
        return OAuthClientConfig.discover(scopes)

    def _load_cached_credentials(self, config: OAuthClientConfig, credentials_cls: Any, request_cls: Any) -> Any:
        credentials = None
        token_info = self.token_store.load()
        if token_info:
            raw = token_info.get("scopes", "")
            if isinstance(raw, str):
                granted = set(raw.split())
            else:
                granted = set(raw or [])
            if granted.issuperset(config.scopes):
                credentials = credentials_cls.from_authorized_user_info(token_info, list(config.scopes))
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(request_cls())
            self.token_store.save(json.loads(credentials.to_json()))
        return credentials
