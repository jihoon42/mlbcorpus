"""원본 JSON → 정규화 테이블 (docs/02-schema.md §1).

계획된 모듈 (원본 수집이 끝나면 실제 데이터로 검증하며 채운다):
    games.py             games, linescore, boxscore_notes, teams
    plays.py             plays (outs_before / base_state_before / score_before 유도 포함)
    pitches.py           pitches, play_events, runners
    boxscore.py          boxscore_players, players
    articles.py          articles (body_html → body_text 정제, docs/02 §2), highlights
    winprob.py           plays 에 home_wp_before/after, home_wpa, leverage_index 병합

출력은 data/tables/*.parquet. 입력은 data/raw 만 읽으므로 네트워크가 없어도 실행된다.
"""

from __future__ import annotations

from ..config import Settings


def build_tables(settings: Settings) -> None:
    raise NotImplementedError(
        "build-tables 는 아직 구현되지 않았습니다. 원본 수집(crawl) 후 docs/02-schema.md §1 순서대로 채웁니다."
    )
