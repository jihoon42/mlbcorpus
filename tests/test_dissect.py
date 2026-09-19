"""dissect 의 텍스트 정제·문장 분리·이름 찾기·정렬 규칙. 실제 API 응답 구조를 최소한으로 흉내 낸 합성 경기로 검증한다."""

import gzip
import json

import pytest

from mlbcorpus import dissect as dm
from mlbcorpus.dissect import (
    Player, Play, Sentence, align_sentence, clean_recap_html, find_mentions, inning_near, load_dissection,
    sentences_with_quote_state, split_sentences, subjects_for,
)
from mlbcorpus.dissect_md import render

# ----------------------------------------------------------------------------- text


def test_clean_recap_html_strips_embeds_links_and_related_bullets():
    body = (
        '<p>CINCINNATI -- The Dodgers won an <a href="https://x" target="_blank">8-2 victory</a> on Thursday.\n\n'
        "They [clinched](https://www.mlb.com/y) the West.</p>"
        '<p><iframe class="story-player-iframe" src="https://www.mlb.com/stories/game/1"></iframe></p>'
        '<p>*   <a href="https://z">Related: the schedule</a></p>'
        "<p>Roberts said **it** was &quot;fine&quot;.</p>"
    )
    dateline, paragraphs = clean_recap_html(body)
    assert dateline == "CINCINNATI"
    assert paragraphs == [
        "The Dodgers won an 8-2 victory on Thursday.",
        "They clinched the West.",
        'Roberts said it was "fine".',
    ]


def test_split_sentences_keeps_abbreviations_and_quotes():
    para = 'He was dealt to L.A. ahead of the deadline. They hold the No. 2 seed. "It works," Betts said. "Same goal."'
    assert split_sentences(para) == [
        "He was dealt to L.A. ahead of the deadline.",
        "They hold the No. 2 seed.",
        '"It works," Betts said.',
        '"Same goal."',
    ]


def test_quote_state_marks_sentences_inside_an_open_quote():
    paragraphs = ['"We had troubles. Things were hard. But we finish strong," Friedman said.', "The Dodgers lead the West."]
    sents = sentences_with_quote_state(paragraphs)
    assert [s.kind for s in sents] == ["quote", "quote", "quote", "context"]
    assert [s.paragraph for s in sents] == [1, 1, 1, 2]
    assert [s.sid for s in sents] == [1, 2, 3, 4]


# ----------------------------------------------------------------------------- mentions


def roster() -> dict[int, Player]:
    ps = [
        Player(1, "Kyle Tucker", "Tucker", "away", True),
        Player(2, "Teoscar Hernández", "Hernández", "away", True),
        Player(3, "Enrique Hernández", "Hernández", "away", False),
        Player(4, "Alex Call", "Call", "away", False),
        Player(5, "Josue De Paula", "De Paula", "away", True),
        Player(6, "Blake Treinen", "Treinen", "away", True),
        Player(7, "Sal Stewart", "Stewart", "home", True),
        Player(8, "Brock Stewart", "Stewart", "home", True),
    ]
    return {p.id: p for p in ps}


def test_find_mentions_full_name_accent_and_possessive():
    found, ambiguous = find_mentions("Tucker's double and Teoscar Hernandez's single; Josue De Paula walked.", roster())
    assert [m.player.full_name for m in found] == ["Kyle Tucker", "Teoscar Hernández", "Josue De Paula"]
    assert ambiguous == []
    assert [m.start for m in found] == sorted(m.start for m in found)


def test_find_mentions_prefers_players_who_played_and_flags_true_ambiguity():
    found, ambiguous = find_mentions("Hernández doubled; Stewart homered.", roster())
    assert [m.player.full_name for m in found] == ["Teoscar Hernández"]  # 출전 선수 우선
    assert ambiguous == ["Stewart"]  # 둘 다 출전 → 모호


def test_find_mentions_is_case_sensitive_for_common_word_surnames():
    found, _ = find_mentions("It was a close call, and Call pinch-hit.", roster())
    assert [m.player.full_name for m in found] == ["Alex Call"]


