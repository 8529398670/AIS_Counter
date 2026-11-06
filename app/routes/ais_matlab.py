"""The MATLAB helper: Replay in MATLAB from a server that cannot reach the
person's MATLAB, because it runs in Docker or on another machine.

The server has no way to reach a computer, so the helper (helper/) asks: every
few seconds it polls next_job, and when the person clicks Replay their browser
has send queue the run. The helper fetches it as the same zip Download MATLAB
Replay saves, launches MATLAB, and reports back to the request send is holding.

Two rules carry the security of this:
- Only a browser session can queue a run, and only for itself, so neither
  another user nor a stolen helper key can start anything on anyone's computer.
- What is sent is the fixed replay template plus validated numbers and a
  sanitized name; no field of a request reaches MATLAB as code. The helper still
  runs what this server gives it, which is why it has its own switch
  (server.matlab_helper) and the Account screen says so.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from app.analysis import matlab
from app.analysis.images import ImageError
from app.analysis.matlab_jobs import Jobs
from app.core.security import actor_from
from app.models import api_keys, users
from app.routes.ais import _body, _library, bundle_response, matlab_run
from app.routes.helpers import bad_request, error, get_store, not_found, run

# Waiting for a helper that polls every 3 s to pick the job up, then for it to
# download and start MATLAB. Together they stay under the 100 s a proxy such as
# Cloudflare gives a request.
CLAIM_SECONDS = 10
DONE_SECONDS = 70
MESSAGE_MAX = 500
# Longer than a default key: a helper that dies quietly every 90 days would look
# like a broken button.
KEY_DAYS = 365
KEY_NAME = "MATLAB helper"

DIST = Path(__file__).resolve().parents[2] / "helper" / "dist"
# What `uname -s`-`uname -m` says (lowercased), and Go's names, to a build.
TARGETS = {
    "darwin-arm64": "darwin-arm64",
    "darwin-x86_64": "darwin-amd64",
    "darwin-amd64": "darwin-amd64",
    "linux-x86_64": "linux-amd64",
    "linux-amd64": "linux-amd64",
    "linux-aarch64": "linux-arm64",
    "linux-arm64": "linux-arm64",
    "windows-amd64": "windows-amd64",
}


def _jobs(request: Request) -> Jobs:
    return request.app.state.matlab_jobs


async def send(request: Request) -> Response:
    """Body: see matlab_run. Hands the run to the caller's own helper and
    answers with what became of it."""
    body, refused = await _body(request)
    if refused:
        return refused
    wanted, why = matlab_run(body)
    if wanted is None:
        return bad_request(why)
    jobs = _jobs(request)
    user_id = actor_from(request).user.id
    if not jobs.live(user_id):
        return error(409, "the MATLAB helper is not running on your computer")
    try:
        await run(_library(request).file_path, wanted.processed)
        if wanted.raw:
            await run(_library(request).file_path, wanted.raw)
    except ImageError as exc:
        return bad_request(str(exc))
    job = jobs.add(user_id, wanted)
    if job is None:
        return error(409, "MATLAB is already being opened")
    try:
        try:
            await asyncio.wait_for(job.claimed.wait(), CLAIM_SECONDS)
        except TimeoutError:
            return error(409, "the MATLAB helper did not answer")
        try:
            await asyncio.wait_for(job.done.wait(), DONE_SECONDS)
        except TimeoutError:
            return error(409, "the MATLAB helper is taking too long: MATLAB may still open")
    finally:
        jobs.remove(job)
    return JSONResponse({"ok": True}) if job.ok else bad_request(job.message or "the MATLAB helper could not start MATLAB")


async def mint_key(request: Request) -> Response:
    """The Connect button: a key good for the helper's routes and nothing else
    (app/models/api_keys.py). The credential appears here and nowhere else."""
    _, refused = await _body(request)
    if refused:
        return refused
    try:
        credential, _key = await run(api_keys.issue_api_key, get_store(request), actor_from(request).user.id, KEY_NAME,
                                     users.ROLE_USER, KEY_DAYS * 24 * 60 * 60, api_keys.PURPOSE_MATLAB_HELPER)
    except api_keys.APIKeyError as exc:
        return bad_request(str(exc))
    return JSONResponse({"credential": credential}, status_code=201)


async def download(request: Request) -> Response:
    """The helper for one OS and CPU, from helper/build.sh."""
    target = TARGETS.get(request.path_params["platform"].lower())
    if target is None:
        return not_found("no helper for that platform")
    name = f"ais-matlab-helper-{target}" + (".exe" if target.startswith("windows") else "")
    path = DIST / name
    if not path.is_file():
        return not_found("the helper has not been built on this server: run helper/build.sh")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


async def next_job(request: Request) -> Response:
    """Polled by the helper: also how the server knows it is there."""
    jobs = _jobs(request)
    user_id = actor_from(request).user.id
    jobs.see(user_id)
    job = jobs.claim(user_id)
    if job is None:
        return Response(status_code=204)
    return JSONResponse({"id": job.id, "mode": job.run.mode, "cell": matlab.safe_cell(job.run.cell)})


async def job_bundle(request: Request) -> Response:
    """The claimed run's zip, built now rather than held in memory waiting."""
    job = _jobs(request).get(actor_from(request).user.id, request.path_params["job_id"])
    if job is None:
        return not_found("no such job")
    try:
        return await bundle_response(request, job.run)
    except ImageError as exc:
        return bad_request(str(exc))


async def job_done(request: Request) -> Response:
    """Body: {ok, message?}: what the helper did with the job."""
    body, refused = await _body(request)
    if refused:
        return refused
    jobs = _jobs(request)
    job = jobs.get(actor_from(request).user.id, request.path_params["job_id"])
    if job is None:
        return not_found("no such job")
    message = body.get("message")
    jobs.finish(job, body.get("ok") is True, message[:MESSAGE_MAX] if isinstance(message, str) else "")
    return JSONResponse({"ok": True})
