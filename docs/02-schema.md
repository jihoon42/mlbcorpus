# 코퍼스 스키마 설계 v0.1 (2026-09-19)

전제: `01-statsapi-findings.md`의 확인 사실. 원칙 세 가지.

1. **원본은 손대지 않고 캐시한다.** 가공 테이블은 언제든 원본에서 재생성. 스키마를 고칠 때 API를 다시 치지 않는다.
2. **"전"과 "후"를 컬럼 이름에 박는다.** API의 `count.outs`, `postOnFirst`, `result.homeScore`, `splits.menOnBase`는 모두 플레이 **후** 상태다. 뉴스가치·정보량 모델은 플레이 **전** 상태를 조건으로 삼으므로 둘 다 명시한다.
3. **텍스트는 세 register를 같은 키로 잇는다.** `plays.description`(공식 기록) — `highlights.description`(캡션, `play_id`로 조인) — `articles.body_text`(리캡, `game_pk`로 조인 후 문장 정렬).

## 0. 저장 레이아웃

```
NLP/
  data/
    raw/
      schedule/{season}_{game_type}.json.gz
      games/{season}/{game_pk}/feed.json.gz          # /api/v1.1/game/{pk}/feed/live
      games/{season}/{game_pk}/content.en.json.gz    # /api/v1/game/{pk}/content
      games/{season}/{game_pk}/content.es.json.gz    # ...?language=es
      games/{season}/{game_pk}/winprob.json.gz       # /api/v1/game/{pk}/winProbability
      meta/{kind}.json.gz                            # /api/v1/eventTypes 등 코드표
      manifest.sqlite                                # 수집 상태 (resume용)
    tables/          # 아래 §1의 정규화 테이블, Parquet
    derived/         # 문장 분리·정렬·피처 등 파생물 (별도 문서)
  crawl.log
```

구현: `src/mlbcorpus/` (config·endpoints·fetch·storage·schedule·manifest·crawl·cli). 2026-09-19 기준 수집기까지 구현, `normalize/`는 스텁.

- 포맷: Parquet(pyarrow) + DuckDB로 조회. pandas로 바로 읽히므로 수업 실습 수준과도 이어진다.
- 키 규약: `game_pk`(INT), `at_bat_index`(INT, `about.atBatIndex`), `event_index`(INT, `playEvents[].index`), `play_id`(TEXT UUID, `playEvents[].playId`), `player_id`, `team_id`(INT).
- 시간은 전부 UTC TIMESTAMP. 날짜는 `official_date`(현지 기준 경기 날짜).

## 1. 테이블

### 1.1 `games` — 경기당 1행. PK `game_pk`

| 컬럼 | 타입 | 출처 (feed/live 기준) |
|---|---|---|
| game_pk | INT | gameData.game.pk |
| season | INT | gameData.game.season |
| game_type | TEXT | gameData.game.type (R 정규, P/D/L/W/F 포스트시즌) |
| official_date | DATE | gameData.datetime.officialDate |
| game_datetime_utc | TIMESTAMP | gameData.datetime.dateTime |
| day_night | TEXT | gameData.datetime.dayNight |
| double_header, game_number | TEXT, INT | gameData.game.doubleHeader / gameNumber |
| status_detailed | TEXT | gameData.status.detailedState ("Final", "Completed Early") |
| venue_id, venue_name | INT, TEXT | gameData.venue |
| home_team_id, away_team_id | INT | gameData.teams.{home,away}.id |
| home_score, away_score | INT | liveData.linescore.teams.{home,away}.runs |
| home_hits, away_hits, home_errors, away_errors, home_lob, away_lob | INT | linescore.teams.* |
| innings_played, scheduled_innings | INT | linescore.currentInning / scheduledInnings |
| winner_team_id | INT | 파생 |
| winning_pitcher_id, losing_pitcher_id, save_pitcher_id | INT | liveData.decisions |
| home_probable_pitcher_id, away_probable_pitcher_id | INT | gameData.probablePitchers |
| attendance, duration_minutes, first_pitch_utc | INT, INT, TIMESTAMP | gameData.gameInfo |
| weather_condition, temp_f, wind | TEXT, INT, TEXT | gameData.weather |
| umpire_hp | TEXT | boxscore.officials (officialType == "Home Plate") |
| no_hitter, perfect_game | BOOL | gameData.flags |
| series_description, series_game_number, games_in_series | TEXT, INT, INT | schedule 항목 |
| n_plays, n_pitches | INT | 파생 |
| has_recap_en, has_recap_es, n_highlights | BOOL, BOOL, INT | 파생 (content) |

