"""The API docs for AIS Counter's own routes in the template's modules: the
About screen's report (meta.py) and the MATLAB path (account.py).
config/openapi.json and config/api.md are written from these by
scripts/api_docs.sh (see app/apidocs)."""
from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from app.apidocs import SESSION_ONLY, Field, doc
from app.routes import account, meta


class GetReportReply(TypedDict):
    markdown: Annotated[str, Field(doc="docs/ais_auto_report.md as it is on disk.")]


doc(
    meta.get_report,
    summary="The ais_auto.m report, as Markdown",
    tag="About",
    description="docs/ais_auto_report.md as {\"markdown\": ...}, for the About screen. Read on every call so an edited report shows without a restart.",
    mcp_http="The About screen's copy of a document in the repository; nothing to act on.",
    reply=GetReportReply,
    errors=(401, 404),
)


class SetMatlabPathBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc="From GET /api/me. Browser sessions only.")]]
    path: Annotated[str, Field(doc="Where MATLAB is on your computer. Empty clears it. No double quotes.")]


class SetMatlabPathReply(TypedDict):
    ok: bool
    path: Annotated[str, Field(doc="As saved, trimmed.")]


doc(
    account.set_matlab_path,
    summary="Set where MATLAB is on your computer",
    tag="Account",
    description="Body: {path}: where MATLAB is on the caller's own computer, written into their replay zips (app/analysis/matlab_bundle.py). Empty clears it. A session only: this value decides what those scripts execute.",
    access=SESSION_ONLY,
    body=SetMatlabPathBody,
    reply=SetMatlabPathReply,
    errors=(400, 401, 403),
)
