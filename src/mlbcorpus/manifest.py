"""수집 상태 SQLite. resume 는 이 파일만 본다.

테이블
    games    schedule 에서 본 모든 경기 (미종료 포함). finished=1 인 경기만 수집 대상.
    fetches  (game_pk, resource) 별 성공 여부·크기·시각·오류.

Parquet 대신 SQLite 인 이유: 경기 하나 끝날 때마다 한 행씩 갱신해야 하는데
Parquet 은 파일 전체를 다시 써야 한다. 표준 라이브러리만으로 충분하다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .schedule import GameRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_pk         INTEGER PRIMARY KEY,
    season          INTEGER NOT NULL,
    game_type       TEXT    NOT NULL,
    official_date   TEXT    NOT NULL,
    status_detailed TEXT    NOT NULL,
    status_code     TEXT    NOT NULL,
    finished        INTEGER NOT NULL,
    home_team_id    INTEGER,
    away_team_id    INTEGER,
    double_header   TEXT,
    game_number     INTEGER,
    seen_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_season_type ON games(season, game_type);

CREATE TABLE IF NOT EXISTS fetches (
    game_pk     INTEGER NOT NULL,
    resource    TEXT    NOT NULL,
    ok          INTEGER NOT NULL,
    bytes       INTEGER,
    fetched_at  TEXT    NOT NULL,
    error       TEXT,
    PRIMARY KEY (game_pk, resource)
);
"""


@dataclass(frozen=True)
class PendingGame:
    game_pk: int
    season: int
    game_type: str
    missing: tuple[str, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- games ----
    def upsert_games(self, rows: Iterable[GameRow]) -> int:
        seen_at = _now()
        data = [
            (
                r.game_pk, r.season, r.game_type, r.official_date, r.status_detailed, r.status_code,
                int(r.finished), r.home_team_id, r.away_team_id, r.double_header, r.game_number, seen_at,
            )
            for r in rows
        ]
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO games (game_pk, season, game_type, official_date, status_detailed, status_code,
                                   finished, home_team_id, away_team_id, double_header, game_number, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_pk) DO UPDATE SET
                    season = excluded.season, game_type = excluded.game_type,
                    official_date = excluded.official_date, status_detailed = excluded.status_detailed,
                    status_code = excluded.status_code, finished = excluded.finished,
                    home_team_id = excluded.home_team_id, away_team_id = excluded.away_team_id,
                    double_header = excluded.double_header, game_number = excluded.game_number,
                    seen_at = excluded.seen_at
                """,
                data,
            )
        return len(data)

    # ---- fetches ----
    def mark(self, game_pk: int, resource: str, *, ok: bool, nbytes: int | None = None, error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO fetches (game_pk, resource, ok, bytes, fetched_at, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_pk, resource) DO UPDATE SET
                    ok = excluded.ok, bytes = excluded.bytes, fetched_at = excluded.fetched_at, error = excluded.error
                """,
                (game_pk, resource, int(ok), nbytes, _now(), error),
            )

    def pending(
        self,
        resources: Sequence[str],
        *,
        seasons: Sequence[int] | None = None,
        game_types: Sequence[str] | None = None,
        force: bool = False,
    ) -> list[PendingGame]:
        """종료 경기 중 아직 못 받은 리소스가 있는 것. force=True 면 전부 다시."""
        query = "SELECT game_pk, season, game_type FROM games WHERE finished = 1"
        params: list[object] = []
        if seasons:
            query += f" AND season IN ({','.join('?' * len(seasons))})"
            params.extend(seasons)
        if game_types:
            query += f" AND game_type IN ({','.join('?' * len(game_types))})"
            params.extend(game_types)
        query += " ORDER BY season, official_date, game_pk"
        games = self.conn.execute(query, params).fetchall()

        done: dict[int, set[str]] = {}
        if not force:
            for game_pk, resource in self.conn.execute("SELECT game_pk, resource FROM fetches WHERE ok = 1"):
                done.setdefault(game_pk, set()).add(resource)

        result: list[PendingGame] = []
        for game_pk, season, game_type in games:
            missing = tuple(r for r in resources if r not in done.get(game_pk, set()))
            if missing:
                result.append(PendingGame(game_pk, season, game_type, missing))
        return result

    def summary(self, resources: Sequence[str]) -> dict[str, object]:
        """status 명령용 집계."""
        by_status = dict(
            self.conn.execute(
                "SELECT status_detailed, COUNT(*) FROM games GROUP BY status_detailed ORDER BY status_detailed"
            ).fetchall()
        )
        finished = self.conn.execute("SELECT COUNT(*) FROM games WHERE finished = 1").fetchone()[0]
        complete = self.conn.execute(
            """
            SELECT COUNT(*) FROM games g
            WHERE g.finished = 1 AND (
                SELECT COUNT(*) FROM fetches f
                WHERE f.game_pk = g.game_pk AND f.ok = 1 AND f.resource IN ({})
            ) = ?
            """.format(",".join("?" * len(resources))),
            (*resources, len(resources)),
        ).fetchone()[0]
        per_resource = {
            resource: ok_count
            for resource, ok_count in self.conn.execute(
                "SELECT resource, SUM(ok) FROM fetches GROUP BY resource ORDER BY resource"
            ).fetchall()
        }
        errors = self.conn.execute("SELECT COUNT(*) FROM fetches WHERE ok = 0").fetchone()[0]
        by_season = [
            {"season": season, "game_type": game_type, "finished": n}
            for season, game_type, n in self.conn.execute(
                "SELECT season, game_type, COUNT(*) FROM games WHERE finished = 1 "
                "GROUP BY season, game_type ORDER BY season, game_type"
            ).fetchall()
        ]
        total_bytes = self.conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM fetches WHERE ok = 1").fetchone()[0]
        return {
            "games_by_status": by_status,
            "finished_games": finished,
            "complete_games": complete,
            "per_resource_ok": per_resource,
            "failed_fetches": errors,
            "stored_bytes": total_bytes,
            "finished_by_season": by_season,
        }

    def recent_errors(self, limit: int = 20) -> list[tuple[int, str, str, str]]:
        return self.conn.execute(
            "SELECT game_pk, resource, fetched_at, error FROM fetches WHERE ok = 0 ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
