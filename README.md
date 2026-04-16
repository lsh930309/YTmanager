# YTmanager

YTmanager는 개인 YouTube 채널에 이미 업로드된 영상을 한국어 GUI에서 빠르게 관리하기 위한 데스크톱 앱입니다.
Windows 11을 1차 지원 대상으로 두고, PySide6 기반이라 macOS 확장도 가능한 구조로 시작합니다.

## MVP 기능

- Google OAuth 로그인 및 YouTube Data API v3 연동
- 내 채널 업로드 영상 목록 동기화
- 제목 `[]` 글머리와 설명 상단 해시태그 자동 연동
- `DESCRIPTION_TEMPLATE.md` 기반 구조화 설명 렌더링
- YouTube 임베드 플레이어에서 현재 시점을 찍어 설명 타임스탬프에 추가
- YouTube 재생 화면 기반 썸네일 후보 캡처 POC 및 `thumbnails.set` 업로드 흐름
- 적용 전 변경사항 diff와 로컬 스냅샷 저장

## 개발 환경

권장 Python은 3.12입니다. 현재 코드는 테스트 편의를 위해 Python 3.9 이상 문법으로 작성되어 있습니다.

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
python -m pip install -e .[dev]
python -m unittest discover -s tests
python -m ytmanager
```

macOS/Linux 개발 환경에서는 다음처럼 실행할 수 있습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .[dev]
python -m unittest discover -s tests
python -m ytmanager
```

## Google OAuth 설정

개인 사용 단계에서는 Google Cloud Console에서 YouTube Data API v3를 활성화하고 데스크톱 OAuth 클라이언트를 준비합니다.
공개 배포 수준으로 확장하려면 OAuth 동의 화면, 개인정보 처리방침, 민감 스코프 검증 자료가 필요합니다.

앱은 아래 순서로 OAuth 클라이언트 JSON을 찾습니다.

1. 환경변수 `YTMANAGER_OAUTH_CLIENT_SECRET`
2. 사용자 설정 디렉터리의 `client_secret.json`
3. 현재 작업 디렉터리의 `client_secret.json`

향후 배포 빌드에서는 검증된 OAuth 클라이언트 설정을 패키지 리소스로 포함할 수 있습니다. 단, refresh token은 항상 OS 보안 저장소에 저장합니다.

## 설명 템플릿

프로젝트 루트의 `DESCRIPTION_TEMPLATE.md`를 앱의 설명 구조 계약으로 사용합니다. 기본 예시는 다음과 같습니다.

```md
[{game_version} {game_content_name} {game_content_season_in_current_version}]
{top_tags}

{timestamps}

{notes}
```

사용 가능한 기본 placeholder는 `game_version`, `game_content_name`, `game_content_season_in_current_version`, `top_tags`, `timestamps`, `notes`입니다.


## 제목 글머리/해시태그 규칙

앱은 사용자 데이터 디렉터리의 `rules.json`을 읽어 제목 글머리와 설명 상단 해시태그를 연결합니다.
처음에는 내장 기본값으로 `[젠존제]` → `#zenlesszonezero`가 제공되며, `rules.example.json`을 복사해 확장할 수 있습니다.

```json
[
  {
    "title_prefix": "젠존제",
    "description_tags": ["#zenlesszonezero"],
    "display_name": "젠레스 존 제로"
  }
]
```

## Windows 패키징

```powershell
python -m pip install -e .[dev]
pyinstaller packaging/pyinstaller/ytmanager.spec --clean --noconfirm
```

그 다음 Inno Setup에서 `packaging/windows/ytmanager.iss`를 열어 설치 파일을 생성합니다.

## 정책/기술상 주의

- YouTube Data API는 업로드된 영상 원본 프레임을 직접 제공하지 않습니다.
- 썸네일 스냅샷은 공식 임베드 플레이어 화면 캡처 POC로 격리되어 있으며, 환경에 따라 검은 화면이 캡처될 수 있습니다.
- 비공식 다운로드/스트림 추출 방식은 사용하지 않습니다.
- `videos.update`는 누락된 mutable 필드를 삭제할 수 있으므로 기존 snippet을 보존한 payload만 전송합니다.
