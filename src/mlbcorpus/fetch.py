"""속도 제한 + 재시도가 붙은 비동기 HTTP 클라이언트.

- 전역 속도 제한: 초당 N 요청 (RateLimiter). MLB 가 공개한 한도는 없으므로 보수적으로 3/s.
- 재시도: 네트워크 오류, 429, 5xx 에 지수 백오프(+지터). Retry-After 헤더가 있으면 따른다.
- 200 이라도 JSON 으로 파싱되지 않으면 실패로 본다 (HTML 오류 페이지를 캐시하지 않기 위해).
- 성공 시 응답 바이트를 그대로 돌려준다. 저장도 그대로 한다 (재직렬화 없음).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """재시도 후에도 실패했거나, 재시도할 수 없는 응답."""

    def __init__(self, url: str, message: str, status_code: int | None = None):
        super().__init__(f"{message} [{url}]")
        self.url = url
        self.status_code = status_code


class NotFound(FetchError):
    """404. 존재하지 않는 gamePk 등. 재시도하지 않는다."""


class RateLimiter:
    """최소 간격 방식의 전역 속도 제한. 슬롯을 순서대로 배정하고 각자 자기 슬롯까지 잔다."""

    def __init__(self, requests_per_second: float):
        self._interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._interval == 0.0:
            return
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass
class FetchResult:
    url: str
    content: bytes  # 받은 그대로의 바이트. 저장은 이걸로.
    data: Any  # json.loads(content). 검증·요약용. 두 번 파싱하지 않기 위해 같이 돌려준다.
    status_code: int
    attempts: int
    elapsed_seconds: float


class Fetcher:
    """하나의 httpx.AsyncClient 를 공유하는 GET 도우미. `async with` 로 쓴다."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.limiter = RateLimiter(settings.requests_per_second)
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def get_json_bytes(self, url: str) -> FetchResult:
        """GET 후 JSON 으로 검증된 원본 바이트를 돌려준다. 실패는 FetchError."""
        started = time.monotonic()
        last_error: str = "no attempt"
        max_attempts = self.settings.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            await self.limiter.wait()
            try:
                response = await self.client.get(url)
            except httpx.TransportError as exc:  # 연결 실패, 타임아웃 등
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("attempt %d/%d transport error %s %s", attempt, max_attempts, last_error, url)
                retry_after = None
            else:
                status = response.status_code
                if status == 200:
                    try:
                        data = json.loads(response.content)
                    except ValueError as exc:
                        raise FetchError(url, f"200 but body is not JSON ({exc})", status) from exc
                    return FetchResult(
                        url=url,
                        content=response.content,
                        data=data,
                        status_code=status,
                        attempts=attempt,
                        elapsed_seconds=time.monotonic() - started,
                    )
                if status == 404:
                    raise NotFound(url, "404 not found", status)
                if status not in RETRYABLE_STATUS:
                    raise FetchError(url, f"unexpected HTTP {status}", status)
                last_error = f"HTTP {status}"
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                log.warning("attempt %d/%d got %s %s", attempt, max_attempts, last_error, url)

            if attempt == max_attempts:
                break
            await asyncio.sleep(
                _backoff_seconds(
                    attempt, retry_after, self.settings.backoff_base_seconds, self.settings.backoff_max_seconds
                )
            )

        raise FetchError(url, f"giving up after {max_attempts} attempts; last error: {last_error}")


def _backoff_seconds(attempt: int, retry_after: float | None, base: float, cap: float) -> float:
    if retry_after is not None:
        return min(retry_after, cap)
    delay = min(base**attempt, cap)  # base=2: 2, 4, 8, 16, 32, 60 ...
    return delay + random.uniform(0, delay / 2)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date 형식은 무시하고 기본 백오프
