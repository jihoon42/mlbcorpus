# MLB Stats API 탐색 결과 (2026-09-19)

브레인스토밍(09-18)에서 "Stats API로 직접 구축"을 택한 뒤, 실제 응답을 열어 보고 확인한 사실만 적는다. 모든 수치는 아래 표본 경기에서 직접 센 값이다.

기준 표본: **gamePk 824464, LAD@CIN, 2026-09-17 (Final, 8-2)**. 시즌 범위 확인에는 2008·2012·2015·2017·2018(6월, 9월 두 경기)·2019(3/28, 4/15, 6/15)·2020~2025 각 1경기를 추가로 열었다.

## 1. 엔드포인트 4개로 충분하다

| 엔드포인트 | 용도 | 크기(표본) |
|---|---|---|
| `GET /api/v1/schedule?sportId=1&season={YYYY}&gameType=R` | 시즌의 gamePk 목록. `status.detailedState == "Final"`만 취함 | 시즌당 1회 |
| `GET /api/v1.1/game/{pk}/feed/live` | 경기 메타(gameData) + 플레이·투구(liveData.plays) + 박스스코어 + 라인스코어 | 834 KB |
| `GET /api/v1/game/{pk}/content` | **리캡 기사 본문**, 하이라이트 캡션, 영상 메타 | 610 KB |
| `GET /api/v1/game/{pk}/winProbability` | 플레이별 승리확률·WPA·레버리지 | ~0.8 MB (allPlays를 통째로 다시 포함) |

브레인스토밍에서 걱정했던 "리캡 본문이 API로 오는가"는 **온다**로 확정. MLB.com 기사 크롤링 단계가 필요 없다.

## 2. feed/live 구조 (표본 경기 기준)

`liveData.plays.allPlays`는 타석(plate appearance) 단위. 표본은 79타석, 그 안의 `playEvents` 345개(투구 299, action 38, pickoff 4, stepoff 4).

타석 하나(`allPlays[i]`)에서 쓸 필드:

- `result`: `description`(문장), `event`("Home Run"), `eventType`("home_run"), `rbi`, `isOut`, `awayScore`/`homeScore`(플레이 **후** 점수), `type`("atBat")
- `about`: `atBatIndex`, `inning`, `halfInning`, `isTopInning`, `startTime`/`endTime`(ISO, 밀리초), `isScoringPlay`, `hasOut`, `hasReview`, **`captivatingIndex`**(MLB 자체 흥미도, 정수; 표본 HR은 38)
- `count`: 타석 종료 시점의 `balls`/`strikes`/`outs`. **`outs`는 플레이 후 아웃카운트**(1루 땅볼 → outs 1). 타석 시작 아웃카운트는 같은 하프이닝의 직전 타석 `count.outs`로 유도.
- `matchup`: `batter{id,fullName}`, `pitcher{id,fullName}`, `batSide`, `pitchHand`, `splits{batter:"vs_RHP", pitcher:"vs_LHB", menOnBase:"Empty"}`, `postOnFirst/Second/Third{id,fullName}` — 이름 그대로 **플레이 후** 주자. 시작 시점 주자 상황은 직전 타석의 postOn*으로 유도(하프이닝 첫 타석은 빈 베이스).
- `runners[]`: 주자 이동 단위. `movement{start,end,outBase,outNumber,isOut}`, `details{event,eventType,movementReason,isScoringEvent,rbi,earned,responsiblePitcher,playIndex}`, `credits[]`(수비 기록 6-4-3 같은 것)
- `playEvents[]`: 투구·비투구 이벤트. 공통 `index`, `type`, `isPitch`, `count`(이 이벤트 **후** 카운트), `startTime`/`endTime`, `playId`(UUID)
  - 투구(`isPitch`): `pitchNumber`, `details{type{code:"SI",description:"Sinker"}, call{code,description}, isBall,isStrike,isInPlay,isOut}`, `pitchData{startSpeed,endSpeed,zone,plateTime,extension,strikeZoneTop/Bottom,typeConfidence, breaks{spinRate,spinDirection,breakAngle,breakLength,breakVertical,breakVerticalInduced,breakHorizontal}, coordinates{pX,pZ,x0,y0,z0,vX0,vY0,vZ0,aX,aY,aZ,pfxX,pfxZ}}`, 인플레이면 `hitData{launchSpeed,launchAngle,totalDistance,trajectory,hardness,location,coordinates{coordX,coordY}}`
  - 비투구: `details{event:"Pitching Substitution"|"Defensive Sub"|"Mound Visit"|"Pickoff Attempt 1B"|"Game Advisory"|...}`, `player`, `position`, `replacedPlayer`, `isSubstitution`, `isBaseRunningPlay`, `base`

