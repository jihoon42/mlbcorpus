from mlbcorpus import endpoints


def test_schedule_url():
    assert endpoints.schedule(2025, "R") == "https://statsapi.mlb.com/api/v1/schedule?sportId=1&season=2025&gameType=R"


def test_schedule_url_with_hydrate_is_encoded():
    url = endpoints.schedule_by_date("2026-09-17", hydrate="game(content(editorial(recap)))", language="es")
    assert url.startswith("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-09-17&hydrate=")
    assert "game%28content%28editorial%28recap%29%29%29" in url
    assert url.endswith("&language=es")


def test_feed_live_is_v1_1():
    assert endpoints.feed_live(824464) == "https://statsapi.mlb.com/api/v1.1/game/824464/feed/live"


def test_content_english_has_no_language_param():
    assert endpoints.content(824464) == "https://statsapi.mlb.com/api/v1/game/824464/content"
    assert endpoints.content(824464, "en") == "https://statsapi.mlb.com/api/v1/game/824464/content"


def test_content_spanish():
    assert endpoints.content(824464, "es") == "https://statsapi.mlb.com/api/v1/game/824464/content?language=es"


def test_win_probability_and_meta():
    assert endpoints.win_probability(1) == "https://statsapi.mlb.com/api/v1/game/1/winProbability"
    assert endpoints.meta("eventTypes") == "https://statsapi.mlb.com/api/v1/eventTypes"
