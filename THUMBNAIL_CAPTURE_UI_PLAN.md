# 썸네일 캡처 UI 계획: `controls=0` YouTube 렌더러 + 앱 자체 미니멀 컨트롤

## Summary
- YouTube iframe은 순정 UI 조작용이 아니라 영상 렌더링 전용으로 사용한다.
- iframe에는 `controls=0`, `disablekb=1`, `fs=0`, `iv_load_policy=3`, `rel=0`, `playsinline=1`을 적용한다.
- 플레이어 위에는 투명 mouse shield를 덮어 YouTube iframe이 hover/click/mousemove를 받지 못하게 한다.
- 재생/탐색/프레임 이동/캡처는 앱 자체 UI와 단축키로만 제어한다.

## Key Changes
- 실패한 iframe 내부 CSS 주입 방식과 offscreen/교체형 캡처 플레이어 경로를 제거한다.
- 기존 `QWebEngineView` 하나만 유지하고, `PLAYER_HTML`은 `controls=0` 렌더러로 동작하게 한다.
- `FixedVideoFrame` 안에서 `QWebEngineView` 위에 투명 `MouseShield` 위젯을 덮어 hover overlay 발생을 차단한다.
- 플레이어 하단에 미니멀 아이콘 컨트롤을 둔다: `⏪`, `◂`, `⏵/⏸`, `▸`, `⏩`, 현재 시간, 타임스탬프 추가, `📸`.
- 최초 재생도 앱 자체 `⏵` 버튼 또는 Space 단축키로 동작해야 한다.
- 캡처는 현재 보이는 `QWebEngineView`를 직접 `grab()`하고, 검은 테두리 crop 및 16:9 후보 `1280×720` 리사이즈를 유지한다.

## UI / UX Acceptance Criteria
- 영상 선택 직후 YouTube 순정 재생 버튼/재생바/상단 제목 UI가 플레이어에 보이지 않아야 한다.
- 앱 자체 `⏵` 버튼 또는 Space로 최초 재생이 가능해야 한다.
- 마우스를 플레이어 위로 올려도 YouTube 순정 hover UI가 나타나지 않아야 한다.
- 앱 자체 버튼과 단축키로 재생/일시정지, 5초 이동, 1프레임 이동이 가능해야 한다.
- 썸네일 후보 이미지에는 앱 UI와 YouTube 순정 UI가 포함되지 않아야 한다.
- 미리보기는 검은 여백 없이 꽉 차게 표시되어야 한다.

## Test Plan
- `python -m unittest discover -s tests`
- `ruff check src tests`
- `compileall -q src tests`
- `.venv/bin/python -m ytmanager` 실행 시 segfault 없이 창이 떠야 한다.
- 수동 확인: 최초 재생, mouse shield hover 차단, Space/Left/Right/`,`/`.` 단축키, 여러 상태에서 캡처 결과 확인.

## Assumptions
- 로컬 원본 파일, 공식 다운로드 파일, yt-dlp 기반 다운로드/스트림 추출은 이번 계획 범위에서 제외한다.
- 이 방식은 다운로드 없이 가능한 마지막 합리적 iframe 기반 접근이다.
- YouTube iframe이 `controls=0` 상태에서도 특정 상태에서 자체 overlay를 강제로 표시하면, 해당 overlay는 앱이 안정적으로 제거할 수 없을 수 있다.