def test_subjects_for_groups_conjoined_names():
    text = "Kyle Tucker, Josue De Paula and Teoscar Hernández also knocked in runs, while Blake Treinen struggled."
    mentions, _ = find_mentions(text, roster())
    pos = text.index("knocked")
    assert [m.player.last_name for m in subjects_for(text, mentions, pos)] == ["Tucker", "De Paula", "Hernández"]
    assert [m.player.last_name for m in subjects_for(text, mentions, text.index("struggled"))] == ["Treinen"]
    assert [m.player.last_name for m in subjects_for(text, mentions, 0)] == ["Tucker"]  # 앞에 없으면 뒤의 첫 언급


def test_inning_near_ignores_innings_in_other_clauses():
    text = "Blake Treinen surrendered a solo home run in the fourth, and Sal Stewart allowed a run in the ninth."
    mentions, _ = find_mentions(text, roster())
    assert inning_near(text, mentions, text.index("home run")) == 4
    assert inning_near(text, mentions, text.index("allowed")) == 9
    assert inning_near("Tucker homered.", [], 0) is None


# ----------------------------------------------------------------------------- alignment on a synthetic game


def _play(idx, inning, half, batter, pitcher, event_type, desc, rbi=0, runs=0, wpa=0.0):
    return Play(
        at_bat_index=idx, inning=inning, half=half, batter=batter, pitcher=pitcher, event=event_type, event_type=event_type,
        description=desc, rbi=rbi, is_out=event_type in ("field_out", "strikeout"), away_before=0, home_before=0,
        away_after=0, home_after=0, runs_scored=runs, captivating_index=10, home_wp_before=50.0, home_wp_after=50.0 + wpa,
        home_wpa=wpa, leverage_index=1.0, launch_speed=None, hit_distance=None, n_pitches=3, play_ids={f"pid{idx}": 3},
    )


@pytest.fixture
def game():
    r = roster()
    tucker, teo, treinen, sal = r[1], r[2], r[6], r[7]
    plays = [
        _play(0, 1, "top", tucker, sal, "strikeout", "Kyle Tucker strikes out swinging."),
        _play(1, 1, "top", teo, sal, "field_out", "Teoscar Hernández flies out."),
        _play(2, 1, "top", tucker, sal, "field_out", "Kyle Tucker grounds out."),
        _play(3, 2, "top", tucker, sal, "home_run", "Kyle Tucker homers (16). Teoscar Hernández scores.", rbi=2, runs=2, wpa=-16.7),
        _play(4, 3, "top", tucker, sal, "double", "Kyle Tucker doubles (22).", rbi=1, runs=1),
        _play(5, 4, "bottom", sal, treinen, "home_run", "Sal Stewart homers (32).", rbi=1, runs=1),
        _play(6, 5, "top", tucker, sal, "single", "Kyle Tucker singles."),
        _play(7, 9, "bottom", sal, treinen, "field_out", "Sal Stewart grounds out. Run scores.", rbi=1, runs=1),
    ]
    box_batting = {tucker.id: {"hits": 3, "atBats": 5, "rbi": 3}}
    return r, plays, box_batting


def _align(text, game, kind="context"):
    r, plays, box = game
    s = Sentence(sid=1, paragraph=1, text=text, kind=kind)
    align_sentence(s, plays, r, box, final_score=(4, 2))
    return s


def test_direct_event_with_inning_and_rbi_modifier(game):
    s = _align("Kyle Tucker hit a two-run homer in the second.", game)
    assert s.kind == "play" and s.plays == [3] and s.verdict == "확인"
    s = _align("Kyle Tucker hit a two-run homer in the third.", game)  # 이닝이 틀리면 대응 없음
    assert s.plays == [] and s.verdict == "대응 없음" and "대응 플레이 없음" in s.evidence


def test_pitcher_verb_routes_event_to_pitcher(game):
    s = _align("Blake Treinen surrendered a solo home run in the fourth.", game)
    assert s.plays == [5] and s.verdict == "확인" and "피홈런" in s.evidence


