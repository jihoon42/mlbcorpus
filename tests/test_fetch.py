import time

import httpx
import pytest

from mlbcorpus.fetch import FetchError, Fetcher, NotFound, RateLimiter

URL = "https://statsapi.mlb.com/api/v1/game/1/winProbability"


async def test_ok_returns_raw_bytes_and_parsed_json(settings, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, content=b'[{"atBatIndex": 0}]'))
    async with Fetcher(settings) as fetcher:
        result = await fetcher.get_json_bytes(URL)
    assert result.content == b'[{"atBatIndex": 0}]'  # 재직렬화하지 않는다
    assert result.data == [{"atBatIndex": 0}]
    assert result.attempts == 1


async def test_retries_on_503_then_succeeds(settings, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json=[])])
    async with Fetcher(settings) as fetcher:
        result = await fetcher.get_json_bytes(URL)
    assert result.attempts == 2
    assert route.call_count == 2


async def test_retries_on_transport_error(settings, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=[])])
    async with Fetcher(settings) as fetcher:
        result = await fetcher.get_json_bytes(URL)
    assert result.attempts == 2 and route.call_count == 2


async def test_gives_up_after_max_retries(settings, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(500))
    async with Fetcher(settings) as fetcher:
        with pytest.raises(FetchError, match="giving up after 3 attempts"):
            await fetcher.get_json_bytes(URL)
    assert route.call_count == settings.max_retries + 1


async def test_404_is_not_retried(settings, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(404))
    async with Fetcher(settings) as fetcher:
        with pytest.raises(NotFound):
            await fetcher.get_json_bytes(URL)
    assert route.call_count == 1


async def test_200_with_html_body_is_an_error(settings, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text="<html>login</html>"))
    async with Fetcher(settings) as fetcher:
        with pytest.raises(FetchError, match="not JSON"):
            await fetcher.get_json_bytes(URL)


async def test_sends_user_agent(settings, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200, json=[]))
    async with Fetcher(settings) as fetcher:
        await fetcher.get_json_bytes(URL)
    assert route.calls.last.request.headers["User-Agent"].startswith("mlbcorpus/")


async def test_rate_limiter_spaces_requests():
    limiter = RateLimiter(requests_per_second=50)
    started = time.monotonic()
    for _ in range(5):
        await limiter.wait()
    elapsed = time.monotonic() - started
    assert elapsed >= 4 / 50 * 0.9  # 첫 요청은 즉시, 나머지 4개는 20ms 간격


async def test_rate_limiter_zero_means_unlimited():
    limiter = RateLimiter(requests_per_second=0)
    started = time.monotonic()
    for _ in range(100):
        await limiter.wait()
    assert time.monotonic() - started < 0.05
