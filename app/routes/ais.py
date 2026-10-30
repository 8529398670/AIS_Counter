"""AIS analysis: the browser uploads its TIFFs once, then each click on an
image is one POST that runs the ais_auto.m port (app/analysis/) and returns
the trace and measures.

Uploads are JSON like every other POST here (base64 file + CSRF token), with a
larger body limit on that one route; a TIFF pair is ~6 MB.
"""
from __future__ import annotations

import base64
import binascii
import math
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.analysis.images import ImageError
from app.analysis.service import Library
from app.core.security import actor_from, check_csrf
from app.routes.helpers import bad_request, forbidden, not_found, read_json, run

UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024


def _library(request: Request) -> Library:
    return request.app.state.ais


def _user_id(request: Request) -> int:
    return actor_from(request).user.id


async def upload(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    data = body.get("data")
    if not isinstance(data, str):
        return bad_request("data must be a base64 string")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return bad_request("data must be a base64 string")
    try:
        info = await run(_library(request).add, _user_id(request), raw)
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse(info)


async def view(request: Request) -> Response:
    try:
        png = await run(_library(request).preview, _user_id(request), request.path_params["sha"])
    except ImageError:
        return not_found("unknown image")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


def _point(value: Any) -> tuple[float, float] | None:
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        return float(value[0]), float(value[1])
    return None


async def trace(request: Request) -> Response:
    """Body: {processed, raw?, click: [x, y], click2?: [x, y], threshold?}.
    Clicks are MATLAB axes coordinates (x = column, y = row, pixel centres at
    1..n). click2 stands in for the second ginput after re-thresholding; by
    default the first click is used again. threshold defaults to 0.01, what
    the original was called with (0 means Otsu, as in the original)."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    processed, raw = body.get("processed"), body.get("raw")
    click, click2 = _point(body.get("click")), _point(body.get("click2"))
    threshold = body.get("threshold", 0.01)
    if not isinstance(processed, str) or (raw is not None and not isinstance(raw, str)):
        return bad_request("processed (and raw) must be image ids")
    if click is None or (body.get("click2") is not None and click2 is None):
        return bad_request("click must be [x, y]")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 1:
        return bad_request("threshold must be between 0 and 1")
    try:
        result = await run(_library(request).trace, _user_id(request), processed, raw, click, click2, float(threshold))
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse(result)