### 1.2 `plays` — 타석(plate appearance)당 1행. PK (`game_pk`, `at_bat_index`)

뒤의 모든 장이 이 테이블에 걸린다. 컬럼을 넉넉히 둔다.

| 컬럼 | 타입 | 출처 / 규칙 |
|---|---|---|
| game_pk, at_bat_index | INT | about.atBatIndex |
| inning, half, is_top | INT, TEXT, BOOL | about.inning / halfInning / isTopInning |
| batting_team_id, fielding_team_id | INT | 파생 (top이면 away 공격) |
| batter_id, batter_name, bat_side | INT, TEXT, TEXT | matchup.batter, batSide.code |
| pitcher_id, pitcher_name, pitch_hand | INT, TEXT, TEXT | matchup.pitcher, pitchHand.code |
| split_batter, split_pitcher | TEXT | matchup.splits ("vs_RHP", "vs_LHB") |
| **outs_before** | INT | 파생: 같은 하프이닝 직전 타석의 outs_after, 하프이닝 첫 타석은 0 |
| outs_after | INT | count.outs |
| balls_final, strikes_final | INT | count.balls / strikes (타석 종료 시 카운트) |
| **runner_1b_before, runner_2b_before, runner_3b_before** | INT | 파생: 직전 타석의 *_after, 하프이닝 첫 타석은 NULL |
| runner_1b_after, runner_2b_after, runner_3b_after | INT | matchup.postOnFirst/Second/Third.id |
| base_state_before, base_state_after | TEXT | 파생, "---"·"1-3" 식 8가지 |
| men_on_base_after | TEXT | matchup.splits.menOnBase |
| **home_score_before, away_score_before** | INT | 파생: 직전 타석의 *_after, 경기 첫 타석은 0 |
| home_score_after, away_score_after | INT | result.homeScore / awayScore |
| score_diff_before | INT | 파생, 공격팀 관점 (양수면 공격팀 리드) |
| runs_scored | INT | 파생 (after − before 합) |
| event, event_type | TEXT | result.event ("Home Run") / eventType ("home_run") |
| **description** | TEXT | result.description — register 1 |
| rbi | INT | result.rbi |
| is_out, is_scoring_play, has_out, has_review | BOOL | result.isOut / about.* |
| **captivating_index** | INT | about.captivatingIndex |
| start_time_utc, end_time_utc | TIMESTAMP | about.startTime / endTime |
| n_pitches, n_events | INT | len(pitchIndex) / len(playEvents) |
| **last_play_id** | TEXT | 마지막 투구의 playId — highlights 조인 키 |
| last_pitch_type, last_pitch_speed | TEXT, FLOAT | 마지막 투구의 details.type.code / pitchData.startSpeed |
| launch_speed, launch_angle, hit_distance, hit_trajectory, hit_hardness, hit_location, hit_coord_x, hit_coord_y | FLOAT, FLOAT, FLOAT, TEXT, TEXT, TEXT, FLOAT, FLOAT | 마지막 투구의 hitData (인플레이가 아니면 NULL) |
| **home_wp_before, home_wp_after** | FLOAT | winProbability: 직전 항목의 homeTeamWinProbability / 이 항목의 값. 첫 타석 before = 50.0 |
| **home_wpa** | FLOAT | winProbability.homeTeamWinProbabilityAdded |
| wpa_batting_team | FLOAT | 파생: 공격팀 관점 부호 |
| **leverage_index** | FLOAT | winProbability.leverageIndex (첫 타석 NULL) |

주의: 타석 도중 도루·견제사 등으로 주자 상황이 바뀌면 `*_before`는 타석 **시작** 시점, 마지막 투구 시점과 다를 수 있다. 정밀한 시점별 상황이 필요한 분석(투구 단위 레버리지)은 `runners`와 `play_events`에서 재구성한다.

### 1.3 `pitches` — 투구당 1행. PK (`game_pk`, `at_bat_index`, `event_index`)

