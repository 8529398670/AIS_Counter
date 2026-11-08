"""Who may do what around MATLAB, through the real routes and guards, and the
whole trip from a browser to a helper. MATLAB itself is never started."""
from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.analysis import matlab
from app.core import db, encryption
from app.core.db import BUCKET_SESSIONS
from app.core.static_files import StaticServer
from app.main import build_app
from tests.live_config import real_holder
from app.models import api_keys, sessions, users
from app.routes import ais_matlab

KEY = "0" * 64
SHA = "a" * 64
BODY = {"mode": "replay", "processed": SHA, "cell": "c", "threshold": 0.01, "clicks": [[1.5, 2.5]]}
NEXT = "/api/ais/matlab/helper/next"


class Harness:
    def __init__(self, tmp_path, matlab_helper=True, api_keys_enabled=True):
        self.store = db.open_store(tmp_path / "app.db", KEY, False)
        self.holder = real_holder(
            tmp_path, storage_dir=tmp_path / "storage", api_keys_enabled=api_keys_enabled, mcp_enabled=False,
            matlab_helper=matlab_helper, matlab="",
            local_folders_enabled=False, rate_limit_max=1000, rate_limit_signin_max=1000, rate_limit_window_seconds=60,
            trust_proxy=False, trusted_proxies=(), proxy_header="", body_limit_bytes=1048576, cookie_name="s",
            secret_key=KEY, encrypt_at_rest=False, secure_cookies=False, api_key_ttl_seconds=3600)
        self.cfg = self.holder.get()
        static = tmp_path / "static"
        static.mkdir()
        self.app = build_app(self.holder, self.store, {}, StaticServer(static), "test")
        self.library = self.app.state.ais
        self.users = {}

    def set(self, **changes):
        """Change the running config, as an edit to config.yaml would."""
        self.holder._current = dataclasses.replace(self.holder.get(), **changes)
        self.cfg = self.holder.get()

    def user(self, name="Ada", path="", role=users.ROLE_USER):
        user = users.create_user(self.store, name, role)
        if path:
            users.set_matlab_path(self.store, user.id, path)
        session_id, credential, session = sessions.new_session(user.id, 3600)
        self.store.put(BUCKET_SESSIONS, session_id, session.to_record())
        cookie = encryption.xchacha_encrypt_string(KEY, credential)
        return SimpleNamespace(id=user.id, cookie=f"s={cookie}", csrf=session.csrf_token)

    def key(self, who, purpose=""):
        return api_keys.issue_api_key(self.store, who.id, "k", users.ROLE_USER, 3600, purpose)[0]

    def helper(self, who):
        return self.key(who, api_keys.PURPOSE_MATLAB_HELPER)

    async def call(self, method, path, session=None, key=None, body=None, extra=(), peer="127.0.0.1"):
        headers = [(b"host", b"t"), *extra]
        if session is not None:
            headers.append((b"cookie", session.cookie.encode()))
        if key is not None:
            headers.append((b"authorization", f"Bearer {key}".encode()))
        payload = b""
        if body is not None:
            payload = json.dumps({**body, **({"csrf_token": session.csrf} if session else {})}).encode()
        sent = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                await asyncio.Event().wait()
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": headers,
                 "client": (peer, 5000), "server": ("t", 80)}
        await self.app(scope, receive, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        data = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return SimpleNamespace(status=start["status"], data=data, headers=dict(start["headers"]))

    def get(self, *args, **kw):
        return asyncio.run(self.call(*args, **kw))


@pytest.fixture
def h(tmp_path, monkeypatch):
    harness = Harness(tmp_path)
    monkeypatch.setattr(harness.library, "file_path", lambda sha: tmp_path)
    monkeypatch.setattr(harness.library, "matlab_pair", lambda processed, raw: (b"P", None))
    return harness


def test_the_zip_needs_a_login_and_holds_the_callers_path(h):
    ada = h.user(path="/ada/matlab")
    assert h.get("POST", "/api/ais/matlab/bundle", body=BODY).status == 401
    answer = h.get("POST", "/api/ais/matlab/bundle", session=ada, body=BODY)
    assert answer.status == 200 and answer.headers[b"content-type"] == b"application/zip"
    assert b'filename="c-matlab-replay.zip"' in answer.headers[b"content-disposition"]
    with zipfile.ZipFile(io.BytesIO(answer.data)) as archive:
        assert archive.read("c-matlab-replay/matlab_path.txt") == b"/ada/matlab"


def test_a_non_ascii_cell_downloads(h):
    assert h.get("POST", "/api/ais/matlab/bundle", session=h.user(), body={**BODY, "cell": "β-IV"}).status == 200


@pytest.mark.parametrize("change", [
    {"mode": "shell"}, {"mode": ["replay"]}, {"processed": 1}, {"cell": None}, {"threshold": 2}, {"clicks": None},
    {"clicks": [[1]]}, {"clicks": [[1, 2]] * 3}, {"clicks": [[10 ** 400, 1]]}, {"settings": {"smooth": ["log"]}},
    {"settings": {"smooth": "x'); system('rm')"}}, {"settings": {"kernel": 1e400}},
])
def test_bad_runs_are_refused_not_crashed(h, change):
    assert h.get("POST", "/api/ais/matlab/bundle", session=h.user(), body={**BODY, **change}).status == 400


def test_a_key_can_never_send_a_run(h):
    ada = h.user()
    for key in (h.key(ada), h.helper(ada)):
        assert h.get("POST", "/api/ais/matlab/send", key=key, body=BODY).status in (401, 403)


def test_only_a_helper_key_reaches_the_helper_routes(h):
    ada = h.user()
    assert h.get("GET", NEXT).status == 401
    assert h.get("GET", NEXT, session=ada).status == 403
    assert h.get("GET", NEXT, key=h.key(ada)).status == 403
    assert h.get("GET", NEXT, key=h.helper(ada)).status == 204


def test_a_helper_key_is_nothing_anywhere_else(h):
    key = h.helper(h.user())
    for path in ("/api/me", "/api/ais/batches", "/api/ais/local/status"):
        assert h.get("GET", path, key=key).status == 401
    assert h.get("POST", "/api/ais/matlab/bundle", key=key, body=BODY).status == 401


def test_minting_a_helper_key_needs_a_session(h):
    ada = h.user()
    assert h.get("POST", "/api/ais/matlab/helper/key", key=h.key(ada), body={}).status == 403
    answer = h.get("POST", "/api/ais/matlab/helper/key", session=ada, body={})
    assert answer.status == 201
    key = json.loads(answer.data)["credential"]
    assert h.get("GET", NEXT, key=key).status == 204


@pytest.mark.parametrize("flags", [{"matlab_helper": False}, {"api_keys_enabled": False}])
def test_the_routes_are_absent_when_switched_off(tmp_path, monkeypatch, flags):
    harness = Harness(tmp_path, **flags)
    monkeypatch.setattr(harness.library, "matlab_pair", lambda processed, raw: (b"P", None))
    ada = harness.user()
    assert harness.get("POST", "/api/ais/matlab/send", session=ada, body=BODY).status in (404, 405)
    assert harness.get("POST", "/api/ais/matlab/helper/key", session=ada, body={}).status in (404, 405)
    assert harness.get("GET", NEXT).status == 404
    status = json.loads(harness.get("GET", "/api/ais/local/status", session=ada).data)
    assert status["helper"] is False and status["helper_enabled"] is False
    # The zip does not depend on the helper.
    assert harness.get("POST", "/api/ais/matlab/bundle", session=ada, body=BODY).status == 200


def test_send_refuses_at_once_with_no_helper(h):
    answer = h.get("POST", "/api/ais/matlab/send", session=h.user(), body=BODY)
    assert answer.status == 409 and b"not running" in answer.data


def trip(h, ada, key, report):
    """The browser's send and one helper poll, at the same time."""
    async def go():
        await h.call("GET", NEXT, key=key)            # the helper is there
        sending = asyncio.create_task(h.call("POST", "/api/ais/matlab/send", session=ada, body=BODY))
        for _ in range(100):
            polled = await h.call("GET", NEXT, key=key)
            if polled.status == 200:
                break
            await asyncio.sleep(0.01)
        job = json.loads(polled.data)
        bundle = await h.call("GET", f"/api/ais/matlab/helper/jobs/{job['id']}/bundle", key=key)
        await h.call("POST", f"/api/ais/matlab/helper/jobs/{job['id']}/done", key=key, body=report)
        return job, bundle, await sending
    return asyncio.run(go())


def test_the_whole_trip(h):
    ada = h.user(path="/ada/matlab")
    job, bundle, answer = trip(h, ada, h.helper(ada), {"ok": True})
    assert job["mode"] == "replay" and job["cell"] == "c"
    assert bundle.status == 200 and answer.status == 200
    with zipfile.ZipFile(io.BytesIO(bundle.data)) as archive:
        assert archive.read("c-matlab-replay/matlab_path.txt") == b"/ada/matlab"
    assert h.app.state.matlab_jobs._jobs == {}


def test_a_helper_failure_reaches_the_browser(h):
    ada = h.user()
    _, _, answer = trip(h, ada, h.helper(ada), {"ok": False, "message": "MATLAB was not found"})
    assert answer.status == 400 and b"MATLAB was not found" in answer.data


def test_no_helper_reaches_another_users_job(h):
    ada, bob = h.user("Ada"), h.user("Bob")
    ada_key, bob_key = h.helper(ada), h.helper(bob)

    async def go():
        await h.call("GET", NEXT, key=ada_key)
        sending = asyncio.create_task(h.call("POST", "/api/ais/matlab/send", session=ada, body=BODY))
        await asyncio.sleep(0.05)
        assert (await h.call("GET", NEXT, key=bob_key)).status == 204
        job = json.loads((await h.call("GET", NEXT, key=ada_key)).data)
        path = f"/api/ais/matlab/helper/jobs/{job['id']}"
        assert (await h.call("GET", path + "/bundle", key=bob_key)).status == 404
        assert (await h.call("POST", path + "/done", key=bob_key, body={"ok": True})).status == 404
        await h.call("POST", path + "/done", key=ada_key, body={"ok": True})
        await sending

    asyncio.run(go())


def test_an_unclaimed_job_goes_when_the_wait_ends(h, monkeypatch):
    monkeypatch.setattr(ais_matlab, "CLAIM_SECONDS", 0.01)
    ada = h.user()
    key = h.helper(ada)

    async def go():
        await h.call("GET", NEXT, key=key)
        answer = await h.call("POST", "/api/ais/matlab/send", session=ada, body=BODY)
        assert answer.status == 409 and b"did not answer" in answer.data
        # A helper arriving now must not open MATLAB after that answer.
        assert (await h.call("GET", NEXT, key=key)).status == 204

    asyncio.run(go())


def test_the_saved_path_never_reaches_the_servers_launcher(h, monkeypatch):
    launched = []
    monkeypatch.setattr(matlab.subprocess, "Popen", lambda *a, **k: launched.append(a))
    ada = h.user(path="/evil/matlab")
    h.get("POST", "/api/ais/local/matlab", session=ada, body=BODY)
    h.get("POST", "/api/ais/matlab/bundle", session=ada, body=BODY)
    assert launched == []


@pytest.fixture
def host(h, monkeypatch):
    """A server that can open its own MATLAB. Nothing here starts it."""
    h.set(local_folders_enabled=True)
    h.launched = []
    monkeypatch.setattr(matlab, "find_matlab", lambda configured: "/x/matlab")
    monkeypatch.setattr(matlab, "stage", lambda *a: Path("/run/stem"))
    monkeypatch.setattr(matlab, "launch", lambda *a: h.launched.append(a))
    return h


TUNNEL = [(b"cf-connecting-ip", b"203.0.113.5")]


def test_a_browser_on_this_computer_gets_the_servers_matlab(host):
    admin = host.user(role=users.ROLE_ADMIN)
    assert json.loads(host.get("GET", "/api/ais/local/status", session=admin).data)["matlab"] is True
    assert host.get("POST", "/api/ais/local/matlab", session=admin, body=BODY).status == 200
    assert len(host.launched) == 1


@pytest.mark.parametrize("away", [
    {"extra": TUNNEL},
    {"extra": [(b"x-forwarded-for", b"203.0.113.5")]},
    {"extra": [(b"x-real-ip", b"203.0.113.5")]},
    {"extra": [(b"forwarded", b"for=203.0.113.5")]},
    {"extra": [(b"cf-connecting-ip", b"127.0.0.1")]},
    {"peer": "192.168.1.20"},
    {"peer": "unknown"},
])
def test_anyone_else_is_not_offered_it_and_cannot_start_it(host, away):
    admin = host.user(role=users.ROLE_ADMIN)
    status = json.loads(host.get("GET", "/api/ais/local/status", session=admin, **away).data)
    assert status["matlab"] is False and status["enabled"] is True
    assert host.get("POST", "/api/ais/local/matlab", session=admin, body=BODY, **away).status == 403
    assert host.launched == []


def test_the_configured_proxy_header_counts_too(host):
    host.set(proxy_header="X-Visitor")
    admin = host.user(role=users.ROLE_ADMIN)
    answer = host.get("GET", "/api/ais/local/status", session=admin, extra=[(b"x-visitor", b"203.0.113.5")])
    assert json.loads(answer.data)["matlab"] is False


def test_a_remote_visitor_with_a_helper_keeps_replay(host):
    admin = host.user(role=users.ROLE_ADMIN)
    host.get("GET", NEXT, key=host.helper(admin))
    status = json.loads(host.get("GET", "/api/ais/local/status", session=admin, extra=TUNNEL).data)
    assert status["matlab"] is False and status["helper"] is True


def test_the_account_path_is_session_only(h):
    ada = h.user(path="/ada/matlab")
    key = h.key(ada)
    assert h.get("POST", "/api/account/matlab", key=key, body={"path": "/x"}).status == 403
    assert b"matlab_path" not in h.get("GET", "/api/me", key=key).data
    assert json.loads(h.get("GET", "/api/me", session=ada).data)["matlab_path"] == "/ada/matlab"
    assert h.get("POST", "/api/account/matlab", session=ada, body={"path": 'a"b'}).status == 400
    assert h.get("POST", "/api/account/matlab", session=ada, body={"path": " /new "}).status == 200
    assert users.get_user(h.store, ada.id).matlab_path == "/new"


def test_the_download_is_allowlisted(h, tmp_path, monkeypatch):
    ada = h.user()
    monkeypatch.setattr(ais_matlab, "DIST", tmp_path)
    (tmp_path / "ais-matlab-helper-darwin-arm64").write_bytes(b"BIN")
    base = "/api/ais/matlab/helper/download/"
    assert h.get("GET", base + "Darwin-arm64").status == 401
    assert h.get("GET", base + "Darwin-arm64", session=ada).data == b"BIN"
    assert h.get("GET", base + "Darwin-arm64", key=h.helper(ada)).data == b"BIN"
    assert h.get("GET", base + "linux-x86_64", session=ada).status == 404
    assert h.get("GET", base + "..%2f..%2fapp.db", session=ada).status == 404
