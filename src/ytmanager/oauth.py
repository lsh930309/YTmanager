from __future__ import annotations

import json
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
        try:
            import keyring
        except ImportError:
            return None
        raw = keyring.get_password(self.service_name, self.account_name)
        if not raw:
            return None
        return json.loads(raw)

    def save(self, token_info: dict[str, Any]) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise OAuthSetupError("토큰 저장을 위해 keyring 패키지가 필요합니다.") from exc
        keyring.set_password(self.service_name, self.account_name, json.dumps(token_info))

    def clear(self) -> None:
        try:
            import keyring
            keyring.delete_password(self.service_name, self.account_name)
        except Exception:
            return


class OAuthManager:
    def __init__(self, token_store: TokenStore | None = None) -> None:
        self.token_store = token_store or TokenStore()

    def login(self, write_access: bool = False) -> Any:
        scopes = list(DEFAULT_READ_SCOPES)
        if write_access:
            scopes = list(dict.fromkeys(scopes + DEFAULT_WRITE_SCOPES))
        config = OAuthClientConfig.discover(scopes)
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise OAuthSetupError("Google OAuth 패키지가 설치되어 있지 않습니다.") from exc

        credentials = None
        token_info = self.token_store.load()
        if token_info:
            credentials = Credentials.from_authorized_user_info(token_info, list(config.scopes))
            if hasattr(credentials, "has_scopes") and not credentials.has_scopes(list(config.scopes)):
                credentials = None
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_store.save(json.loads(credentials.to_json()))
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(config.client_secret_path), list(config.scopes))
            credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
            self.token_store.save(json.loads(credentials.to_json()))
        return credentials

    def build_youtube_service(self, write_access: bool = False) -> Any:
        credentials = self.login(write_access=write_access)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise OAuthSetupError("google-api-python-client가 설치되어 있지 않습니다.") from exc
        return build("youtube", "v3", credentials=credentials)