`gameData`: `game{pk,season,type,doubleHeader,gameNumber}`, `datetime{dateTime,officialDate,dayNight}`, `status`, `teams{home,away}`(id, name, abbreviation, teamName="Reds", locationName, league, division, venue), `players{ID_xxx}`(56명; fullName, useName, lastName, boxscoreName "Smith, W", nickName, nameSlug, primaryPosition, batSide, pitchHand, birthDate, birthCountry, mlbDebutDate 등 **이름 변이형 7종**), `venue`, `weather{condition,temp,wind}`, `gameInfo{attendance,firstPitch,gameDurationMinutes}`, `probablePitchers`, `flags{noHitter,perfectGame,...}`

`liveData.boxscore.teams.{home,away}`: `players{ID_xxx}` 각각 `stats{batting,pitching,fielding}`(경기 기록; `batting.summary`가 **"0-4 | 3 K"**, `pitching.summary`가 **"3.1 IP, 7 ER, 0 K, 4 BB"**, `pitching.note`가 "(L, 6-15)" 같은 문자열), `seasonStats`(경기 시점 시즌 누적 — 기사에 나오는 "ERA를 1.89로 낮췄다" 검증용), `battingOrder`("200"=2번 선발, 끝자리≠0이면 교체), `position`, `allPositions`, `gameStatus{isSubstitute}`. 팀 단위 `batters[]`, `pitchers[]`, `bench[]`, `bullpen[]`, `battingOrder[]`, `teamStats`. 경기 단위 `info[]`(HBP, Pitches-strikes, Umpires, Weather, T: 2:39, Att: 24,169 …), `officials[]`, `topPerformers[]`.

`liveData.linescore`: `innings[]{num, home{runs,hits,errors,leftOnBase}, away{...}}`, `teams{home,away}` 합계. `liveData.decisions{winner,loser,save}`.

## 3. content 구조 — 텍스트 층이 세 겹 있다

`editorial.recap.mlb`:
- `headline`, `seoTitle`, `slug`, `blurb`(첫 300자), `date`, `contributors[{name}]`(기자), `url`, `keywordsAll[]`(team/game/player/taxonomy 태그, `bodyParagraphCount`)
- **`body`**: HTML. `<p>` 단락, 안에 `<a>`, `<iframe>`(영상·트윗 임베드), 가끔 `<blockquote>`·`<script>`(트윗), 마크다운식 `[텍스트](url)` 링크가 섞여 있음. 표본 6,376자 / 8단락 / 인용부호 51개. 2024·2025 표본은 5,649자·5,021자. **선수 이름에 링크가 없다** → 지시 해소는 우리가 박스스코어 로스터로 직접 해야 함(Frege 장의 재료).
- `editorial.preview`, `editorial.wrap`은 표본에서 비어 있음(`summary.hasPreviewArticle=false`).

`highlights.highlights.items[]` (표본 40개):
- 각 항목 `title`, `headline`, `blurb`, **`description`**(한 문장 캡션: "Kyle Tucker hammers a two-run home run to right-center field, giving the Dodgers a 2-0 lead in the top of the 1st inning"), `duration`, `date`, `keywordsAll[]`(`player:playerid-678020`, `game_pk:824464`, `taxonomy:home-run` 같은 문자열 태그), `playbacks[]`, `cclocationVtt`
- **`guid` == `playEvents[].playId`**. 표본 40개 중 13개에 guid가 있고 13개 전부 특정 투구에 정확히 붙는다. 즉 캡션은 플레이 단위로 정렬된 두 번째 텍스트 층이다.
- `cclocationVtt`: 방송 자막(WebVTT) URL. 표본 24개에 존재, 도메인은 `mlb-cuts-diamond.mlb.com` / `diamond.mlb.com`. 2020년 이후 표본에서는 0개였으므로 안정적인 층으로 보지 않는다(선택 층).

같은 플레이 하나에 세 가지 register가 붙는다. Saussure 장의 재료가 여기서 나온다.

| 층 | 예 (표본 HR, atBatIndex 2) | 성격 |
|---|---|---|
| `result.description` | "Kyle Tucker homers (16) on a fly ball to right center field. Freddie Freeman scores." | 공식 기록 문장, 정형 |
| highlight `description` | "Kyle Tucker hammers a two-run home run to right-center field, giving the Dodgers a 2-0 lead in the top of the 1st inning" | 편집자 캡션, 한 문장 |
| recap `body` | 기사 단락 안의 언급 | 저널리즘 서사, 선택적 |

