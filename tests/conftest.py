"""테스트 공용 fixture. 실제 API 응답의 구조를 최소한으로 흉내 낸다 (docs/01 §2~4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mlbcorpus.config import Settings

BASE = "https://statsapi.mlb.com/api"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        seasons=(2026,),
        game_types=("R",),
        languages=("en", "es"),
        requests_per_second=0,  # 테스트에서는 속도 제한 없음
        concurrency=2,
        max_retries=2,
        backoff_base_seconds=0.001,
        backoff_max_seconds=0.002,
    )


def schedule_game(
    pk: int,
    date: str,
    *,
    detailed: str = "Final",
    coded: str = "F",
    season: int = 2026,
    game_type: str = "R",
    home: int = 113,
    away: int = 119,
) -> dict[str, Any]:
    return {
        "gamePk": pk,
        "gameType": game_type,
        "season": str(season),
        "officialDate": date,
        "status": {"abstractGameState": "Final" if coded in "FDC" else "Preview", "codedGameState": coded, "detailedState": detailed},
        "teams": {"home": {"team": {"id": home}}, "away": {"team": {"id": away}}},
        "doubleHeader": "N",
        "gameNumber": 1,
    }


def schedule_doc(*days: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"totalGames": sum(len(g) for _, g in days), "dates": [{"date": d, "games": g} for d, g in days]}


def feed_doc(pk: int, *, season: int = 2026, game_type: str = "R", n_plays: int = 3) -> dict[str, Any]:
    plays = []
    for i in range(n_plays):
        plays.append(
            {
                "atBatIndex": i,
                "result": {"description": f"Play {i}.", "eventType": "field_out", "homeScore": 0, "awayScore": 0},
                "about": {"atBatIndex": i, "inning": 1, "halfInning": "top", "captivatingIndex": 5},
                "playEvents": [
                    {"index": 0, "isPitch": True, "playId": f"pid-{pk}-{i}-0", "pitchNumber": 1},
                    {"index": 1, "isPitch": False, "playId": f"pid-{pk}-{i}-1"},
                ],
            }
        )
    return {
        "gamePk": pk,
        "gameData": {
            "game": {"pk": pk, "season": str(season), "type": game_type, "doubleHeader": "N", "gameNumber": 1},
            "datetime": {"officialDate": "2026-09-17"},
            "status": {"codedGameState": "F", "detailedState": "Final"},
            "teams": {"home": {"id": 113, "abbreviation": "CIN"}, "away": {"id": 119, "abbreviation": "LAD"}},
        },
        "liveData": {
            "plays": {"allPlays": plays},
            "linescore": {"teams": {"home": {"runs": 2}, "away": {"runs": 8}}},
        },
    }


def content_doc(pk: int, lang: str = "en") -> dict[str, Any]:
    return {
        "editorial": {
            "recap": {
                "mlb": {
                    "headline": f"Recap {pk} ({lang})",
                    "body": "<p>Body.</p>" * 3,
                    "contributors": [{"name": "Writer"}],
                }
            }
        },
        "highlights": {"highlights": {"items": [{"guid": f"pid-{pk}-0-0", "description": "HR"}, {"description": "no guid"}]}},
    }


def winprob_doc(n: int = 3) -> list[dict[str, Any]]:
    return [{"atBatIndex": i, "homeTeamWinProbability": 50.0, "homeTeamWinProbabilityAdded": float(i)} for i in range(n)]
