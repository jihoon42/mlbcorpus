"""수집 루프: schedule → 종료 경기 → 경기별 리소스(feed, content.*, winprob).

resume: manifest.fetches 에 ok=1 인 리소스는 건너뛴다. 중간에 끊겨도 다시 실행하면 이어진다.
저장: 원본 바이트를 data/raw/games/{season}/{game_pk}/{resource}.json.gz 에 그대로.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import endpoints
from .config import RESOURCE_FEED, RESOURCE_WINPROB, Settings
from .fetch import FetchError, Fetcher, NotFound
from .manifest import Manifest, PendingGame
from .schedule import GameRow, parse_schedule, summarize
from .storage import read_gz_json, write_gz_atomic

log = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    schedules_fetched: int = 0
    games_seen: int = 0
    games_finished: int = 0
    games_pending: int = 0
    fetched_ok: int = 0
    fetched_failed: int = 0
    bytes_stored: int = 0
    seconds: float = 0.0
    status_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------- resources


def resource_url(resource: str, game_pk: int) -> str:
    if resource == RESOURCE_FEED:
        return endpoints.feed_live(game_pk)
    if resource == RESOURCE_WINPROB:
        return endpoints.win_probability(game_pk)
    if resource.startswith("content."):
        return endpoints.content(game_pk, resource.split(".", 1)[1])
    raise ValueError(f"unknown resource {resource!r}")


def validate_resource(resource: str, game_pk: int, data: Any) -> str | None:
    """응답이 기대한 모양인지 가볍게 확인. 문제면 사유 문자열, 정상이면 None."""
    if resource == RESOURCE_FEED:
        if not isinstance(data, dict) or data.get("gamePk") != game_pk:
            return "feed: gamePk mismatch or not an object"
        if "liveData" not in data or "gameData" not in data:
            return "feed: missing liveData/gameData"
        return None
    if resource == RESOURCE_WINPROB:
        if not isinstance(data, list):
            return "winprob: expected a list of plays"
        return None
    if resource.startswith("content."):
        if not isinstance(data, dict) or "editorial" not in data:
            return "content: missing editorial"
        return None
    return f"unknown resource {resource!r}"


# ---------------------------------------------------------------- schedules


async def fetch_schedules(
    settings: Settings,
    fetcher: Fetcher,
    manifest: Manifest,
    seasons: Sequence[int],
    game_types: Sequence[str],
) -> list[GameRow]:
    """시즌×게임타입별 schedule 을 받아 캐시하고 manifest.games 를 갱신한다."""
    rows: list[GameRow] = []
    for season in seasons:
        for game_type in game_types:
            url = endpoints.schedule(season, game_type)
            result = await fetcher.get_json_bytes(url)
            write_gz_atomic(settings.schedule_dir / f"{season}_{game_type}.json.gz", result.content)
            parsed = parse_schedule(result.data)
            manifest.upsert_games(parsed)
            rows.extend(parsed)
            log.info(
                "schedule %d %s: %d games %s",
                season, game_type, len(parsed), summarize(parsed),
            )
    return rows


# ---------------------------------------------------------------- games


async def fetch_game_resources(
    settings: Settings,
    fetcher: Fetcher,
    manifest: Manifest,
    item: PendingGame,
    stats: CrawlStats,
) -> None:
    for resource in item.missing:
        url = resource_url(resource, item.game_pk)
        try:
            result = await fetcher.get_json_bytes(url)
        except NotFound as exc:
            manifest.mark(item.game_pk, resource, ok=False, error=str(exc))
            stats.fetched_failed += 1
            log.warning("404 game %d %s", item.game_pk, resource)
            continue
        except FetchError as exc:
            manifest.mark(item.game_pk, resource, ok=False, error=str(exc))
            stats.fetched_failed += 1
            log.error("failed game %d %s: %s", item.game_pk, resource, exc)
            continue
        except Exception as exc:  # 예상 못 한 오류로 전체 수집이 죽지 않게
            manifest.mark(item.game_pk, resource, ok=False, error=f"{type(exc).__name__}: {exc}")
            stats.fetched_failed += 1
            log.exception("unexpected error game %d %s", item.game_pk, resource)
            continue

        problem = validate_resource(resource, item.game_pk, result.data)
        if problem:
            manifest.mark(item.game_pk, resource, ok=False, error=problem)
            stats.fetched_failed += 1
            log.error("invalid game %d %s: %s", item.game_pk, resource, problem)
            continue

        nbytes = write_gz_atomic(settings.resource_path(item.season, item.game_pk, resource), result.content)
        manifest.mark(item.game_pk, resource, ok=True, nbytes=nbytes)
        stats.fetched_ok += 1
        stats.bytes_stored += nbytes


async def crawl_games(
    settings: Settings,
    fetcher: Fetcher,
    manifest: Manifest,
    pending: Sequence[PendingGame],
    stats: CrawlStats,
    *,
    progress_every: int = 50,
) -> None:
    queue: asyncio.Queue[PendingGame] = asyncio.Queue()
    for item in pending:
        queue.put_nowait(item)
    total = len(pending)
    done = 0
    started = time.monotonic()

    async def worker() -> None:
        nonlocal done
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await fetch_game_resources(settings, fetcher, manifest, item, stats)
            done += 1
            if done % progress_every == 0 or done == total:
                elapsed = time.monotonic() - started
                rate = done / elapsed if elapsed > 0 else 0.0
                remaining = (total - done) / rate if rate > 0 else float("inf")
                log.info(
                    "games %d/%d  ok=%d failed=%d  %.1f MB  %.2f games/s  ETA %s",
                    done, total, stats.fetched_ok, stats.fetched_failed,
                    stats.bytes_stored / 1e6, rate, _fmt_seconds(remaining),
                )

    workers = [asyncio.create_task(worker()) for _ in range(max(1, settings.concurrency))]
    await asyncio.gather(*workers)


def _fmt_seconds(seconds: float) -> str:
    if seconds == float("inf"):
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------- entry points


async def crawl(
    settings: Settings,
    *,
    seasons: Sequence[int] | None = None,
    game_types: Sequence[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    refresh_schedule: bool = True,
) -> CrawlStats:
    seasons = tuple(seasons or settings.seasons)
    game_types = tuple(game_types or settings.game_types)
    resources = settings.resource_names()
    stats = CrawlStats()
    started = time.monotonic()

    with Manifest(settings.manifest_path) as manifest:
        async with Fetcher(settings) as fetcher:
            if refresh_schedule:
                rows = await fetch_schedules(settings, fetcher, manifest, seasons, game_types)
                stats.schedules_fetched = len(seasons) * len(game_types)
                stats.games_seen = len(rows)
                stats.games_finished = sum(r.finished for r in rows)
                stats.status_counts = summarize(rows)

            pending = manifest.pending(resources, seasons=seasons, game_types=game_types, force=force)
            if limit is not None:
                pending = pending[:limit]
            stats.games_pending = len(pending)
            log.info(
                "pending %d games x up to %d resources (force=%s, rps=%.1f, concurrency=%d)",
                len(pending), len(resources), force, settings.requests_per_second, settings.concurrency,
            )
            if pending:
                await crawl_games(settings, fetcher, manifest, pending, stats)

    stats.seconds = time.monotonic() - started
    log.info(
        "done in %s: ok=%d failed=%d stored=%.1f MB",
        _fmt_seconds(stats.seconds), stats.fetched_ok, stats.fetched_failed, stats.bytes_stored / 1e6,
    )
    return stats


async def fetch_meta(settings: Settings, kinds: Sequence[str]) -> dict[str, int]:
    """코드표를 data/raw/meta/{kind}.json.gz 로. 반환값은 kind → 항목 수."""
    counts: dict[str, int] = {}
    async with Fetcher(settings) as fetcher:
        for kind in kinds:
            result = await fetcher.get_json_bytes(endpoints.meta(kind))
            write_gz_atomic(settings.meta_dir / f"{kind}.json.gz", result.content)
            counts[kind] = len(result.data) if isinstance(result.data, list) else 1
            log.info("meta %s: %d entries", kind, counts[kind])
    return counts


async def fetch_one_game(settings: Settings, game_pk: int, *, force: bool = True) -> tuple[int, CrawlStats]:
    """경기 하나를 캐시에 넣는다 (연결·형식 확인용). 시즌은 feed 에서 읽는다. 반환값은 (season, stats)."""
    stats = CrawlStats()
    async with Fetcher(settings) as fetcher:
        feed = await fetcher.get_json_bytes(endpoints.feed_live(game_pk))
        problem = validate_resource(RESOURCE_FEED, game_pk, feed.data)
        if problem:
            raise FetchError(feed.url, problem)
        game = feed.data["gameData"]["game"]
        season = int(game["season"])
        with Manifest(settings.manifest_path) as manifest:
            manifest.upsert_games([_game_row_from_feed(feed.data)])
            nbytes = write_gz_atomic(settings.resource_path(season, game_pk, RESOURCE_FEED), feed.content)
            manifest.mark(game_pk, RESOURCE_FEED, ok=True, nbytes=nbytes)
            stats.fetched_ok += 1
            stats.bytes_stored += nbytes
            rest = tuple(r for r in settings.resource_names() if r != RESOURCE_FEED)
            item = PendingGame(game_pk, season, str(game["type"]), rest)
            await fetch_game_resources(settings, fetcher, manifest, item, stats)
    return season, stats


def _game_row_from_feed(feed: dict[str, Any]) -> GameRow:
    from .schedule import is_finished

    gd = feed["gameData"]
    status = gd.get("status", {})
    return GameRow(
        game_pk=int(feed["gamePk"]),
        season=int(gd["game"]["season"]),
        game_type=str(gd["game"]["type"]),
        official_date=str(gd["datetime"]["officialDate"]),
        status_detailed=str(status.get("detailedState", "")),
        status_code=str(status.get("codedGameState", "")),
        finished=is_finished(status),
        home_team_id=gd.get("teams", {}).get("home", {}).get("id"),
        away_team_id=gd.get("teams", {}).get("away", {}).get("id"),
        double_header=gd["game"].get("doubleHeader"),
        game_number=gd["game"].get("gameNumber"),
    )


def inspect_game(settings: Settings, season: int, game_pk: int) -> dict[str, Any]:
    """캐시된 경기 하나의 요약. docs/01 의 표본 수치와 대조하는 용도."""
    out: dict[str, Any] = {"game_pk": game_pk, "season": season}
    feed_path = settings.resource_path(season, game_pk, RESOURCE_FEED)
    if feed_path.exists():
        feed = read_gz_json(feed_path)
        gd, ld = feed["gameData"], feed["liveData"]
        plays = ld["plays"]["allPlays"]
        events = [e for p in plays for e in p.get("playEvents", [])]
        out.update(
            {
                "date": gd["datetime"]["officialDate"],
                "matchup": f'{gd["teams"]["away"]["abbreviation"]}@{gd["teams"]["home"]["abbreviation"]}',
                "status": gd["status"]["detailedState"],
                "score": f'{ld["linescore"]["teams"]["away"].get("runs")}-{ld["linescore"]["teams"]["home"].get("runs")}',
                "n_plays": len(plays),
                "n_pitches": sum(1 for e in events if e.get("isPitch")),
                "n_events": len(events),
                "n_play_ids": len({e["playId"] for e in events if e.get("playId")}),
            }
        )
    for lang in settings.languages:
        path = settings.resource_path(season, game_pk, f"content.{lang}")
        if not path.exists():
            continue
        content = read_gz_json(path)
        recap = ((content.get("editorial") or {}).get("recap") or {}).get("mlb") or {}
        items = ((content.get("highlights") or {}).get("highlights") or {}).get("items") or []
        out[f"recap_{lang}"] = {
            "headline": recap.get("headline"),
            "body_chars": len(recap.get("body") or ""),
            "authors": [c.get("name") for c in recap.get("contributors") or []],
        }
        out[f"highlights_{lang}"] = {
            "n": len(items),
            "n_with_play_id": sum(1 for h in items if h.get("guid")),
        }
    wp_path = settings.resource_path(season, game_pk, RESOURCE_WINPROB)
    if wp_path.exists():
        wp = read_gz_json(wp_path)
        out["winprob"] = {
            "n": len(wp),
            "max_abs_wpa_at_bat": max(wp, key=lambda p: abs(p.get("homeTeamWinProbabilityAdded") or 0)).get("atBatIndex")
            if wp
            else None,
        }
    return out
