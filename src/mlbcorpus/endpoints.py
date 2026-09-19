"""Stats API URL 조립.

인증·API 키 없음. 공식 문서(docs.statsapi.mlb.com)는 로그인이 걸려 있으므로
엔드포인트·파라미터의 근거는 toddrob99/MLB-StatsAPI 의 statsapi/endpoints.py 와
docs/01-statsapi-findings.md 의 실측이다.
"""

from __future__ import annotations

from urllib.parse import urlencode

from .config import BASE_URL, SPORT_ID_MLB


def _url(path: str, params: dict[str, object] | None = None) -> str:
    url = f"{BASE_URL}/{path}"
    if params:
        query = {k: v for k, v in params.items() if v is not None}
        if query:
            url += "?" + urlencode(query)
    return url


def schedule(
    season: int,
    game_type: str,
    *,
    sport_id: int = SPORT_ID_MLB,
    hydrate: str | None = None,
    fields: str | None = None,
) -> str:
    """시즌·게임 타입 하나의 전체 일정. 응답의 dates[].games[] 에 gamePk 가 있다."""
    return _url(
        "v1/schedule",
        {"sportId": sport_id, "season": season, "gameType": game_type, "hydrate": hydrate, "fields": fields},
    )


def schedule_by_date(
    date: str,
    *,
    sport_id: int = SPORT_ID_MLB,
    hydrate: str | None = None,
    language: str | None = None,
) -> str:
    """하루치 일정. hydrate=game(content(editorial(recap))) 로 리캡을 한 번에 받을 때 쓴다."""
    return _url(
        "v1/schedule",
        {"sportId": sport_id, "date": date, "hydrate": hydrate, "language": language},
    )


def feed_live(game_pk: int) -> str:
    """경기 메타 + 플레이·투구 + 박스스코어 + 라인스코어 (v1.1)."""
    return _url(f"v1.1/game/{game_pk}/feed/live")


def content(game_pk: int, language: str = "en", *, highlight_limit: int | None = None) -> str:
    """리캡 기사·하이라이트 캡션·영상 메타. 영어는 기본값이라 language 파라미터를 붙이지 않는다."""
    return _url(
        f"v1/game/{game_pk}/content",
        {"language": None if language == "en" else language, "highlightLimit": highlight_limit},
    )


def win_probability(game_pk: int) -> str:
    """플레이별 승리확률·WPA·레버리지 (allPlays 전체를 다시 포함한다)."""
    return _url(f"v1/game/{game_pk}/winProbability")


def meta(kind: str) -> str:
    """코드표. kind: eventTypes, pitchTypes, pitchCodes, gameStatus, gameTypes,
    hitTrajectories, situationCodes, positions, reviewReasons, languages ..."""
    return _url(f"v1/{kind}")
