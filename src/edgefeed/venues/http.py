"""Shared async HTTP: per-venue rate limit, retries with jittered backoff, Retry-After, metrics."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from edgefeed import metrics

USER_AGENT = "edgefeed/0.2 (+https://github.com/Kage7047/edgefeed)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class VenueError(RuntimeError):
    pass


class NotFound(VenueError):
    pass


class ClientError(VenueError):
    """A 4xx other than 404/429: the request itself is wrong, retrying will not help."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class RateLimiter:
    """At most ``rate`` requests per second, smoothed (one slot every 1/rate seconds)."""

    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class VenueHTTP:
    def __init__(
        self,
        venue: str,
        base_url: str,
        *,
        rate: float = 8.0,
        retries: int = 3,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.venue = venue
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.limiter = RateLimiter(rate)
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kw: Any) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            await self.limiter.wait()
            t0 = time.perf_counter()
            try:
                resp = await self._client.request(method, url, **kw)
            except httpx.TransportError as e:
                last = e
                metrics.http_requests.labels(self.venue, "error").inc()
            else:
                metrics.http_latency.labels(self.venue).observe(time.perf_counter() - t0)
                metrics.http_requests.labels(self.venue, str(resp.status_code)).inc()
                if resp.status_code == 404:
                    raise NotFound(f"{self.venue} 404: {url}")
                if 400 <= resp.status_code < 500 and resp.status_code not in RETRY_STATUS:
                    raise ClientError(resp.status_code, f"{self.venue} {resp.status_code}: {url}")
                if resp.status_code not in RETRY_STATUS:
                    resp.raise_for_status()
                    return resp.json()
                last = VenueError(f"{self.venue} {resp.status_code}: {url}")
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit() and attempt < self.retries:
                    await asyncio.sleep(min(float(retry_after), 30.0))
                    continue
            if attempt < self.retries:
                await asyncio.sleep((2**attempt) * 0.4 + random.uniform(0, 0.3))
        raise VenueError(f"{self.venue}: gave up on {url}: {last}")

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params or None)

    async def post(self, path: str, payload: Any) -> Any:
        return await self.request("POST", path, json=payload)
