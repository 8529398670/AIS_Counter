"""The API docs for ais_matlab.py's routes (the MATLAB helper): config/openapi.json
and config/api.md are written from these by scripts/api_docs.sh (see app/apidocs)."""
from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from app.apidocs import KEY_ONLY, SESSION_ONLY, Field, doc
from app.routes import ais_matlab
from app.routes.ais_results_api import MatlabRunBody


class SendReply(TypedDict):
    ok: bool


doc(
    ais_matlab.send,
    summary="Send a MATLAB run to your helper",
    tag="AIS",
    description="Body: see matlab_run. Hands the run to the caller's own helper and answers with what became of it.",
    access=SESSION_ONLY,
    body=MatlabRunBody,
    reply=SendReply,
    errors=(400, 401, 403, 409),
)


class MintKeyBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc="From GET /api/me. Browser sessions only.")]]


class MintKeyReply(TypedDict):
    credential: Annotated[str, Field(doc="The helper's key, sent as Authorization: Bearer. Shown only here: treat it like a password.")]


doc(
    ais_matlab.mint_key,
    summary="Make a MATLAB helper key",
    tag="AIS",
    description="The Connect button: a key good for the helper's routes and nothing else (app/models/api_keys.py). The credential appears here and nowhere else.",
    access=SESSION_ONLY,
    body=MintKeyBody,
    status=201,
    reply=MintKeyReply,
    errors=(400, 401, 403),
)


class DownloadParams(TypedDict):
    platform: Annotated[str, Field(path="platform", enum=tuple(ais_matlab.TARGETS), doc="`uname -s`-`uname -m`, lowercased, or Go's name for it.")]


doc(
    ais_matlab.download,
    summary="The helper for one OS and CPU, from helper/build.sh",
    tag="AIS",
    description="The helper for one OS and CPU, from helper/build.sh.",
    mcp_http="The MATLAB helper program itself, a download for a person's computer.",
    params=DownloadParams,
    reply_type="application/octet-stream",
    errors=(401, 404),
)


class NextJobReply(TypedDict):
    id: Annotated[str, Field(doc="The job's id, for its bundle and done routes.")]
    mode: Annotated[str, Field(enum=("open", "run", "replay"))]
    cell: Annotated[str, Field(doc="The cell's name, safe as a file name.")]


doc(
    ais_matlab.next_job,
    summary="The helper's next run",
    tag="AIS",
    description="Polled by the helper: also how the server knows it is there.",
    access=KEY_ONLY,
    mcp_http="Called by the MATLAB helper program, not by agents.",
    reply=NextJobReply,
    reply_description="The run to open, now claimed. 204 with no body when there is none.",
    errors=(401, 403),
)


class JobParams(TypedDict):
    job_id: Annotated[str, Field(path="job_id")]


doc(
    ais_matlab.job_bundle,
    summary="The claimed run's zip, built now rather than held in memory waiting",
    tag="AIS",
    description="The claimed run's zip, built now rather than held in memory waiting.",
    access=KEY_ONLY,
    mcp_http="Called by the MATLAB helper program, not by agents; the bundle is a zip.",
    params=JobParams,
    reply_type="application/zip",
    errors=(400, 401, 403, 404),
)


class JobDoneBody(TypedDict):
    ok: Annotated[bool, Field(doc="Whether MATLAB started.")]
    message: NotRequired[Annotated[str, Field(doc="Why not, shown to the person. Cut to 500 characters.")]]


class JobDoneReply(TypedDict):
    ok: bool


doc(
    ais_matlab.job_done,
    summary="Report what the helper launched",
    tag="AIS",
    description="Body: {ok, message?}: what the helper did with the job.",
    access=KEY_ONLY,
    mcp_http="Called by the MATLAB helper program, not by agents.",
    params=JobParams,
    body=JobDoneBody,
    reply=JobDoneReply,
    errors=(400, 401, 403, 404),
)