**`content?language=es`** 를 붙이면 같은 경기의 **스페인어 리캡**이 온다(표본 4,182자, 같은 기자 명의, 영어판의 번역으로 보임). 경기 단위 EN–ES 병렬 코퍼스가 추가 수집 없이 확보된다. 스페인어 확장은 이 한 줄로 끝난다.

## 4. winProbability

플레이 배열(79개, `atBatIndex`로 조인). 각 항목에 allPlays의 플레이 객체 전체 + `homeTeamWinProbability`, `awayTeamWinProbability`, `homeTeamWinProbabilityAdded`(WPA, 홈팀 기준 %p), `leverageIndex`(첫 타석은 null), `contextMetrics`(표본에서 빈 객체), `credits[]`. 표본 HR: 홈팀 승률 49.8 → 33.1, WPA −16.7, LI 1.21.

## 5. 시즌별 커버리지 — 리캡은 2019년부터

| 시즌 | 정규시즌 Final 경기 수 | description / captivatingIndex | about.startTime | pitchData(구속·무브먼트) | hitData(타구속도·발사각) | 리캡·하이라이트 |
|---|---|---|---|---|---|---|
| 2008 | 2,427 | 있음 | **없음** | 있음(256/285) | 없음 | **없음** |
| 2012 | 2,423 | 있음 | 있음 | 있음 | 없음 | 없음 |
| 2015 | 2,429 | 있음 | 있음 | 있음 | 부분(인플레이 41 중 32) | 없음 |
| 2017 | — | 있음 | 있음 | 있음 | 49/53 | 없음 |
| 2018 | 2,428 | 있음 | 있음 | 있음 | 45/50 | 없음(6월·9월·9/30 모두) |
| **2019** | — | 있음 | 있음 | 있음 | 44/51 | **있음(개막일 3/28부터)** |
| 2020 | 898 | 있음 | 있음 | 있음 | 36/37 | 있음 |
| 2021~2025 | 2,430 / — / 2,433 / 2,428 / 2,429 | 있음 | 있음 | 있음 | 인플레이 전부 | 있음 |
| 2026 | 2,293 (9/19 현재, 9/27 종료) | 있음 | 있음 | 있음 | 전부 | 있음 |

결론: **리캡 정렬 코퍼스의 핵심 범위는 2019~2026 (8시즌, 2020 단축)**. 정규시즌 Final 기준 약 17,900경기, 타석 약 135만, 투구 약 520만, 리캡 약 17,900편(편당 ~5,000자 ≈ 850단어 → 약 1,500만 단어), 플레이 정렬 캡션 약 15~25만 문장. 2015~2018은 플레이·투구 데이터만 있으므로 뉴스가치 모델의 베이스라인 확률 추정에 보태는 용도 외에는 수집 우선순위가 낮다.

schedule에는 Postponed·Cancelled 항목이 같은 날짜에 따로 잡히므로 `detailedState == "Final"`로 걸러야 한다(우천 순연 경기는 새 날짜에 다시 Final로 나타남). "Completed Early"(강우 콜드 등, 시즌당 2~7경기)는 별도 플래그로 두고 포함.

## 6. 실행 환경 제약

- **인증 불필요.** 위 엔드포인트는 전부 로그인·API 키 없이 열려 있다(오늘 탐색 전부 익명 `fetch`). 로그인이 걸리는 곳은 `statsapi.mlb.com/docs/` → `docs.statsapi.mlb.com`(Okta 로그인/Register)의 **공식 문서 포털**뿐이며, 여기는 MLB 승인 대상이라 개인은 사실상 못 들어간다. 문서 대신 §8의 커뮤니티 레지스트리를 쓴다.
- 클라우드 워크스페이스와 Cowork VM 셸 양쪽 모두 `statsapi.mlb.com` 접속이 정책상 차단됨(HTTP CONNECT 403). 오늘 탐색은 Claude 내장 브라우저에서 `fetch`로 했다.
- 따라서 **수집기는 JiHoon의 맥 터미널에서 직접 실행**한다. 코드 작성·결과 분석은 Cowork에서 하고, 실행만 로컬 터미널에서. 수집 결과가 `NLP/data/`에 떨어지면 Cowork가 그 파일을 바로 읽을 수 있다.
- 요청량: 경기당 3~4회(feed, content, content?language=es, winProbability) × 17,900 ≈ 6~7만 요청. 초당 3~4회로 제한하면 5~6시간. 재개 가능(resume)하게 만들 것.
- 응답마다 붙는 저작권 고지: "Use of any content on this page acknowledges agreement to the terms posted here http://gdx.mlb.com/components/copyright.txt". 수업용 비상업 분석은 통상 문제없지만, **원본 덤프를 공개 저장소에 올리지 않는다**(코드만 공개, 데이터는 재생성 스크립트로). 보고서에 출처와 고지를 명기.