def test_batting_aggregates_and_cycle(game):
    s = _align("Kyle Tucker led the way with a three-hit, three-RBI showing, finishing a triple shy of the cycle.", game)
    assert s.kind == "aggregate" and s.verdict == "확인"
    assert s.plays == [3, 4, 6]  # 안타 셋
    assert "3루타 하나 부족" in s.evidence
    s = _align("Kyle Tucker went 3-for-5.", game)
    assert s.verdict == "확인" and s.plays == [3, 4, 6]
    s = _align("Kyle Tucker had a four-hit night.", game)
    assert s.verdict == "불일치"


def test_pitching_aggregates_cover_but_do_not_mention(game):
    s = _align("Sal Stewart opened with one perfect inning before Blake Treinen allowed a run in the ninth.", game)
    assert s.kind == "aggregate" and s.verdict == "확인"
    assert s.plays == [7]  # 9회 실점 플레이만 특정
    assert s.covered == [0, 1, 2]  # 퍼펙트 1이닝이 포괄하는 타석
    assert "퍼펙트 1이닝" in s.evidence and "실점 1(9회)" in s.evidence


def test_knocked_in_runs_for_a_list_of_players(game):
    s = _align("Kyle Tucker and Sal Stewart also knocked in runs.", game)
    assert s.verdict == "확인" and sorted(s.plays) == [3, 4, 5, 7]


def test_score_claim_and_quotes_and_context(game):
    s = _align("They sealed a 4-2 victory over the Reds.", game)
    assert s.kind == "aggregate" and s.verdict == "확인" and s.plays == []
    s = _align('"We never panicked," Kyle Tucker said.', game, kind="quote")
    assert s.kind == "quote" and [p.last_name for p in s.mentions] == ["Tucker"] and s.plays == []
    s = _align("Alex Call was not in the lineup.", game)
    assert s.kind == "context" and s.verdict == "대응 없음"


# ----------------------------------------------------------------------------- end to end on cached files


def _write_gz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(json.dumps(obj).encode())


