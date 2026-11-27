"""Thin, strictly sequential Lichess API client.

Lichess asks for one request at a time and a full minute of back-off on HTTP 429.
All requests go through a single lock; ndjson responses are streamed line by line.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://lichess.org"
USER_AGENT = "chess-coach/0.1 (+https://github.com/netangel/chess-coach)"
RATE_LIMIT_SLEEP = 60.0
MAX_RETRIES = 3


class LichessError(RuntimeError):
    pass


class RateLimited(LichessError):
    pass


class LichessClient:
    _lock = threading.Lock()  # process-wide: never two requests in flight

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 60.0,
    ) -> None:
        headers = {"User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.has_token = bool(token)
        self._token = token
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            transport=transport,
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LichessClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- core ---------------------------------------------------------------

    @contextmanager
    def _request(self, method: str, path: str, **kwargs: Any) -> Iterator[httpx.Response]:
        """Open a (streamed) response, retrying on 429 with a 60 s sleep."""
        with self._lock:
            for attempt in range(MAX_RETRIES + 1):
                req = self._http.build_request(method, path, **kwargs)
                resp = self._http.send(req, stream=True)
                if resp.status_code == 429:
                    resp.close()
                    if attempt == MAX_RETRIES:
                        raise RateLimited(f"{method} {path}: still rate limited after retries")
                    log.warning("429 on %s %s, sleeping %.0fs", method, path, RATE_LIMIT_SLEEP)
                    self._sleep(RATE_LIMIT_SLEEP)
                    continue
                try:
                    if resp.status_code >= 400:
                        resp.read()
                        raise LichessError(
                            f"{method} {path}: HTTP {resp.status_code}: {resp.text[:300]}"
                        )
                    yield resp
                finally:
                    resp.close()
                return

    # -- helpers ------------------------------------------------------------

    def stream_ndjson_lines(self, path: str, params: dict[str, Any] | None = None) -> Iterator[str]:
        """Yield raw non-empty ndjson lines (unparsed, to store exactly as returned)."""
        with self._request(
            "GET", path, params=_clean(params), headers={"Accept": "application/x-ndjson"}
        ) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if line:
                    yield line

    def stream_ndjson(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        for line in self.stream_ndjson_lines(path, params):
            yield json.loads(line)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        with self._request(
            "GET", path, params=_clean(params), headers={"Accept": "application/json"}
        ) as resp:
            resp.read()
            return resp.json()

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        with self._request("GET", path, params=_clean(params)) as resp:
            resp.read()
            return resp.text

    def post_form(self, path: str, data: dict[str, Any]) -> Any:
        with self._request("POST", path, data=_clean(data)) as resp:
            resp.read()
            return resp.json() if resp.content else None

    def token_info(self) -> dict | None:
        """Scopes and expiry of our own token (POST /api/token/test, body = the token)."""
        if not self._token:
            return None
        with self._request("POST", "/api/token/test", content=self._token) as resp:
            resp.read()
            return (resp.json() or {}).get(self._token)

    def delete(self, path: str) -> None:
        with self._request("DELETE", path) as resp:
            resp.read()


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop None values and render booleans the way Lichess expects."""
    if params is None:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else v
    return out