## 8. 참고: toddrob99/MLB-StatsAPI (2026-09-19 추가)

`https://github.com/toddrob99/MLB-StatsAPI` — PyPI `MLB-StatsAPI` 1.9.0(2025-04), GPL-3.0, 의존성은 `requests` 하나. 소스를 읽고 확인한 것:

- 핵심은 `statsapi/endpoints.py`의 `ENDPOINTS` 딕셔너리(62개 엔드포인트, 각각 URL 템플릿·path/query 파라미터·필수 파라미터·주석). **막힌 공식 문서의 대체물이 이 파일이다.** 우리가 쓰는 네 개는 `schedule`, `game`(= v1.1 feed/live), `game_content`(query `highlightLimit`), `game_winProbability`로 등록돼 있고, 그 외 `game_playByPlay`·`game_boxscore`·`game_linescore`(feed/live의 부분 집합), `game_timestamps`/`game_diff`(경기 중 증분), `people`/`person`, `teams`, `meta` 등이 있다.
- `statsapi.get(endpoint, params)`는 URL을 조립해 `requests.get(url)` 한 번 호출하고 `.json()`을 돌려주는 게 전부. 헤더·User-Agent 지정, 재시도, 속도 제한, 캐시 **모두 없음**. 인증 코드가 한 줄도 없다는 것 자체가 "API는 열려 있다"는 증거.
- 편의 함수(`schedule()`, `boxscore()`, `game_highlight_data()` 등)는 사람이 읽는 표 문자열을 만드는 쪽이라 우리 정규화 테이블에는 안 쓴다. 다만 `game_highlight_data()`가 쓰는 **hydrate 트릭**은 유용하다.
- `hydrate`: schedule 엔드포인트에 `hydrate=game(content(editorial(recap),highlights(highlights)))`를 붙이면 **하루치 경기 전체의 리캡 본문이 한 요청에 온다**(9/17 9경기 = 1.6 MB, `&language=es`로 스페인어도 동일). 즉 리캡만 먼저 모으려면 시즌당 약 185요청으로 끝난다. 단 하이라이트는 하이드레이션에서 경기당 10개로 잘리므로(경기별 content는 40개) 캡션 층은 경기별 `content` 호출을 유지한다. 사용 가능한 하이드레이션 목록은 `schedule?sportId=1&hydrate=hydrations&fields=hydrations`로 조회(`linescore`, `decisions`, `scoringplays`, `probablePitcher`, `weather`, `officials`, `lineups`, `homeRuns`, `story`, `preGameOdds` 등 80여 개).
- `meta` 엔드포인트: `/api/v1/eventTypes`(74개, `plateAppearance`·`hit` 플래그 포함), `pitchTypes`, `pitchCodes`, `gameStatus`, `gameTypes`, `hitTrajectories`, `situationCodes`, `positions`, `reviewReasons` 등 코드표. `event_type` 차원 테이블은 여기서 받아 채운다.
- 라이선스 판단: 우리 레포는 코드 제출 대상이라 GPL 의존성을 피한다. `endpoints.py`는 **참고 문서로만** 쓰고 수집기는 `httpx`로 직접 작성(어차피 URL 네 개). README에 참고했음을 명기.

스페인어 리캡 길이 비교(9/17): 823334 EN 11,082자 / ES 11,638자, 824464 EN 6,376 / ES 4,182, 822924 EN 5,140 / ES 3,148. 번역이되 축약되는 경우가 있어 보이므로 EN–ES는 문서 단위 병렬로 두고 문장 정렬은 별도 검증.

## 7. 다음 단계에서 바로 쓰는 판단

1. 시즌 범위: 2019~2026 정규시즌을 1차 수집 대상으로. 포스트시즌(`gameType=P,D,L,W,F`)은 리캡 문체가 다르므로 수집은 하되 `game_type`으로 구분.
2. 원본 JSON은 그대로 gzip 캐시(경기당 4개 응답 합계 약 2.8 MB → 압축 후 약 300 KB, 17,900경기면 5~6 GB). 가공 테이블은 원본에서 재생성.
3. 스페인어 리캡은 처음부터 같이 받는다(요청 1회 추가).
4. 방송 자막(VTT)은 별도 도메인·불안정 → 1차 범위 제외, 스키마에 URL 컬럼만 남김.