def test_load_dissection_and_render(settings):
    pk = 5001
    p1 = {"id": 1, "fullName": "Kyle Tucker", "link": "/api/v1/people/1"}
    p2 = {"id": 7, "fullName": "Sal Stewart", "link": "/api/v1/people/7"}
    plays = [
        {"atBatIndex": 0, "result": {"description": "Kyle Tucker homers (1).", "event": "Home Run", "eventType": "home_run", "rbi": 1, "awayScore": 1, "homeScore": 0, "isOut": False},
         "about": {"atBatIndex": 0, "inning": 1, "halfInning": "top", "captivatingIndex": 40},
         "matchup": {"batter": p1, "pitcher": p2},
         "playEvents": [{"index": 0, "isPitch": True, "playId": "hr-pitch", "pitchNumber": 1, "hitData": {"launchSpeed": 105.1, "totalDistance": 410}}]},
        {"atBatIndex": 1, "result": {"description": "Sal Stewart strikes out.", "event": "Strikeout", "eventType": "strikeout", "rbi": 0, "awayScore": 1, "homeScore": 0, "isOut": True},
         "about": {"atBatIndex": 1, "inning": 1, "halfInning": "bottom", "captivatingIndex": 5},
         "matchup": {"batter": p2, "pitcher": p1},
         "playEvents": [{"index": 0, "isPitch": True, "playId": "k-pitch-1", "pitchNumber": 1}, {"index": 1, "isPitch": True, "playId": "k-pitch-2", "pitchNumber": 2}]},
    ]
    feed = {
        "gamePk": pk,
        "gameData": {
            "game": {"pk": pk, "season": "2026", "type": "R"},
            "datetime": {"officialDate": "2026-09-17"},
            "status": {"codedGameState": "F", "detailedState": "Final"},
            "teams": {"away": {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD"}, "home": {"id": 113, "name": "Cincinnati Reds", "abbreviation": "CIN"}},
            "venue": {"name": "Great American Ball Park"},
            "gameInfo": {"attendance": 24169, "gameDurationMinutes": 159},
            "players": {"ID1": {"id": 1, "fullName": "Kyle Tucker", "lastName": "Tucker"}, "ID7": {"id": 7, "fullName": "Sal Stewart", "lastName": "Stewart"}},
        },
        "liveData": {
            "plays": {"allPlays": plays},
            "linescore": {"teams": {"away": {"runs": 1}, "home": {"runs": 0}}},
            "boxscore": {"teams": {
                "away": {"batters": [1], "pitchers": [], "players": {"ID1": {"person": p1, "stats": {"batting": {"hits": 1, "atBats": 1}}}}},
                "home": {"batters": [7], "pitchers": [7], "players": {"ID7": {"person": p2, "stats": {"batting": {"hits": 0, "atBats": 1}, "pitching": {}}}}},
            }},
        },
    }
    content_en = {
        "editorial": {"recap": {"mlb": {
            "headline": "Tucker homers", "contributors": [{"name": "Writer"}],
            "body": "<p>CINCINNATI -- Kyle Tucker hit a solo homer in the first for a 1-0 win.\n\n\"Felt good,\" Tucker said.</p>",
        }}},
        "highlights": {"highlights": {"items": [
            {"id": "h1", "guid": "hr-pitch", "title": "Tucker's solo homer", "description": "Kyle Tucker crushes a solo home run"},
            {"id": "h2", "guid": "k-pitch-1", "title": "Ball overturned", "description": "ABS overturns ball 1"},
            {"id": "h3", "title": "Postgame interview", "description": "no guid"},
        ]}},
    }
    content_es = {"editorial": {"recap": {"mlb": {"headline": "Tucker conecta", "contributors": [{"name": "Writer"}], "body": "<p>Kyle Tucker conectó un jonrón.</p>"}}}}
    winprob = [
        {"atBatIndex": 0, "homeTeamWinProbability": 40.0, "homeTeamWinProbabilityAdded": -10.0},
        {"atBatIndex": 1, "homeTeamWinProbability": 38.0, "homeTeamWinProbabilityAdded": -2.0, "leverageIndex": 0.9},
    ]
    gd = settings.game_dir(2026, pk)
    _write_gz(gd / "feed.json.gz", feed)
    _write_gz(gd / "content.en.json.gz", content_en)
    _write_gz(gd / "content.es.json.gz", content_es)
    _write_gz(gd / "winprob.json.gz", winprob)

    d = load_dissection(settings, pk)
    assert d.away_score == 1 and d.n_pitches == 3 and d.n_highlights == 3 and d.n_highlights_with_play_id == 2
    hr, k = d.plays
    assert hr.wpa_batting == 10.0 and hr.home_wp_before == 50.0 and hr.launch_speed == 105.1
    assert [c.description for c in hr.captions] == ["Kyle Tucker crushes a solo home run"] and hr.captions[0].is_last_pitch
    assert k.captions[0].pitch_number == 1 and not k.captions[0].is_last_pitch  # 마지막 투구가 아닌 투구에 붙은 영상
    assert k.leverage_index == 0.9 and k.wpa_batting == -2.0
    rec = d.recap_en
    assert rec.dateline == "CINCINNATI" and [s.kind for s in rec.sentences] == ["aggregate", "quote"]
    assert rec.sentences[0].plays == [0] and rec.sentences[0].verdict == "확인"
    assert hr.sentence_ids == [1] and k.sentence_ids == []
    assert d.recap_es.headline == "Tucker conecta"

    md = render(d)
    assert "## 3. 타석별 정렬표" in md and "| 0 | 1초 | Kyle Tucker vs Stewart |" in md
    assert "득점이 난 타석 1개 중 기사에 언급된 것 1개" in md
    assert "Tucker conecta" in md

    j = dm.to_jsonable(d)
    assert j["plays"][0]["sentence_ids"] == [1] and j["recap_en"]["sentences"][0]["plays"] == [0]


def test_find_game_dir_missing(settings):
    with pytest.raises(FileNotFoundError):
        dm.find_game_dir(settings, 1)
