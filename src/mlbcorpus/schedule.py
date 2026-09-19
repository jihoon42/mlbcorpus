"""schedule 응답 → 경기 목록.

판정 규칙 (docs/01-statsapi-findings.md §5):
- 종료 경기 = status.codedGameState == "F" (Final, Completed Early 포함).
  "O"(Game Over)는 마지막 아웃 직후 기록 확정 전의 과도 상태라 다음 실행에서 받는다.
- Postponed/Cancelled 는 abstractGameState 가 "Final" 이어도 종료 경기가 아니다.
- 순연된 경기는 같은 gamePk 로 다른 날짜에 다시 나타날 수 있다. gamePk 로 중복을 제거하되
  종료된 쪽을 우선한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

FINISHED_CODED_STATES = frozenset({"F"})
FINISHED_DETAILED_STATES = frozenset({"Final", "Completed Early"})
NOT_PLAYED_DETAILED_STATES = frozenset({"Postponed", "Cancelled"})


@dataclass(frozen=True)
class GameRow:
    game_pk: int
    season: int
    game_type: str
    official_date: str
    status_detailed: str
    status_code: str
    finished: bool
    home_team_id: int | None
    away_team_id: int | None
    double_header: str | None
    game_number: int | None


def is_finished(status: dict[str, Any]) -> bool:
    detailed = status.get("detailedState", "")
    if detailed in NOT_PLAYED_DETAILED_STATES:
        return False
    return status.get("codedGameState") in FINISHED_CODED_STATES or detailed in FINISHED_DETAILED_STATES


def parse_schedule(doc: dict[str, Any]) -> list[GameRow]:
    """dates[].games[] 를 GameRow 로. 같은 gamePk 가 여러 날짜에 있으면 종료된 항목을 남긴다."""
    rows: dict[int, GameRow] = {}
    for date in doc.get("dates", []):
        for game in date.get("games", []):
            row = _row_from_game(game)
            prev = rows.get(row.game_pk)
            if prev is None or (row.finished and not prev.finished):
                rows[row.game_pk] = row
            elif row.finished and prev.finished and row.official_date > prev.official_date:
                # 서스펜디드 경기가 재개된 날짜의 항목이 최종 상태
                rows[row.game_pk] = row
    return sorted(rows.values(), key=lambda r: (r.official_date, r.game_pk))


def _row_from_game(game: dict[str, Any]) -> GameRow:
    status = game.get("status", {})
    teams = game.get("teams", {})
    return GameRow(
        game_pk=int(game["gamePk"]),
        season=int(game["season"]),
        game_type=str(game["gameType"]),
        official_date=str(game["officialDate"]),
        status_detailed=str(status.get("detailedState", "")),
        status_code=str(status.get("codedGameState", "")),
        finished=is_finished(status),
        home_team_id=_team_id(teams.get("home")),
        away_team_id=_team_id(teams.get("away")),
        double_header=game.get("doubleHeader"),
        game_number=game.get("gameNumber"),
    )


def _team_id(side: dict[str, Any] | None) -> int | None:
    if not side:
        return None
    team = side.get("team") or {}
    return int(team["id"]) if "id" in team else None


def summarize(rows: Iterable[GameRow]) -> dict[str, int]:
    """상태별 건수. status 명령과 로그용."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status_detailed] = counts.get(row.status_detailed, 0) + 1
    return dict(sorted(counts.items()))
