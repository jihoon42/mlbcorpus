"""설정. 값의 근거는 docs/01-statsapi-findings.md, docs/02-schema.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://statsapi.mlb.com/api"
SPORT_ID_MLB = 1

# gameType 코드 (meta/gameTypes). R 정규시즌, F 와일드카드, D 디비전시리즈,
# L 리그챔피언십, W 월드시리즈. S(스프링캠프)·A(올스타)·E(시범)는 받지 않는다.
REGULAR_SEASON: tuple[str, ...] = ("R",)
POSTSEASON: tuple[str, ...] = ("F", "D", "L", "W")
DEFAULT_GAME_TYPES: tuple[str, ...] = REGULAR_SEASON + POSTSEASON

# 리캡·하이라이트가 존재하는 범위 (2019 개막일부터). 플레이 데이터만 필요하면
# --seasons 로 2015 등을 지정해도 된다.
DEFAULT_SEASONS: tuple[int, ...] = tuple(range(2019, 2027))

# content 엔드포인트의 언어. "en" 은 파라미터 없이 기본값, 그 외는 ?language=xx
DEFAULT_LANGUAGES: tuple[str, ...] = ("en", "es")

# 경기당 받는 리소스 이름. manifest.fetches.resource 의 값이기도 하다.
RESOURCE_FEED = "feed"
RESOURCE_WINPROB = "winprob"


def content_resource(language: str) -> str:
    return f"content.{language}"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    seasons: tuple[int, ...] = DEFAULT_SEASONS
    game_types: tuple[str, ...] = DEFAULT_GAME_TYPES
    languages: tuple[str, ...] = DEFAULT_LANGUAGES
    requests_per_second: float = 3.0
    concurrency: int = 4
    timeout_seconds: float = 30.0
    max_retries: int = 5
    backoff_base_seconds: float = 2.0  # 재시도 대기: base**attempt (+지터), backoff_max 로 상한
    backoff_max_seconds: float = 60.0
    user_agent: str = "mlbcorpus/0.1 (academic research; Hongik Univ. course project)"

    # ---- 경로 규약 (docs/02-schema.md §0) ----
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def schedule_dir(self) -> Path:
        return self.raw_dir / "schedule"

    @property
    def games_dir(self) -> Path:
        return self.raw_dir / "games"

    @property
    def meta_dir(self) -> Path:
        return self.raw_dir / "meta"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "manifest.sqlite"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "crawl.log"

    @property
    def tables_dir(self) -> Path:
        return self.data_dir / "tables"

    def game_dir(self, season: int, game_pk: int) -> Path:
        return self.games_dir / str(season) / str(game_pk)

    def resource_names(self) -> tuple[str, ...]:
        """경기 하나가 '완료'로 간주되기 위해 필요한 리소스 목록."""
        return (RESOURCE_FEED, *(content_resource(lang) for lang in self.languages), RESOURCE_WINPROB)

    def resource_path(self, season: int, game_pk: int, resource: str) -> Path:
        return self.game_dir(season, game_pk) / f"{resource}.json.gz"
