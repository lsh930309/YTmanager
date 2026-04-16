# 게임별 캐릭터 마스터 사전 구축 계획

## 목표

- 게임별 캐릭터의 한국어 기준 대표명, 영문명, 별칭, 희귀도, 속성, 역할/운명의 길 등을 하나의 마스터 사전으로 관리한다.
- 설명란 역파싱으로 얻은 `character_roster`와 연결해 메타데이터 입력 시 자동완성/추천값을 제공한다.
- 공식/준공식 위키 데이터를 우선하고, 한국어 별칭은 나무위키/수동 사전으로 보강한다.

## 데이터 모델

마스터 사전의 최소 공통 필드:

- `game_key`
- `canonical_name_ko`
- `canonical_name_en`
- `display_name`
- `aliases_ko`
- `rarity`
- `element`
- `role_or_path`
- `source_name`
- `source_url`
- `extra`

게임별 고유 속성은 `extra`에 보관한다.

## 구현 순서

1. `character_master` SQLite 테이블 추가.
2. `character_master.example.json` 형식 정의.
3. `scripts/import_character_master.py`로 로컬 JSON import 지원.
4. import 시 `character_aliases`에도 대표명/별칭을 함께 반영.
5. `scripts/update_character_master.py`로 URL/정규식 기반 초기 수집기를 제공하고, 이후 게임별 공식/나무위키 수집기로 확장.
6. GUI 자동완성은 `character_master + character_roster`를 합쳐 추천 후보를 제공하도록 추후 연결.

## 소스 우선순위

1. 공식/준공식 위키 또는 공식 캐릭터 페이지.
2. 나무위키 한국어 캐릭터 목록/개별 문서.
3. 수동 JSON 보정 파일.

## 안전 원칙

- 외부 웹 수집 결과는 바로 기존 alias를 덮어쓰지 않고, 마스터 사전에 source를 남긴다.
- 별칭은 `character_aliases`로 동기화하되, 같은 게임 내 alias 충돌은 나중에 GUI에서 검수한다.
- 자동완성은 마스터 사전의 대표명과 alias를 우선 사용하고, 기존 역파싱 roster는 보유 상태 추천에 사용한다.

## 현재 구현된 빌드 파이프라인

- `scripts/update_character_master.py --list-sources`로 내장 소스 목록을 확인한다.
- `scripts/build_character_master.py`는 기본 소스를 수집하고 `.local/master/` 아래에 소스별 JSON, 병합 JSON, 리포트를 생성한다.
- `--apply`를 붙이면 병합 결과를 `character_master` DB에 import하고 `character_aliases`도 동기화한다.
- 현재 내장 소스:
  - `zzz_gg_ko`: ZZZ.GG 한국어 젠레스 존 제로 캐릭터 목록
  - `hoyodb_hsr_ko`: HoYoDB/BitTopup Wiki 한국어 붕괴: 스타레일 목록
  - `namu_hsr_ko`: 나무위키 한국어 붕괴: 스타레일 캐릭터 문서
  - `namu_ww_ko`: 나무위키 한국어 명조 공명자 문서
  - `endfield_wiki_en`: Arknights: Endfield Wiki 영어 오퍼레이터 목록

### 권장 명령

```bash
.venv/bin/python scripts/build_character_master.py --output-dir .local/master
.venv/bin/python scripts/build_character_master.py --output-dir .local/master --apply
```

### 현재 품질 메모

- 젠레스 존 제로: 한국어명/역할/희귀도는 양호하나 일부 속성 누락이 있다.
- 붕괴: 스타레일: 나무위키는 한국어 운명의 길이 좋고 HoYoDB는 속성 보강에 유용하다.
- 명조: 나무위키에서 한국어명/속성은 확보되지만 희귀도와 무기/직군은 추가 소스가 필요하다.
- 엔드필드: 영어 위키 기준으로 영어명/속성/직군/희귀도를 확보하며, 한국어명은 추후 보강이 필요하다.

