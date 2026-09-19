"""`mlbcorpus` 명령.

    mlbcorpus sample --pk 824464          경기 하나 받아서 요약 (연결·형식 확인)
    mlbcorpus crawl                        기본 범위(2019~2026, R+포스트시즌) 수집, 재실행하면 이어서
    mlbcorpus crawl --seasons 2025 --game-types R --limit 20
    mlbcorpus status                       manifest 집계
    mlbcorpus meta                         코드표(eventTypes 등) 저장
    mlbcorpus dissect --pk 824464          경기 하나의 세 register 정렬 보고서 → docs/dissect/824464.md
    mlbcorpus build-tables                 원본 → 정규화 테이블 (미구현)

모든 명령은 --data-dir (기본 ./data) 를 받는다. 로그는 stderr 와 data/crawl.log 둘 다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__, crawl as crawl_mod
from .config import DEFAULT_GAME_TYPES, DEFAULT_SEASONS, Settings
from .manifest import Manifest

DEFAULT_META_KINDS = (
    "eventTypes", "pitchTypes", "pitchCodes", "gameStatus", "gameTypes",
    "hitTrajectories", "situationCodes", "positions", "reviewReasons", "languages",
)


def parse_seasons(text: str) -> tuple[int, ...]:
    """'2019-2026' 또는 '2023,2025' 또는 둘의 혼합."""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    if not out:
        raise argparse.ArgumentTypeError("빈 시즌 목록")
    return tuple(sorted(set(out)))


def parse_csv(text: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in text.split(",") if p.strip())


def setup_logging(settings: Settings, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):  # main() 을 여러 번 불러도 핸들러가 겹치지 않게
        root.removeHandler(handler)
        handler.close()
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mlbcorpus", description="MLB Stats API 야구 텍스트 코퍼스 수집기")
    parser.add_argument("--version", action="version", version=f"mlbcorpus {__version__}")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="데이터 루트 (기본 ./data)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("crawl", help="schedule → 경기별 feed/content/winProbability 수집 (resume 가능)")
    p.add_argument("--seasons", type=parse_seasons, default=DEFAULT_SEASONS, help="예: 2019-2026 또는 2023,2025")
    p.add_argument("--game-types", type=parse_csv, default=DEFAULT_GAME_TYPES, help="예: R 또는 R,F,D,L,W")
    p.add_argument("--languages", type=parse_csv, default=None, help="content 언어 (기본 en,es)")
    p.add_argument("--rps", type=float, default=None, help="초당 요청 수 (기본 3)")
    p.add_argument("--concurrency", type=int, default=None, help="동시 경기 수 (기본 4)")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 처리할 최대 경기 수")
    p.add_argument("--force", action="store_true", help="이미 받은 리소스도 다시 받는다")
    p.add_argument("--no-refresh-schedule", action="store_true", help="schedule 을 다시 받지 않고 manifest 만으로 진행")

    p = sub.add_parser("status", help="manifest 집계")
    p.add_argument("--languages", type=parse_csv, default=None)
    p.add_argument("--errors", type=int, default=10, help="최근 실패 몇 건을 보여줄지")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sample", help="경기 하나를 받아 캐시하고 요약을 출력")
    p.add_argument("--pk", type=int, required=True, help="gamePk (예: 824464)")
    p.add_argument("--languages", type=parse_csv, default=None)

    p = sub.add_parser("meta", help="코드표 저장 (data/raw/meta/*.json.gz)")
    p.add_argument("kinds", nargs="*", default=list(DEFAULT_META_KINDS))

    p = sub.add_parser("dissect", help="캐시된 경기 하나의 세 register(기록 문장·캡션·리캡)를 타석 단위로 정렬한 Markdown 보고서")
    p.add_argument("--pk", type=int, required=True, help="gamePk (crawl 또는 sample 로 받아 둔 경기)")
    p.add_argument("--out", type=Path, default=None, help="출력 파일 (기본 docs/dissect/{pk}.md)")
    p.add_argument("--json", action="store_true", help="Markdown 대신 정렬 결과를 JSON 으로 stdout 에")
    p.add_argument("--languages", type=parse_csv, default=None)

    sub.add_parser("build-tables", help="원본 JSON → 정규화 테이블 (docs/02-schema.md). 아직 미구현")
    return parser


def make_settings(args: argparse.Namespace) -> Settings:
    settings = Settings(data_dir=args.data_dir)
    overrides: dict[str, object] = {}
    if getattr(args, "languages", None):
        overrides["languages"] = args.languages
    if getattr(args, "rps", None):
        overrides["requests_per_second"] = args.rps
    if getattr(args, "concurrency", None):
        overrides["concurrency"] = args.concurrency
    return replace(settings, **overrides) if overrides else settings


def cmd_crawl(args: argparse.Namespace, settings: Settings) -> int:
    stats = asyncio.run(
        crawl_mod.crawl(
            settings,
            seasons=args.seasons,
            game_types=args.game_types,
            force=args.force,
            limit=args.limit,
            refresh_schedule=not args.no_refresh_schedule,
        )
    )
    print(json.dumps(stats.__dict__, ensure_ascii=False, indent=2))
    return 0 if stats.fetched_failed == 0 else 1


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.manifest_path.exists():
        print(f"manifest 없음: {settings.manifest_path} (아직 crawl 을 실행하지 않았습니다)")
        return 1
    with Manifest(settings.manifest_path) as manifest:
        summary = manifest.summary(settings.resource_names())
        errors = manifest.recent_errors(args.errors)
    if args.json:
        print(json.dumps({**summary, "recent_errors": errors}, ensure_ascii=False, indent=2))
        return 0
    print(f"manifest: {settings.manifest_path}")
    print(f"경기 상태별: {summary['games_by_status']}")
    print(f"종료 경기 {summary['finished_games']}개 중 4개 리소스 모두 확보 {summary['complete_games']}개")
    print(f"리소스별 성공: {summary['per_resource_ok']}")
    print(f"실패 {summary['failed_fetches']}건, 저장 {summary['stored_bytes'] / 1e6:.1f} MB (gzip)")
    for row in summary["finished_by_season"]:
        print(f"  {row['season']} {row['game_type']}: {row['finished']}")
    if errors:
        print("최근 실패:")
        for game_pk, resource, at, error in errors:
            print(f"  {at} {game_pk} {resource}: {error}")
    return 0


def cmd_sample(args: argparse.Namespace, settings: Settings) -> int:
    season, stats = asyncio.run(crawl_mod.fetch_one_game(settings, args.pk))
    summary = crawl_mod.inspect_game(settings, season, args.pk)
    summary["fetch"] = {"ok": stats.fetched_ok, "failed": stats.fetched_failed, "bytes_gz": stats.bytes_stored}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if stats.fetched_failed == 0 else 1


def cmd_meta(args: argparse.Namespace, settings: Settings) -> int:
    counts = asyncio.run(crawl_mod.fetch_meta(settings, args.kinds))
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


def cmd_dissect(args: argparse.Namespace, settings: Settings) -> int:
    from . import dissect as dissect_mod
    from .dissect_md import render

    d = dissect_mod.load_dissection(settings, args.pk)
    if args.json:
        print(json.dumps(dissect_mod.to_jsonable(d), ensure_ascii=False, indent=2))
        return 0
    out = args.out or Path("docs") / "dissect" / f"{args.pk}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(d), encoding="utf-8")
    rec = d.recap_en
    mentioned = sum(1 for p in d.plays if p.mentioned)
    print(
        f"{out}: {len(d.plays)} plays, {d.n_pitches} pitches, {d.n_highlights_with_play_id}/{d.n_highlights} highlights on plays, "
        f"recap {'yes' if rec else 'no'}" + (f" ({len(rec.sentences)} sentences, {mentioned} plays mentioned)" if rec else "")
    )
    return 0


def cmd_build_tables(args: argparse.Namespace, settings: Settings) -> int:
    from .normalize import build_tables

    try:
        build_tables(settings)
    except NotImplementedError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


COMMANDS = {
    "crawl": cmd_crawl,
    "status": cmd_status,
    "sample": cmd_sample,
    "meta": cmd_meta,
    "dissect": cmd_dissect,
    "build-tables": cmd_build_tables,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = make_settings(args)
    setup_logging(settings, args.verbose)
    try:
        return COMMANDS[args.command](args, settings)
    except KeyboardInterrupt:
        logging.getLogger(__name__).warning("interrupted — 다시 실행하면 manifest 기준으로 이어서 받습니다")
        return 130


if __name__ == "__main__":
    sys.exit(main())