| 컬럼 | 타입 | 출처 |
|---|---|---|
| game_pk, at_bat_index, event_index, pitch_number | INT | playEvents[].index / pitchNumber |
| play_id | TEXT | playEvents[].playId |
| pitch_type_code, pitch_type_desc | TEXT | details.type.code / description ("SI", "Sinker") |
| call_code, call_desc | TEXT | details.call.code / description ("E", "In play, run(s)") |
| is_ball, is_strike, is_in_play, is_out | BOOL | details.* |
| balls_before, strikes_before | INT | 파생: 같은 타석 직전 이벤트의 *_after, 첫 투구는 0-0 |
| balls_after, strikes_after, outs_after | INT | count (이 이벤트 **후**) |
| start_speed, end_speed, zone, plate_time, extension, sz_top, sz_bottom, type_confidence | FLOAT | pitchData.* |
| spin_rate, spin_direction, break_angle, break_length, break_vertical, break_vertical_induced, break_horizontal | FLOAT | pitchData.breaks.* |
| px, pz, x0, y0, z0, vx0, vy0, vz0, ax, ay, az, pfx_x, pfx_z | FLOAT | pitchData.coordinates.* |
| launch_speed, launch_angle, total_distance, trajectory, hardness, hit_location, hit_coord_x, hit_coord_y | FLOAT/TEXT | hitData.* (인플레이만) |
| runner_going, disengagement_num | BOOL, INT | details.runnerGoing / disengagementNum (2023+ 규정) |
| start_time_utc, end_time_utc | TIMESTAMP | playEvents[].startTime / endTime |

### 1.4 `play_events` — 비투구 이벤트(교체·견제·마운드 방문·리뷰·advisory). PK (`game_pk`, `at_bat_index`, `event_index`)

`type`(action/pickoff/stepoff …), `event`, `event_type`, `description`, `player_id`, `position_code`, `replaced_player_id`, `is_substitution`, `is_base_running_play`, `base`, `is_scoring_play`, `home_score`, `away_score`, `has_review`, `start_time_utc`.

### 1.5 `runners` — 주자 이동당 1행. PK (`game_pk`, `at_bat_index`, `runner_seq`)

`runner_id`, `start_base`, `end_base`("score" 포함), `is_out`, `out_base`, `out_number`, `event`, `event_type`, `movement_reason`, `is_scoring_event`, `rbi`, `earned`, `team_unearned`, `responsible_pitcher_id`, `event_index`(details.playIndex), `credits_json`(수비 크레딧 "6-4-3" 복원용).

### 1.6 `boxscore_players` — (경기, 선수)당 1행. PK (`game_pk`, `player_id`)

| 컬럼 | 출처 |
|---|---|
| team_id, is_home, jersey_number | boxscore.teams.*.players[] |
| position_code, position_abbr, all_positions(list) | position / allPositions |
| batting_order_raw ("200"), batting_order_slot (2), is_starter (끝자리 0), is_substitute | battingOrder, gameStatus.isSubstitute |
| pa, ab, r, h, doubles, triples, hr, rbi, bb, ibb, so, hbp, sb, cs, sf, sh, gidp, lob, total_bases | stats.batting |
| **batting_summary** ("0-4 \| 3 K") | stats.batting.summary — "went 0-for-4" 검증의 정답 |
| ip, pitches_thrown, strikes_thrown, batters_faced, h_allowed, r_allowed, er, bb_allowed, so_pitched, hr_allowed, hbp_pitched, win, loss, save, hold, blown_save | stats.pitching (inningsPitched, numberOfPitches, strikes, battersFaced, hits, runs, earnedRuns, baseOnBalls, strikeOuts, homeRuns, hitBatsmen, wins, losses, saves, holds, blownSaves) |
| **pitching_summary** ("3.1 IP, 7 ER, 0 K, 4 BB"), pitching_note ("(L, 6-15)") | stats.pitching.summary / note |
| putouts, assists, errors | stats.fielding |
| stats_json, season_stats_json | stats / seasonStats 원본 — 기사가 인용하는 "ERA 1.89" 같은 시즌 누적치 검증용 |

### 1.7 `players` — 선수 차원 테이블. PK `player_id` (마지막으로 본 값)

`full_name`, `first_name`, `last_name`, `use_name`, `use_last_name`, `middle_name`, `boxscore_name`("Smith, W"), `nick_name`, `name_slug`, `name_first_last`, `name_last_first`, `init_last_name`, `last_init_name`, `full_fml_name`, `primary_position_code`, `primary_position_abbr`, `bat_side`, `pitch_hand`, `birth_date`, `birth_city`, `birth_country`, `height`, `weight`, `mlb_debut_date`, `draft_year`, `first_seen_game_pk`, `last_seen_game_pk`.

