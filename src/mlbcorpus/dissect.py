"""한 경기 분석(dissect): 캐시된 경기 하나에서 세 register 를 플레이 단위로 정렬한다.

- register 1  공식 기록 문장   feed/live  allPlays[].result.description
- register 2  하이라이트 캡션   content    highlights[].description  — playId 로 정확히 붙는다 (docs/01 §3)
- register 3  리캡 기사        content    editorial.recap.mlb.body  — 링크가 없으므로 휴리스틱 정렬:
              경기 로스터 이름 + 사건 키워드 (+ 이닝 서수 + 타점 수식어). "four-hit", "three perfect innings"
              같은 집계 주장은 플레이를 모아 대조한다. 근거는 그대로 드러내고, 정렬 실패도 관찰 대상으로 남긴다.

여기서 만든 문장 분리·이름 찾기·정렬 규칙은 docs/02-schema.md §4 의 파생 테이블
(article_sentences, entity_mentions, sentence_play_alignment) 의 첫 초안이다.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import RESOURCE_FEED, RESOURCE_WINPROB, Settings, content_resource
from .storage import read_gz_json

# ----------------------------------------------------------------------------- data


@dataclass(frozen=True)
class Player:
    id: int
    full_name: str
    last_name: str
    side: str  # "home" | "away"
    played: bool  # 타석에 섰거나 투구했음 (boxscore batters/pitchers)

    @property
    def ascii_full(self) -> str:
        return strip_accents(self.full_name)

    @property
    def ascii_last(self) -> str:
        return strip_accents(self.last_name)


@dataclass
class Caption:
    highlight_id: str
    title: str
    description: str
    play_id: str
    pitch_number: int | None
    is_last_pitch: bool


@dataclass
class Play:
    at_bat_index: int
    inning: int
    half: str  # "top" | "bottom"
    batter: Player
    pitcher: Player
    event: str
    event_type: str
    description: str
    rbi: int
    is_out: bool
    away_before: int
    home_before: int
    away_after: int
    home_after: int
    runs_scored: int
    captivating_index: int | None
    home_wp_before: float | None
    home_wp_after: float | None
    home_wpa: float | None
    leverage_index: float | None
    launch_speed: float | None
    hit_distance: float | None
    n_pitches: int
    play_ids: dict[str, int | None]  # playId -> pitchNumber (비투구 이벤트는 None)
    captions: list[Caption] = field(default_factory=list)
    sentence_ids: list[int] = field(default_factory=list)

    @property
    def batting_side(self) -> str:
        return "away" if self.half == "top" else "home"

    @property
    def wpa_batting(self) -> float | None:
        """공격팀 관점의 승리확률 변화(%p)."""
        if self.home_wpa is None:
            return None
        return self.home_wpa if self.batting_side == "home" else -self.home_wpa

    @property
    def is_hit(self) -> bool:
        return self.event_type in HIT_EVENTS

    @property
    def mentioned(self) -> bool:
        return bool(self.sentence_ids)


@dataclass
class Sentence:
    sid: int
    paragraph: int
    text: str
    kind: str = "context"  # quote | play | aggregate | context
    mentions: list[Player] = field(default_factory=list)
    plays: list[int] = field(default_factory=list)  # 문장이 가리키는 특정 타석 → 그 타석은 '언급됨'
    covered: list[int] = field(default_factory=list)  # 집계 주장이 포괄하는 타석 (퍼펙트 3이닝 등) → 언급으로 치지 않음
    verdict: str = ""  # "" | 확인 | 불일치 | 대응 없음
    evidence: str = ""


@dataclass
class Recap:
    language: str
    headline: str
    seo_title: str
    dateline: str
    authors: list[str]
    paragraphs: list[str]
    sentences: list[Sentence]
    body_chars: int
    n_quotes: int


@dataclass
class Dissection:
    game_pk: int
    season: int
    game_type: str
    official_date: str
    venue: str
    attendance: int | None
    duration_minutes: int | None
    away_abbr: str
    home_abbr: str
    away_name: str
    home_name: str
    away_score: int
    home_score: int
    plays: list[Play]
    n_pitches: int
    n_highlights: int
    n_highlights_with_play_id: int
    n_winprob: int
    recap_en: Recap | None
    recap_es: Recap | None
    players: dict[int, Player]
    box_batting: dict[int, dict[str, Any]]
    box_pitching: dict[int, dict[str, Any]]


HIT_EVENTS = frozenset({"single", "double", "triple", "home_run"})
# 완전한 이닝 판정에 쓰는 '주자 없이 아웃' 사건. 병살·희생타·야수선택은 주자가 있어야 하므로 제외.
CLEAN_OUT_EVENTS = frozenset({"field_out", "strikeout", "strike_out"})

# ----------------------------------------------------------------------------- text utils


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


_TAG_RE = re.compile(r"<(iframe|script|blockquote|style)\b.*?</\1\s*>", re.S | re.I)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?:)?//[^)]*\)")
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def clean_recap_html(body: str) -> tuple[str, list[str]]:
    """리캡 HTML → (데이트라인, 단락 목록). docs/02 §2 규칙.

    - iframe/script/blockquote 블록 제거 (영상·트윗 임베드)
    - <a>텍스트</a> → 텍스트, [텍스트](url) → 텍스트
    - <p> 경계와 단락 내부 \\n\\n 모두 단락 경계
    - '*' 로 시작하는 단락(관련 기사 링크 목록) 제거
    - 첫 단락의 "CINCINNATI -- " 는 데이트라인으로 분리
    """
    body = _TAG_RE.sub(" ", body)
    paragraphs: list[str] = []
    for chunk in re.split(r"</?p\b[^>]*>", body):
        for para in re.split(r"\n\s*\n", chunk):
            text = _MD_LINK_RE.sub(r"\1", para)
            text = _ANY_TAG_RE.sub("", text)
            text = text.replace("**", "")  # 스페인어판 등에 남는 마크다운 강조
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or text.startswith("*"):
                continue
            paragraphs.append(text)
    dateline = ""
    if paragraphs:
        m = re.match(r"^([A-Z][A-Z .'\-]{1,40}?) -- ", paragraphs[0])
        if m:
            dateline = m.group(1).strip()
            paragraphs[0] = paragraphs[0][m.end():]
    return dateline, paragraphs


_ABBREVIATIONS = ("No.", "Mr.", "Mrs.", "Ms.", "Dr.", "Jr.", "Sr.", "St.", "vs.", "L.A.", "N.L.", "A.L.", "U.S.", "D.C.")
_SENTENCE_SPLIT_RE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’)]))\s+(?=[\"“(]?[A-Z0-9])")


def split_sentences(paragraph: str) -> list[str]:
    protected = paragraph
    for ab in _ABBREVIATIONS:
        protected = protected.replace(ab, ab.replace(".", "\x00"))
    parts = [p.replace("\x00", ".").strip() for p in _SENTENCE_SPLIT_RE.split(protected)]
    return [p for p in parts if p]


_QUOTE_CHARS = "\"“”"


def sentences_with_quote_state(paragraphs: list[str]) -> list[Sentence]:
    """단락별로 문장을 나누고, 따옴표 안에 있는 문장을 quote 로 표시한다."""
    out: list[Sentence] = []
    sid = 0
    for pi, para in enumerate(paragraphs, start=1):
        inside = False
        for text in split_sentences(para):
            n_marks = sum(text.count(ch) for ch in _QUOTE_CHARS)
            is_quote = inside or n_marks > 0
            if n_marks % 2 == 1:
                inside = not inside
            sid += 1
            out.append(Sentence(sid=sid, paragraph=pi, text=text, kind="quote" if is_quote else "context"))
    return out


# ----------------------------------------------------------------------------- loading


def find_game_dir(settings: Settings, game_pk: int) -> Path:
    """data/raw/games/*/{pk} 를 찾는다. 시즌을 몰라도 되게."""
    for season_dir in sorted(settings.games_dir.glob("*")):
        candidate = season_dir / str(game_pk)
        if (candidate / f"{RESOURCE_FEED}.json.gz").exists():
            return candidate
    raise FileNotFoundError(f"cached game {game_pk} not found under {settings.games_dir}")


def _player_from_feed(entry: dict[str, Any], side: str, played: bool) -> Player:
    return Player(
        id=int(entry["id"]),
        full_name=entry.get("fullName", ""),
        last_name=entry.get("lastName", "") or entry.get("fullName", "").split()[-1],
        side=side,
        played=played,
    )


def load_dissection(settings: Settings, game_pk: int) -> Dissection:
    game_dir = find_game_dir(settings, game_pk)
    feed = read_gz_json(game_dir / f"{RESOURCE_FEED}.json.gz")
    gd, ld = feed["gameData"], feed["liveData"]
    box = ld["boxscore"]["teams"]

    # 로스터: 팀 소속과 출전 여부는 박스스코어에서, 이름은 gameData.players 에서
    players: dict[int, Player] = {}
    box_batting: dict[int, dict[str, Any]] = {}
    box_pitching: dict[int, dict[str, Any]] = {}
    for side in ("away", "home"):
        team = box[side]
        played_ids = set(team.get("batters", [])) | set(team.get("pitchers", []))
        for key, entry in team.get("players", {}).items():
            pid = int(entry["person"]["id"])
            gd_entry = gd["players"].get(f"ID{pid}", {"id": pid, "fullName": entry["person"]["fullName"]})
            players[pid] = _player_from_feed(gd_entry, side, pid in played_ids)
            stats = entry.get("stats", {})
            if stats.get("batting"):
                box_batting[pid] = stats["batting"]
            if stats.get("pitching"):
                box_pitching[pid] = stats["pitching"]

    def player(ref: dict[str, Any]) -> Player:
        pid = int(ref["id"])
        if pid not in players:
            players[pid] = Player(pid, ref.get("fullName", str(pid)), ref.get("fullName", str(pid)).split()[-1], "?", True)
        return players[pid]

    # 승리확률
    wp_path = game_dir / f"{RESOURCE_WINPROB}.json.gz"
    winprob: dict[int, dict[str, Any]] = {}
    if wp_path.exists():
        for entry in read_gz_json(wp_path):
            winprob[int(entry["atBatIndex"])] = entry

    plays: list[Play] = []
    away_prev = home_prev = 0
    prev_home_wp = 50.0
    n_pitches = 0
    for p in ld["plays"]["allPlays"]:
        res, about = p["result"], p["about"]
        events = p.get("playEvents", [])
        pitches = [e for e in events if e.get("isPitch")]
        n_pitches += len(pitches)
        last_pitch = pitches[-1] if pitches else None
        hit = (last_pitch or {}).get("hitData") or {}
        away_after = int(res.get("awayScore", away_prev))
        home_after = int(res.get("homeScore", home_prev))
        wp = winprob.get(int(about["atBatIndex"]), {})
        home_wp_after = wp.get("homeTeamWinProbability")
        play = Play(
            at_bat_index=int(about["atBatIndex"]),
            inning=int(about["inning"]),
            half=str(about.get("halfInning", "top")),
            batter=player(p["matchup"]["batter"]),
            pitcher=player(p["matchup"]["pitcher"]),
            event=str(res.get("event", "")),
            event_type=str(res.get("eventType", "")),
            description=str(res.get("description", "")).strip(),
            rbi=int(res.get("rbi", 0) or 0),
            is_out=bool(res.get("isOut", False)),
            away_before=away_prev,
            home_before=home_prev,
            away_after=away_after,
            home_after=home_after,
            runs_scored=(away_after - away_prev) + (home_after - home_prev),
            captivating_index=about.get("captivatingIndex"),
            home_wp_before=prev_home_wp if wp else None,
            home_wp_after=home_wp_after,
            home_wpa=wp.get("homeTeamWinProbabilityAdded"),
            leverage_index=wp.get("leverageIndex"),
            launch_speed=hit.get("launchSpeed"),
            hit_distance=hit.get("totalDistance"),
            n_pitches=len(pitches),
            play_ids={e["playId"]: e.get("pitchNumber") for e in events if e.get("playId")},
        )
        plays.append(play)
        away_prev, home_prev = away_after, home_after
        if home_wp_after is not None:
            prev_home_wp = float(home_wp_after)

    # 하이라이트 캡션 → 플레이
    by_play_id = {pid: play for play in plays for pid in play.play_ids}
    n_highlights = n_with_pid = 0
    recap_en = recap_es = None
    for lang in settings.languages:
        path = game_dir / f"{content_resource(lang)}.json.gz"
        if not path.exists():
            continue
        content = read_gz_json(path)
        if lang == "en":
            items = ((content.get("highlights") or {}).get("highlights") or {}).get("items") or []
            n_highlights = len(items)
            for item in items:
                guid = item.get("guid")
                if not guid:
                    continue
                n_with_pid += 1
                play = by_play_id.get(guid)
                if play is None:
                    continue
                pitch_no = play.play_ids.get(guid)
                play.captions.append(
                    Caption(
                        highlight_id=str(item.get("id") or item.get("slug") or guid),
                        title=(item.get("title") or item.get("headline") or "").strip(),
                        description=(item.get("description") or item.get("blurb") or "").strip(),
                        play_id=guid,
                        pitch_number=pitch_no,
                        is_last_pitch=pitch_no is not None and pitch_no == play.n_pitches,
                    )
                )
        recap = _load_recap(content, lang)
        if lang == "en":
            recap_en = recap
        elif lang == "es":
            recap_es = recap

    dissection = Dissection(
        game_pk=int(feed["gamePk"]),
        season=int(gd["game"]["season"]),
        game_type=str(gd["game"]["type"]),
        official_date=str(gd["datetime"]["officialDate"]),
        venue=str(gd.get("venue", {}).get("name", "")),
        attendance=gd.get("gameInfo", {}).get("attendance"),
        duration_minutes=gd.get("gameInfo", {}).get("gameDurationMinutes"),
        away_abbr=gd["teams"]["away"].get("abbreviation", "AWAY"),
        home_abbr=gd["teams"]["home"].get("abbreviation", "HOME"),
        away_name=gd["teams"]["away"].get("name", ""),
        home_name=gd["teams"]["home"].get("name", ""),
        away_score=int(ld["linescore"]["teams"]["away"].get("runs", away_prev)),
        home_score=int(ld["linescore"]["teams"]["home"].get("runs", home_prev)),
        plays=plays,
        n_pitches=n_pitches,
        n_highlights=n_highlights,
        n_highlights_with_play_id=n_with_pid,
        n_winprob=len(winprob),
        recap_en=recap_en,
        recap_es=recap_es,
        players=players,
        box_batting=box_batting,
        box_pitching=box_pitching,
    )
    if recap_en is not None:
        align_recap(dissection, recap_en)
    return dissection


def _load_recap(content: dict[str, Any], language: str) -> Recap | None:
    rec = ((content.get("editorial") or {}).get("recap") or {}).get("mlb") or {}
    body = rec.get("body")
    if not body:
        return None
    dateline, paragraphs = clean_recap_html(body)
    sentences = sentences_with_quote_state(paragraphs)
    return Recap(
        language=language,
        headline=(rec.get("headline") or "").strip(),
        seo_title=(rec.get("seoTitle") or "").strip(),
        dateline=dateline,
        authors=[c.get("name", "") for c in rec.get("contributors") or []],
        paragraphs=paragraphs,
        sentences=sentences,
        body_chars=len(body),
        n_quotes=sum(1 for s in sentences if s.kind == "quote"),
    )


# ----------------------------------------------------------------------------- alignment rules

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8, "9th": 9,
    "10th": 10, "11th": 11, "12th": 12,
}

EVENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(home runs?|homer(?:ed|s)?|went deep|(?:two|three)-run shot|solo shot|grand slam|long ball|dinger)\b", re.I), "home_run"),
    (re.compile(r"\b(doubled?|two-bagger)\b", re.I), "double"),
    (re.compile(r"\btripled?\b", re.I), "triple"),
    (re.compile(r"\bsingled?\b", re.I), "single"),
    (re.compile(r"\b(walk(?:ed|s)?|base on balls|free pass)\b", re.I), "walk"),
    (re.compile(r"\b(struck out|strikeouts?|strikes? out|fanned|punched out|punchout|whiff(?:ed|s)?|K'd)\b", re.I), "strikeout"),
    (re.compile(r"\bsac(?:rifice)? fly\b", re.I), "sac_fly"),
    (re.compile(r"\b(hit by (?:a )?pitch|plunked)\b", re.I), "hit_by_pitch"),
    (re.compile(r"\b(grounded (?:out|into)|groundout|flied out|flyout|popped (?:out|up)|lined out|lineout)\b", re.I), "field_out"),
]
EVENT_ALIASES = {"strikeout": {"strikeout", "strike_out"}}
EVENT_KO = {"home_run": "홈런", "double": "2루타", "triple": "3루타", "single": "단타", "walk": "볼넷",
            "strikeout": "삼진", "sac_fly": "희생플라이", "hit_by_pitch": "사구", "field_out": "범타"}

RBI_MODIFIERS = [(re.compile(r"\bsolo\b", re.I), 1), (re.compile(r"\btwo-run\b", re.I), 2),
                 (re.compile(r"\bthree-run\b", re.I), 3), (re.compile(r"\bgrand slam\b", re.I), 4)]
PITCHER_VERBS = re.compile(r"\b(surrendered|gave up|allowed|yielded|served up|coughed up)\b", re.I)
INNING_RE = re.compile(
    r"\b(?:in|during) the (first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d{1,2}(?:st|nd|rd|th))\b"
    r"|\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d{1,2}(?:st|nd|rd|th))(?:-inning| inning)\b",
    re.I,
)
HIT_AGG_RE = re.compile(r"\b(\w+)-hit\b", re.I)
RBI_AGG_RE = re.compile(r"\b(\w+)-RBI\b", re.I)
N_FOR_M_RE = re.compile(r"\b(\d+)-for-(\d+)\b")
CYCLE_RE = re.compile(r"\b(single|double|triple|home run|homer) shy of (?:[\w'’-]+ ){0,5}?cycle\b|\bcycle\b", re.I)
PERFECT_RE = re.compile(r"\b(\w+) perfect (?:innings?|frames?)\b", re.I)
SCORELESS_RE = re.compile(r"\b(\w+) (?:scoreless|shutout) (?:innings?|frames?)\b", re.I)
RUNS_ALLOWED_RE = re.compile(r"\b(?:allowed|surrendered|gave up|yielded) (a|an|\w+) runs?\b", re.I)
KNOCKED_IN_RE = re.compile(r"\b(knocked in|drove in|plated|drove home)\b", re.I)
SCORE_RE = re.compile(r"\b(\d{1,2})-(\d{1,2})\b (?:victory|win|loss|defeat|lead|triumph|rout)", re.I)
CONJ_ONLY_RE = re.compile(r"^[\s,]*(?:and|&)?[\s,]*$", re.I)


@dataclass(frozen=True)
class Mention:
    player: Player
    start: int
    end: int


def _to_number(word: str) -> int | None:
    word = word.lower()
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def _to_inning(word: str) -> int | None:
    return ORDINALS.get(word.lower())


def find_mentions(text: str, players: dict[int, Player]) -> tuple[list[Mention], list[str]]:
    """문장에서 로스터 선수를 위치와 함께 찾는다. 성이 겹치면 출전 선수를 우선하고, 그래도 겹치면 '모호'로 남긴다.
    액센트는 양쪽 다 제거하고(Hernández/Hernandez) 대소문자는 유지한다(Call 이 일반 단어 call 에 붙지 않게).
    strip_accents 는 문자 수를 바꾸지 않으므로 위치는 원문과 같다."""
    ascii_text = strip_accents(text)
    found: list[Mention] = []
    covered: list[tuple[int, int]] = []
    ambiguous: list[str] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(not (span[1] <= a or span[0] >= b) for a, b in covered)

    for p in sorted(players.values(), key=lambda x: -len(x.ascii_full)):
        for m in re.finditer(rf"\b{re.escape(p.ascii_full)}\b", ascii_text):
            if not overlaps(m.span()):
                covered.append(m.span())
                found.append(Mention(p, *m.span()))
    by_last: dict[str, list[Player]] = {}
    for p in players.values():
        by_last.setdefault(p.ascii_last, []).append(p)
    for last, group in sorted(by_last.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(rf"\b{re.escape(last)}\b", ascii_text):
            if overlaps(m.span()):
                continue
            covered.append(m.span())
            candidates = [p for p in group if p.played] or group
            if len(candidates) == 1:
                found.append(Mention(candidates[0], *m.span()))
            else:
                ambiguous.append(last)
    return sorted(found, key=lambda m: m.start), ambiguous


def subjects_for(text: str, mentions: list[Mention], pos: int) -> list[Mention]:
    """주장(pos)의 주어: 바로 앞의 선수 언급 + 쉼표/and 로만 이어진 앞 언급들. 앞에 없으면 바로 뒤의 언급."""
    preceding = [m for m in mentions if m.end <= pos]
    if preceding:
        group = [preceding[-1]]
        for prev, cur in zip(reversed(preceding[:-1]), reversed(preceding)):
            if CONJ_ONLY_RE.match(text[prev.end:cur.start]):
                group.insert(0, prev)
            else:
                break
        return group
    following = [m for m in mentions if m.start >= pos]
    return following[:1]


def inning_near(text: str, mentions: list[Mention], pos: int) -> int | None:
    """주장과 가장 가까운 이닝 표현. 사이에 다른 선수 언급이 끼면 그 이닝은 다른 절의 것으로 보고 제외."""
    best: tuple[int, int] | None = None
    for m in INNING_RE.finditer(text):
        inning = _to_inning(m.group(1) or m.group(2))
        if inning is None:
            continue
        lo, hi = (m.end(), pos) if m.end() <= pos else (pos, m.start())
        if any(lo < x.start < hi for x in mentions):
            continue
        dist = min(abs(m.start() - pos), abs(m.end() - pos))
        if best is None or dist < best[0]:
            best = (dist, inning)
    return best[1] if best else None


def _plays_for(plays: list[Play], player: Player, role: str) -> list[Play]:
    if role == "batter":
        return [p for p in plays if p.batter.id == player.id]
    return [p for p in plays if p.pitcher.id == player.id]


def _hit_summary(hits: list[Play]) -> str:
    names = {"single": "단타", "double": "2루타", "triple": "3루타", "home_run": "홈런"}
    counts: dict[str, int] = {}
    for p in hits:
        counts[p.event_type] = counts.get(p.event_type, 0) + 1
    return "·".join(f"{names[k]} {v}" for k, v in counts.items() if k in names) or "없음"


def _ok(flag: bool) -> str:
    return "일치" if flag else "불일치"


class _Aligner:
    """문장 하나의 정렬 상태. 주장마다 주어를 정해 그 선수의 플레이와 대조한다."""

    def __init__(self, sentence: Sentence, plays: list[Play], players: dict[int, Player],
                 box_batting: dict[int, dict[str, Any]], final_score: tuple[int, int] | None):
        self.s = sentence
        self.text = sentence.text
        self.plays = plays
        self.box_batting = box_batting
        self.final_score = final_score
        self.mentions, self.ambiguous = find_mentions(self.text, players)
        self.specific: list[Play] = []  # 문장이 가리키는 특정 타석
        self.covered: list[Play] = []  # 집계 주장이 포괄하는 타석 (언급으로 치지 않음)
        self.verdicts: list[bool] = []
        self.evidence: list[str] = []
        self.aggregate = False
        self.play_claim = False

    # ---- helpers ----
    def bat(self, m: Mention) -> list[Play]:
        return _plays_for(self.plays, m.player, "batter")

    def pit(self, m: Mention) -> list[Play]:
        return _plays_for(self.plays, m.player, "pitcher")

    def subjects(self, pos: int) -> list[Mention]:
        return subjects_for(self.text, self.mentions, pos)

    # ---- claims ----
    def score_claim(self) -> None:
        m = SCORE_RE.search(self.text)
        if not m or self.final_score is None:
            return
        a, b = int(m.group(1)), int(m.group(2))
        ok = {a, b} == set(self.final_score)
        self.verdicts.append(ok)
        self.evidence.append(f"최종 점수 {a}-{b} ↔ 기록 {self.final_score[0]}-{self.final_score[1]} {_ok(ok)}")
        self.aggregate = True

    def batting_aggregates(self) -> None:
        for m in HIT_AGG_RE.finditer(self.text):
            n = _to_number(m.group(1))
            for sub in self.subjects(m.start()):
                bat = self.bat(sub)
                if n is None or not bat:
                    continue
                hits = [p for p in bat if p.is_hit]
                ok = len(hits) == n
                self._record(ok, hits, f"{sub.player.last_name} 안타 {n} ↔ 플레이 {len(hits)}({_hit_summary(hits)}), 박스 {self.box_batting.get(sub.player.id, {}).get('hits', '?')}H {_ok(ok)}")
        for m in RBI_AGG_RE.finditer(self.text):
            n = _to_number(m.group(1))
            for sub in self.subjects(m.start()):
                bat = self.bat(sub)
                if n is None or not bat:
                    continue
                total = sum(p.rbi for p in bat)
                ok = total == n
                self._record(ok, [p for p in bat if p.rbi > 0], f"{sub.player.last_name} 타점 {n} ↔ 플레이 합 {total} {_ok(ok)}")
        for m in N_FOR_M_RE.finditer(self.text):
            for sub in self.subjects(m.start()):
                bat = self.bat(sub)
                if not bat:
                    continue
                box = self.box_batting.get(sub.player.id, {})
                ok = box.get("hits") == int(m.group(1)) and box.get("atBats") == int(m.group(2))
                self._record(ok, [p for p in bat if p.is_hit], f"{sub.player.last_name} {m.group(1)}-for-{m.group(2)} ↔ 박스 {box.get('hits', '?')}-{box.get('atBats', '?')} {_ok(ok)}")
        for m in CYCLE_RE.finditer(self.text):
            for sub in self.subjects(m.start()):
                bat = self.bat(sub)
                if not bat:
                    continue
                hits = [p for p in bat if p.is_hit]
                kinds = {p.event_type for p in hits}
                shy = m.group(1)
                if shy:
                    missing = {"single": "single", "double": "double", "triple": "triple", "home run": "home_run", "homer": "home_run"}[shy.lower()]
                    ok = kinds == HIT_EVENTS - {missing}
                    self._record(ok, hits, f"{sub.player.last_name} 사이클에서 {EVENT_KO[missing]} 하나 부족 ↔ 안타 종류 {_hit_summary(hits)} {_ok(ok)}")
                else:
                    ok = kinds == HIT_EVENTS
                    self._record(ok, hits, f"{sub.player.last_name} 사이클 ↔ 안타 종류 {_hit_summary(hits)} {_ok(ok)}")
        for m in KNOCKED_IN_RE.finditer(self.text):
            for sub in self.subjects(m.start()):
                bat = self.bat(sub)
                if not bat:
                    continue
                rbi_plays = [p for p in bat if p.rbi > 0]
                ok = bool(rbi_plays)
                self._record(ok, rbi_plays, f"{sub.player.last_name} 타점 " + (f"#{', #'.join(str(p.at_bat_index) for p in rbi_plays)}" if ok else "없음"))

    def pitching_aggregates(self) -> None:
        for m in PERFECT_RE.finditer(self.text):
            n = _to_number(m.group(1))
            for sub in self.subjects(m.start()):
                pit = self.pit(sub)
                if n is None or not pit:
                    continue
                innings = sorted({p.inning for p in pit})[:n]
                relevant = [p for p in pit if p.inning in innings]
                clean = all(p.event_type in CLEAN_OUT_EVENTS for p in relevant)
                ok = len(innings) == n and len(relevant) == 3 * n and clean
                self._record(ok, [], f"{sub.player.last_name} 퍼펙트 {n}이닝 ↔ {len(innings)}이닝 {len(relevant)}타자 출루 {'0' if clean else '있음'} {_ok(ok)}", covered=relevant)
        for m in SCORELESS_RE.finditer(self.text):
            n = _to_number(m.group(1))
            for sub in self.subjects(m.start()):
                pit = self.pit(sub)
                if n is None or not pit:
                    continue
                innings = sorted({p.inning for p in pit})
                runs = sum(p.runs_scored for p in pit)
                ok = len(innings) == n and runs == 0
                self._record(ok, [], f"{sub.player.last_name} 무실점 {n}이닝 ↔ {len(innings)}이닝 실점 {runs} {_ok(ok)}", covered=pit)
        for m in RUNS_ALLOWED_RE.finditer(self.text):
            n = _to_number(m.group(1))
            inning = inning_near(self.text, self.mentions, m.start())
            for sub in self.subjects(m.start()):
                pit = self.pit(sub)
                if not pit:
                    continue
                scope = [p for p in pit if inning is None or p.inning == inning]
                runs = sum(p.runs_scored for p in scope)
                ok = n is not None and runs == n
                self._record(ok, [p for p in scope if p.runs_scored > 0], f"{sub.player.last_name} 실점 {n}{f'({inning}회)' if inning else ''} ↔ 플레이 {runs} {_ok(ok)}")

    def event_claims(self) -> None:
        for pattern, event_type in EVENT_PATTERNS:
            for m in pattern.finditer(self.text):
                if re.match(r"\s+shy\b", self.text[m.end():]):
                    continue  # "a triple shy of the cycle" — 부정 맥락
                accepted = EVENT_ALIASES.get(event_type, {event_type})
                inning = inning_near(self.text, self.mentions, m.start())
                for sub in self.subjects(m.start()):
                    between = self.text[sub.end:m.start()] if sub.end <= m.start() else ""
                    pitcher_role = bool(PITCHER_VERBS.search(between))
                    pool = self.pit(sub) if pitcher_role else self.bat(sub)
                    if not pool:
                        pool = self.bat(sub) or self.pit(sub)
                    cands = [p for p in pool if p.event_type in accepted]
                    if inning is not None:
                        cands = [p for p in cands if p.inning == inning]
                    if event_type == "home_run":
                        window = self.text[max(0, m.start() - 12):m.start()]
                        for pat, rbi_n in RBI_MODIFIERS:
                            if pat.search(window):
                                cands = [p for p in cands if p.rbi == rbi_n]
                    label = f"{sub.player.last_name} {'피' if pitcher_role else ''}{EVENT_KO[event_type]}"
                    if cands:
                        self.verdicts.append(True)
                        self.specific += cands
                        self.play_claim = True
                        self.evidence.append(label + " → " + ", ".join(f"#{p.at_bat_index}" for p in cands))
                    else:
                        self.evidence.append(label + " — 대응 플레이 없음")

    def _record(self, ok: bool, specific: list[Play], evidence: str, covered: list[Play] | None = None) -> None:
        self.verdicts.append(ok)
        self.specific += specific
        if covered:
            self.covered += covered
        self.evidence.append(evidence)
        self.aggregate = True

    def finish(self) -> None:
        s = self.s
        s.mentions = [m.player for m in self.mentions]
        if s.kind == "quote":
            return
        if self.ambiguous:
            self.evidence.append("성만 있어 모호: " + ", ".join(sorted(set(self.ambiguous))))
        seen: set[int] = set()
        s.plays = [p.at_bat_index for p in self.specific if not (p.at_bat_index in seen or seen.add(p.at_bat_index))]
        seen_c: set[int] = set(s.plays)
        s.covered = [p.at_bat_index for p in self.covered if not (p.at_bat_index in seen_c or seen_c.add(p.at_bat_index))]
        s.evidence = "; ".join(self.evidence)
        if self.aggregate:
            s.kind = "aggregate"
        elif self.play_claim:
            s.kind = "play"
        if self.verdicts:
            s.verdict = "확인" if all(self.verdicts) else "불일치"
        elif self.mentions:
            s.verdict = "대응 없음"
            s.evidence = s.evidence or (", ".join(m.player.last_name for m in self.mentions) + " 언급, 플레이 주장 없음")


def align_sentence(sentence: Sentence, plays: list[Play], players: dict[int, Player],
                   box_batting: dict[int, dict[str, Any]], final_score: tuple[int, int] | None = None) -> None:
    """문장 하나를 플레이·박스스코어와 대조해 kind/plays/covered/verdict/evidence 를 채운다."""
    a = _Aligner(sentence, plays, players, box_batting, final_score)
    if sentence.kind != "quote":
        a.score_claim()
        a.batting_aggregates()
        a.pitching_aggregates()
        a.event_claims()
    a.finish()


def align_recap(d: Dissection, recap: Recap) -> None:
    for play in d.plays:
        play.sentence_ids = []
    for s in recap.sentences:
        align_sentence(s, d.plays, d.players, d.box_batting, final_score=(d.away_score, d.home_score))
        for idx in s.plays:
            d.plays[idx].sentence_ids.append(s.sid)


# ----------------------------------------------------------------------------- export


def to_jsonable(d: Dissection) -> dict[str, Any]:
    """정렬 결과를 JSON 으로 (파생 테이블 설계·다른 도구 입력용)."""
    def recap_json(r: Recap | None) -> dict[str, Any] | None:
        if r is None:
            return None
        return {
            "language": r.language, "headline": r.headline, "dateline": r.dateline, "authors": r.authors,
            "body_chars": r.body_chars, "n_paragraphs": len(r.paragraphs), "n_quotes": r.n_quotes,
            "sentences": [
                {"sid": s.sid, "paragraph": s.paragraph, "kind": s.kind, "text": s.text,
                 "mentions": [p.id for p in s.mentions], "plays": s.plays, "covered": s.covered, "verdict": s.verdict, "evidence": s.evidence}
                for s in r.sentences
            ],
        }
    return {
        "game_pk": d.game_pk, "season": d.season, "game_type": d.game_type, "official_date": d.official_date,
        "away": {"abbr": d.away_abbr, "name": d.away_name, "score": d.away_score},
        "home": {"abbr": d.home_abbr, "name": d.home_name, "score": d.home_score},
        "n_pitches": d.n_pitches, "n_highlights": d.n_highlights, "n_highlights_with_play_id": d.n_highlights_with_play_id,
        "plays": [
            {
                "at_bat_index": p.at_bat_index, "inning": p.inning, "half": p.half,
                "batter_id": p.batter.id, "batter": p.batter.full_name, "pitcher_id": p.pitcher.id, "pitcher": p.pitcher.full_name,
                "event_type": p.event_type, "description": p.description, "rbi": p.rbi, "runs_scored": p.runs_scored,
                "score_after": [p.away_after, p.home_after], "captivating_index": p.captivating_index,
                "home_wpa": p.home_wpa, "wpa_batting": p.wpa_batting, "leverage_index": p.leverage_index,
                "launch_speed": p.launch_speed, "hit_distance": p.hit_distance,
                "captions": [{"title": c.title, "description": c.description, "pitch_number": c.pitch_number, "is_last_pitch": c.is_last_pitch} for c in p.captions],
                "sentence_ids": p.sentence_ids,
            }
            for p in d.plays
        ],
        "recap_en": recap_json(d.recap_en),
        "recap_es": recap_json(d.recap_es),
    }


# ----------------------------------------------------------------------------- summaries


def selection_summary(d: Dissection) -> dict[str, Any]:
    """기사에 언급된 타석 vs 아닌 타석의 첫 비교 (docs/02 §3 뉴스가치 모델의 씨앗)."""
    def group(plays: list[Play]) -> dict[str, Any]:
        n = len(plays)
        wpa = [abs(p.home_wpa) for p in plays if p.home_wpa is not None]
        cap = [p.captivating_index for p in plays if p.captivating_index is not None]
        return {
            "n": n,
            "mean_abs_wpa": round(sum(wpa) / len(wpa), 2) if wpa else None,
            "mean_captivating": round(sum(cap) / len(cap), 1) if cap else None,
            "home_runs": sum(1 for p in plays if p.event_type == "home_run"),
            "hits": sum(1 for p in plays if p.is_hit),
            "runs": sum(p.runs_scored for p in plays),
            "with_caption": sum(1 for p in plays if p.captions),
        }
    mentioned = [p for p in d.plays if p.mentioned]
    unmentioned = [p for p in d.plays if not p.mentioned]
    scoring = [p for p in d.plays if p.runs_scored > 0]
    top_wpa = sorted((p for p in d.plays if p.home_wpa is not None), key=lambda p: -abs(p.home_wpa))[:10]
    captioned = [p for p in d.plays if p.captions]
    return {
        "mentioned": group(mentioned),
        "unmentioned": group(unmentioned),
        "top_wpa": top_wpa,
        "captioned": len(captioned),
        "captioned_and_mentioned": sum(1 for p in captioned if p.mentioned),
        "scoring": len(scoring),
        "scoring_and_mentioned": sum(1 for p in scoring if p.mentioned),
    }
