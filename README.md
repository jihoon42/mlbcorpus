# mlbcorpus

MLB Stats API로 구축하는 야구 텍스트 코퍼스. 홍익대 불문과 〈언어의미와정보〉 2026-2 팀 프로젝트의 데이터 파이프라인이다.

같은 경기 하나에 붙는 세 겹의 영어 텍스트 — 공식 플레이 기록 문장, 하이라이트 캡션, MLB.com 리캡 기사 — 를 플레이 단위 구조 기록(박스스코어·플레이바이플레이·Statcast·승리확률)에 정렬해, 기사에서 "정보"인 부분과 "의미"인 부분의 경계를 데이터로 그리는 것이 목표다. 설계 배경은 `docs/`에 있다.

- `docs/00-team-guide.md` — 팀원 안내: 무엇을 하는 프로젝트인지, 어디를 보면 되는지, 지금 부탁드리는 것
- `docs/01-statsapi-findings.md` — API 실측: 엔드포인트, 응답 구조, 시즌별 커버리지, 접근 제약
- `docs/02-schema.md` — 원본 캐시 레이아웃과 정규화 테이블 스키마, 장(章)별 의존 컬럼
- `docs/dissect/` — 경기 하나를 세 register 로 정렬한 분석 보고서 (`mlbcorpus dissect` 출력)
- `notebooks/mlb_playground.ipynb` — 팀원용 Colab 노트북. 설치 없이 경기 하나를 API에서 바로 받아 표·기사·그래프로 보고(1~6), 그 기사로 문장 분리·품사 태깅·표제어 추출·한국어 형태소 분석을 해 본다(7~9). 저장소 코드에 의존하지 않는 독립 실행형

## 요구 사항

- [uv](https://docs.astral.sh/uv/) (Python 3.12는 uv가 자동으로 받는다)
- 네트워크: `statsapi.mlb.com` (인증·API 키 없음)

## 설치

```bash
uv sync            # .venv 생성 + 의존성 설치
uv run pytest      # 네트워크 없이 도는 단위 테스트
```

## 사용

```bash
# 1. 연결·형식 확인: 경기 하나를 받아 요약 출력 (2026-09-17 LAD@CIN)
uv run mlbcorpus sample --pk 824464

# 2. 코드표 저장 (eventTypes, pitchTypes, gameTypes ...)
uv run mlbcorpus meta

# 3. 본 수집. 기본 범위는 2019~2026 정규시즌 + 포스트시즌, 영어·스페인어 content.
#    중간에 끊겨도 다시 실행하면 manifest 기준으로 이어서 받는다.
uv run mlbcorpus crawl
uv run mlbcorpus crawl --seasons 2025 --game-types R --limit 50     # 범위를 좁혀서
uv run mlbcorpus crawl --rps 2 --concurrency 2                       # 더 천천히

# 4. 진행 상황
uv run mlbcorpus status

# 5. 경기 하나 분석: 기록 문장·캡션·리캡을 타석 단위로 정렬한 보고서 → docs/dissect/824464.md
uv run mlbcorpus dissect --pk 824464
uv run mlbcorpus dissect --pk 824464 --json > /tmp/824464.json   # 정렬 결과를 JSON 으로
```

경기당 요청 4개(feed/live, content en, content es, winProbability), 초당 3요청 기본값으로 8시즌 약 18,000경기는 6~7시간이 걸린다. 원본은 gzip으로 경기당 약 300 KB, 전체 5~6 GB.

## 데이터 레이아웃

```
data/                         # .gitignore 대상. 재생성은 crawl 로.
  crawl.log
  raw/
    manifest.sqlite           # 수집 상태 (resume 의 근거)
    schedule/{season}_{gameType}.json.gz
    meta/{kind}.json.gz
    games/{season}/{gamePk}/
      feed.json.gz            # /api/v1.1/game/{pk}/feed/live
      content.en.json.gz      # /api/v1/game/{pk}/content
      content.es.json.gz      # ...?language=es
      winprob.json.gz         # /api/v1/game/{pk}/winProbability
  tables/                     # build-tables 출력 (Parquet) — 미구현
```

원본은 받은 바이트 그대로 저장하고 가공 테이블은 언제든 원본에서 다시 만든다.

## 코드 구성

```
src/mlbcorpus/
  config.py      경로·시즌·게임 타입·속도 제한
  endpoints.py   URL 조립
  fetch.py       속도 제한 + 재시도 HTTP 클라이언트
  storage.py     gzip 원자적 쓰기
  schedule.py    schedule 응답 → 종료 경기 판정, 순연 중복 제거
  manifest.py    SQLite 수집 상태
  crawl.py       수집 루프, sample/meta
  dissect.py     경기 하나의 세 register 정렬 (문장 분리·이름 찾기·플레이 대조 휴리스틱)
  dissect_md.py  정렬 결과 → Markdown 보고서
  cli.py         명령줄
  normalize/     원본 → 테이블 (예정)
tests/           respx 로 HTTP 를 흉내 낸 단위 테스트
```

## Colab 노트북

`notebooks/mlb_playground.ipynb`는 `notebooks/build_playground.py`가 생성한다. 셀 내용을 고칠 때는 노트북이 아니라 이 스크립트를 고치고 다시 생성한다. 네트워크 없이 캐시된 응답으로 전체 셀을 실행해 보는 검사도 있다.

```bash
uv run --group notebooks python notebooks/build_playground.py          # 노트북 생성
uv run --group notebooks python notebooks/test_playground_offline.py   # 캐시된 824464 로 오프라인 실행 검사
```

Colab에 올리는 방법은 `docs/00-team-guide.md` 참고.

## 저장소 운영

- 브랜치는 `main` 하나. 실험은 로컬 브랜치에서 하고 정리된 것만 `main`에 올린다.
- 커밋 메시지는 한 줄 요약, 영역을 앞에 붙인다: `crawl: 429 재시도에 Retry-After 반영`, `docs: 02-schema §1.2 outs_before 규칙`, `dissect: 투수 집계 문장 정렬`.
- `docs/dissect/*.md`는 생성물이지만 팀 논의 자료라서 커밋한다. 코드가 바뀌어 보고서가 달라지면 같은 커밋에서 재생성해 올린다.
- `data/`, `.venv/`, `.pytest_cache/`, `.DS_Store`는 `.gitignore`로 제외. `git status`에 `data/`가 보이면 무언가 잘못된 것.
- 올리기 전에 `uv run pytest`.

## 데이터 이용 고지

MLB Stats API 응답에는 "Use of any content on this page acknowledges agreement to the terms posted here http://gdx.mlb.com/components/copyright.txt" 가 붙어 있다. 수업용 비상업 분석 목적으로만 쓰고, 원본 덤프는 저장소에 올리지 않는다.

엔드포인트와 파라미터는 공식 문서(로그인 필요) 대신 [toddrob99/MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI)의 `statsapi/endpoints.py`를 참고했다. 라이브러리 자체는 쓰지 않는다.