이름 변이형 7종이 Frege 장(지시 해소)의 사전이다. 리캡 본문에는 선수 링크가 없으므로 경기 로스터(`boxscore_players` ∩ `players`) 안에서 이름 매칭으로 해소한다. 로스터가 50명 안팎으로 닫혀 있어 성(姓)만으로도 대부분 유일하다.

### 1.8 `teams` — PK (`team_id`, `season`)

`name`("Cincinnati Reds"), `team_name`("Reds"), `location_name`, `abbreviation`, `short_name`, `franchise_name`, `club_name`, `league`, `division`, `venue_id`, `venue_name`, `file_code`. 기사에서 팀은 "the Reds", "Cincinnati", "the Dodgers" 등으로 지칭되므로 변이형 컬럼이 그대로 사전.

### 1.9 `linescore` — PK (`game_pk`, `inning`, `side`)

`runs`, `hits`, `errors`, `lob`. 생성 모델 입력의 최소 단위.

### 1.10 `boxscore_notes` — PK (`game_pk`, `scope`, `seq`)

`scope`(game/home/away), `label`("HBP", "Pitches-strikes", "Umpires", "T", "Att" …), `value`. 준(準)텍스트 공식 기록. 정렬·팩트체크 보조.

### 1.11 `articles` — PK (`game_pk`, `language`, `article_type`)

| 컬럼 | 출처 (content) |
|---|---|
| language ("en"/"es"), article_type ("recap"/"preview"/"wrap") | 요청 파라미터 / editorial 키 |
| slug (식별자 — 리캡 객체에는 id 필드가 없음), headline, seo_title, blurb, url | editorial.{type}.mlb.* |
| **body_html** | body 원본 |
| **body_text** | 정제본 (§2 규칙) |
| n_paragraphs | 파생 (keywordsAll의 bodyParagraphCount와 대조) |
| authors (list) | contributors[].name |
| published_at | date |
| tagged_player_ids, tagged_team_ids, taxonomy_tags (list) | keywordsAll[] type별 |
| keywords_json | keywordsAll 원본 |

### 1.12 `highlights` — PK (`game_pk`, `highlight_id`)

| 컬럼 | 출처 (content.highlights.highlights.items[]) |
|---|---|
| highlight_id | id (슬러그 문자열, 경기 안에서 유일 — 표본 40/40) |
| **play_id** (nullable) | guid — `pitches.play_id` / `plays.last_play_id`로 조인 |
| at_bat_index (nullable) | 파생 (play_id 조인) |
| type, title, headline, blurb | * |
| **description** | 한 문장 캡션 — register 2 |
| duration_sec, published_at, slug, media_playback_id | duration(파싱), date, slug, mediaPlaybackId |
| tagged_player_ids, tagged_team_ids, taxonomy_tags (list) | keywordsAll[] ("player:playerid-678020" 파싱) |
| cc_vtt_url (nullable) | cclocationVtt — 1차 범위 밖, URL만 보존 |
| keywords_json | 원본 |

### 1.13 `manifest.sqlite` — 수집 상태 (Parquet 아님: 경기 하나마다 한 행씩 갱신해야 하므로)

- `games` (PK `game_pk`): `season`, `game_type`, `official_date`, `status_detailed`, `status_code`, `finished`, `home_team_id`, `away_team_id`, `double_header`, `game_number`, `seen_at`. schedule에서 본 모든 경기(미종료 포함).
- `fetches` (PK `game_pk`, `resource`): `ok`, `bytes`, `fetched_at`, `error`. `resource` ∈ {feed, content.en, content.es, winprob}.

수집기의 resume는 `fetches.ok = 1`만 본다. 실패한 리소스는 다음 실행에서 자동으로 다시 시도.

## 2. `body_html` → `body_text` 정제 규칙

1. `<iframe>`, `<script>`, `<blockquote>`(트윗 임베드) 블록 제거.
2. `<a href>텍스트</a>` → 텍스트, 마크다운식 `[텍스트](url)` → 텍스트.
3. `<p>` 경계와 단락 내부 `\n\n`을 모두 단락 경계로. `<br>`은 줄바꿈.
4. HTML 엔티티 복원. 인용부호(" " ' ')와 대시(`--`, `—`)는 **원형 유지** — 인용문 탐지와 문체 분석의 신호이므로 파생 단계에서 정규화한다.
5. 데이트라인("CINCINNATI -- ")은 첫 단락에서 분리해 `dateline` 컬럼으로.

