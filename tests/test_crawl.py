import httpx

from mlbcorpus import crawl as crawl_mod
from mlbcorpus.manifest import Manifest
from mlbcorpus.storage import read_gz_json

from conftest import BASE, content_doc, feed_doc, schedule_doc, schedule_game, winprob_doc

RESOURCES = ("feed", "content.en", "content.es", "winprob")


def mock_schedule(respx_mock, games, *, season=2026, game_type="R"):
    return respx_mock.get(
        f"{BASE}/v1/schedule", params={"sportId": "1", "season": str(season), "gameType": game_type}
    ).mock(return_value=httpx.Response(200, json=schedule_doc(("2026-09-17", games))))


def mock_game(respx_mock, pk: int, *, feed=None, es_failures: int = 0):
    """경기 하나의 리소스 4개. es_failures 만큼 스페인어 content 가 503 을 낸 뒤 성공한다.

    스페인어 route 를 영어 route 보다 먼저 등록해야 한다 — 쿼리 없는 영어 route 는 어떤 쿼리든 매칭한다.
    """
    routes = {}
    routes["feed"] = respx_mock.get(f"{BASE}/v1.1/game/{pk}/feed/live").mock(
        return_value=httpx.Response(200, json=feed if feed is not None else feed_doc(pk))
    )
    es_route = respx_mock.get(f"{BASE}/v1/game/{pk}/content", params={"language": "es"})
    if es_failures:
        es_route.mock(side_effect=[httpx.Response(503)] * es_failures + [httpx.Response(200, json=content_doc(pk, "es"))])
    else:
        es_route.mock(return_value=httpx.Response(200, json=content_doc(pk, "es")))
    routes["content.es"] = es_route
    routes["content.en"] = respx_mock.get(f"{BASE}/v1/game/{pk}/content").mock(
        return_value=httpx.Response(200, json=content_doc(pk, "en"))
    )
    routes["winprob"] = respx_mock.get(f"{BASE}/v1/game/{pk}/winProbability").mock(
        return_value=httpx.Response(200, json=winprob_doc())
    )
    return routes


async def test_crawl_end_to_end_and_resume(settings, respx_mock):
    sched_route = mock_schedule(
        respx_mock,
        [
            schedule_game(101, "2026-09-17"),
            schedule_game(102, "2026-09-17"),
            schedule_game(103, "2026-09-17", detailed="Scheduled", coded="S"),
        ],
    )
    routes_101 = mock_game(respx_mock, 101)
    attempts = settings.max_retries + 1
    mock_game(respx_mock, 102, es_failures=attempts)  # 1차 실행의 모든 시도가 503, 2차 실행에서 성공

    # ---- 1차 실행: 종료 경기 2개, 102.content.es 만 실패 ----
    stats = await crawl_mod.crawl(settings)
    assert stats.games_seen == 3 and stats.games_finished == 2 and stats.games_pending == 2
    assert stats.fetched_ok == 7 and stats.fetched_failed == 1

    feed_path = settings.resource_path(2026, 101, "feed")
    assert feed_path.exists()
    assert read_gz_json(feed_path) == feed_doc(101)
    assert (settings.schedule_dir / "2026_R.json.gz").exists()
    assert not settings.resource_path(2026, 102, "content.es").exists()

    with Manifest(settings.manifest_path) as m:
        assert [(p.game_pk, p.missing) for p in m.pending(RESOURCES)] == [(102, ("content.es",))]
        assert m.recent_errors()[0][0] == 102

    # ---- 2차 실행: 실패했던 하나만 다시 받고 나머지는 건너뛴다 ----
    feed_calls_before = routes_101["feed"].call_count
    stats2 = await crawl_mod.crawl(settings)
    assert stats2.games_pending == 1 and stats2.fetched_ok == 1 and stats2.fetched_failed == 0
    assert routes_101["feed"].call_count == feed_calls_before == 1  # 이미 받은 feed 는 다시 요청하지 않음
    assert sched_route.call_count == 2  # schedule 은 실행마다 새로 (신규 종료 경기 반영)
    assert settings.resource_path(2026, 102, "content.es").exists()

    with Manifest(settings.manifest_path) as m:
        assert m.pending(RESOURCES) == []
        assert m.summary(RESOURCES)["complete_games"] == 2


async def test_crawl_rejects_feed_with_wrong_gamepk(settings, respx_mock):
    mock_schedule(respx_mock, [schedule_game(201, "2026-09-17")])
    mock_game(respx_mock, 201, feed=feed_doc(999))  # 다른 경기의 feed 가 오면 저장하지 않는다

    stats = await crawl_mod.crawl(settings)
    assert stats.fetched_failed == 1 and stats.fetched_ok == 3
    assert not settings.resource_path(2026, 201, "feed").exists()
    with Manifest(settings.manifest_path) as m:
        assert m.recent_errors()[0][3].startswith("feed: gamePk mismatch")


async def test_crawl_limit_and_no_refresh(settings, respx_mock):
    mock_schedule(respx_mock, [schedule_game(301, "2026-09-17"), schedule_game(302, "2026-09-17")])
    mock_game(respx_mock, 301)
    mock_game(respx_mock, 302)

    stats = await crawl_mod.crawl(settings, limit=1)
    assert stats.games_pending == 1 and stats.fetched_ok == 4

    stats2 = await crawl_mod.crawl(settings, refresh_schedule=False)
    assert stats2.schedules_fetched == 0 and stats2.games_pending == 1 and stats2.fetched_ok == 4


async def test_fetch_one_game_and_inspect(settings, respx_mock):
    mock_game(respx_mock, 824464)
    season, stats = await crawl_mod.fetch_one_game(settings, 824464)
    assert season == 2026 and stats.fetched_ok == 4 and stats.fetched_failed == 0

    summary = crawl_mod.inspect_game(settings, 2026, 824464)
    assert summary["matchup"] == "LAD@CIN" and summary["score"] == "8-2"
    assert summary["n_plays"] == 3 and summary["n_pitches"] == 3 and summary["n_play_ids"] == 6
    assert summary["recap_en"]["headline"] == "Recap 824464 (en)" and summary["recap_es"]["body_chars"] == 36
    assert summary["highlights_en"] == {"n": 2, "n_with_play_id": 1}
    assert summary["winprob"] == {"n": 3, "max_abs_wpa_at_bat": 2}

    with Manifest(settings.manifest_path) as m:
        assert m.pending(RESOURCES) == []  # sample 로 받은 경기도 manifest 에 반영


async def test_fetch_meta(settings, respx_mock):
    respx_mock.get(f"{BASE}/v1/eventTypes").mock(
        return_value=httpx.Response(200, json=[{"code": "single"}, {"code": "double"}])
    )
    counts = await crawl_mod.fetch_meta(settings, ["eventTypes"])
    assert counts == {"eventTypes": 2}
    assert read_gz_json(settings.meta_dir / "eventTypes.json.gz") == [{"code": "single"}, {"code": "double"}]
