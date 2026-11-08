"""The rate limiter (app/core/middleware.py): what it counts, and whose."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.core.middleware import RateLimit
from tests.live_config import fake_holder


async def _ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _limiter(trust: bool = False) -> RateLimit:
    cfg = SimpleNamespace(rate_limit_max=2, rate_limit_window_seconds=60, trust_proxy=trust,
                          trusted_proxies=["127.0.0.1"], proxy_header="CF-Connecting-IP")
    cfg.rate_limit_signin_max = 2
    return RateLimit(_ok, fake_holder(cfg))


def _status(limiter: RateLimit, path: str, method: str = "GET", visitor: str | None = None) -> int:
    headers = [(b"cf-connecting-ip", visitor.encode())] if visitor else []
    scope = {"type": "http", "method": method, "path": path, "headers": headers, "client": ("127.0.0.1", 50000)}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(limiter(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_api_requests_are_limited():
    limiter = _limiter()
    assert [_status(limiter, "/api/ais/batches") for _ in range(3)] == [200, 200, 429]


def test_static_files_are_not_counted():
    limiter = _limiter()
    for _ in range(10):
        assert _status(limiter, "/js/ais.js") == 200
    assert _status(limiter, "/api/me") == 200
    assert _status(limiter, "/js/ais.js", method="POST") == 200
    assert _status(limiter, "/api/me") == 429


def test_each_visitor_behind_a_trusted_proxy_has_their_own_budget():
    limiter = _limiter(trust=True)
    assert [_status(limiter, "/api/me", visitor="203.0.113.5") for _ in range(3)] == [200, 200, 429]
    assert _status(limiter, "/api/me", visitor="198.51.100.7") == 200
    # This Mac itself, no header: its own address.
    assert _status(limiter, "/api/me") == 200


def test_api_answers_are_not_cached_unless_the_route_says_so():
    from app.core.middleware import SecurityHeaders

    async def png(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"cache-control", b"private, max-age=86400")]})
        await send({"type": "http.response.body", "body": b""})

    def cache_control(app, path: str) -> str | None:
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "GET", "path": path, "headers": []}
        asyncio.run(SecurityHeaders(app, fake_holder(SimpleNamespace(secure_cookies=False)))(scope, receive, send))
        headers = dict(next(m["headers"] for m in sent if m["type"] == "http.response.start"))
        value = headers.get(b"cache-control")
        return value.decode() if value else None

    # A 404 for a missing image (Cloudflare would keep it: the URL ends .png).
    assert cache_control(_ok, "/api/ais/files/abc/view.png") == "no-store"
    assert cache_control(png, "/api/ais/files/abc/view.png") == "private, max-age=86400"
    assert cache_control(_ok, "/js/ais.js") is None