## 3. 장(章)별 의존 컬럼 — 스키마가 결정하는 것

| 보고서 장 | 필요한 컬럼 |
|---|---|
| 정렬 코퍼스 구축 (1단계) | plays.description, articles.body_text, highlights.description+play_id, players 이름 변이형, boxscore_players.batting_summary |
| 뉴스가치(정보) 모델 — Bar-Hillel/Carnap | plays.{event_type, captivating_index, home_wpa, leverage_index, inning, score_diff_before, base_state_before, outs_before, runs_scored, launch_speed, hit_distance}, boxscore_players.season_stats_json(스타성), 정답: 리캡 언급 여부(파생) |
| 정보 추출 — distant supervision (2단계) | plays.{batter_id, pitcher_id, event_type, rbi, runs_scored}, boxscore_players 전 컬럼, articles.body_text |
| 생성 + 팩트체크 (3단계) | games, linescore, boxscore_players, plays (입력) → articles.body_text (목표); 추출기 출력 ↔ 위 테이블 대조 |
| Saussure — 기의당 기표 수 | plays.event_type × {plays.description, highlights.description, 리캡 정렬 문장} |
| Wittgenstein 후기 — clutch/gem의 쓰임 | plays.{leverage_index, home_wpa, score_diff_before, inning}, games.{home_score, away_score}, 리캡 어휘 |
| Frege — 지칭 표현 | players 변이형, boxscore_players.{position_abbr, batting_order_slot}, teams 변이형, 리캡 멘션(파생) |
| 형태론 — 사건 명사의 동사화 | plays.description(동사형 homered/singled), 리캡 문장, 시즌(통시) |

## 4. 파생 테이블 (다음 문서에서 설계, 여기서는 이름만)

`article_paragraphs`, `article_sentences`(is_quote, speaker_id), `sentence_play_alignment`(sentence_id, at_bat_index, method, score), `entity_mentions`(sentence_id, span, player_id|team_id, mention_type), `play_features`(뉴스가치 모델 입력 행렬), `play_mentioned`(정답 라벨).

## 5. 수집기(crawler) 요구사항

- 입력: 시즌 목록, game_type 목록. 기본 2019~2026, R.
- schedule → `Final`/`Completed Early`만 → gamePk 집합 → 경기당 4요청(feed, content.en, content.es, winprob).
- 초당 3~4요청 상한, 지수 백오프 재시도, `manifest`로 resume. 원본은 받은 그대로 gzip 저장(정규화는 별도 단계).
- 실행은 JiHoon 로컬 터미널(Cowork 셸은 statsapi 차단). 진행 로그를 파일로 남겨 Cowork에서 확인.
- 정규화 단계(`build_tables`)는 raw만 읽으므로 Cowork VM에서 실행 가능.

## 6. 정규화 단계에서 단위 테스트로 확인할 것

1. `outs_before`/`base_state_before` 유도가 하프이닝 경계와 타석 도중 주자 아웃(도루 실패로 3아웃, 다음 이닝 같은 타자 재등장) 케이스에서 맞는가.
2. `playEvents[].count`가 이벤트 **후** 카운트라는 해석이 첫 투구·인플레이 투구에서 일관되는가 (표본 HR: 첫 투구 후 1-0, 인플레이 투구 후 3-1 유지 — 확인됨).
3. `highlights.play_id`가 `pitches.play_id`에 100% 조인되는가 (표본 13/13 — 확인됨). 조인 실패분은 로그.
4. 더블헤더(`double_header`="Y"/"S", `game_number`)와 서스펜디드 경기(`status_detailed`, resume 날짜)의 `official_date` 처리.
5. schedule의 Postponed 항목이 같은 `game_pk`로 뒤 날짜에 Final로 재등장하는지 — 재등장하면 중복 제거, 새 pk면 그대로.
6. `articles.n_paragraphs`와 `bodyParagraphCount` 태그 일치 여부(정제 규칙 검증).

## 7. 열어 둔 결정

- 패키지·레포 이름 (예: `mlbcorpus`).
- 포스트시즌 포함 여부(수집은 하고 분석 기본값은 R로 두는 것을 제안).
- 2015~2018 플레이 데이터를 뉴스가치 모델의 베이스라인(사건 확률) 추정에 추가할지 — 필요해지면 그때.
- 스페인어 리캡이 번역인지 별도 집필인지: 표본은 번역으로 보이나 기자별로 다를 수 있음. 정렬 실험 전에 몇 편 대조.
