"""AIS analysis: batches of TIFFs shared by every signed-in user, each click
on an image one POST that runs the ais_auto.m port (app/analysis/), and the
accepted AIS stored with their batch (app/models/ais.py).

Uploads are JSON like every other POST here (base64 file + CSRF token), with a
larger body limit on that one route; a TIFF pair is ~6 MB. A batch is created
from names and sha-256s alone (the browser hashes its files first), so the
duplicates and the shareable link exist before a single file is uploaded.
"""
from __future__ import annotations

import base64
import binascii
import math
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.analysis import ais_auto as aa
from app.analysis import detect as auto
from app.analysis import local, matlab
from app.analysis.images import ImageError
from app.analysis.service import Library
from app.core.security import actor_from, check_csrf
from app.models import ais as batches
from app.models import users
from app.routes.helpers import bad_request, forbidden, get_config, get_store, not_found, parse_id, read_json, run

UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024


def _library(request: Request) -> Library:
    return request.app.state.ais


def _user_id(request: Request) -> int:
    return actor_from(request).user.id


async def _body(request: Request) -> tuple[dict[str, Any] | None, Response | None]:
    body = await read_json(request)
    if body is None:
        return None, bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return None, forbidden("invalid csrf token")
    return body, None


async def upload(request: Request) -> Response:
    body, refused = await _body(request)
    if refused:
        return refused
    data = body.get("data")
    if not isinstance(data, str):
        return bad_request("data must be a base64 string")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return bad_request("data must be a base64 string")
    try:
        info = await run(_library(request).add, raw)
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse(info)


async def view(request: Request) -> Response:
    try:
        png = await run(_library(request).preview, request.path_params["sha"])
    except ImageError as exc:
        return not_found(str(exc))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def channels(request: Request) -> Response:
    """A .czi's channels [{index, name, color}] for the channel buttons; [] for a TIFF."""
    try:
        found = await run(_library(request).channels, request.path_params["sha"])
    except ImageError as exc:
        return not_found(str(exc))
    return JSONResponse({"channels": found}, headers={"Cache-Control": "private, max-age=86400"})


async def somata(request: Request) -> Response:
    """A .czi's soma outlines (soma.py), each its edge pixels as 1-based [x, y],
    for the Soma button; [] for a TIFF."""
    try:
        found = await run(_library(request).soma, request.path_params["sha"])
    except ImageError as exc:
        return not_found(str(exc))
    return JSONResponse({"somata": found.outlines if found else []}, headers={"Cache-Control": "private, max-age=86400"})


async def channel(request: Request) -> Response:
    try:
        index = int(request.path_params["index"])
        png = await run(_library(request).channel_png, request.path_params["sha"], index)
    except (ImageError, ValueError) as exc:
        return not_found(str(exc))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def thumb(request: Request) -> Response:
    try:
        png = await run(_library(request).thumbnail, request.path_params["sha"])
    except ImageError as exc:
        return not_found(str(exc))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


def _point(value: Any) -> tuple[float, float] | None:
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        return float(value[0]), float(value[1])
    return None


def _threshold(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        return None
    return float(value)


def _settings(value: Any) -> tuple[aa.Settings | None, str]:
    """The method settings a body carries (app/analysis/ais_auto.Settings);
    missing ones are the original's. (None, why) when one is bad."""
    try:
        return aa.Settings.from_dict(value), ""
    except ValueError as exc:
        return None, str(exc)


async def trace(request: Request) -> Response:
    """Body: {processed, raw?, click: [x, y], click2?: [x, y], threshold?,
    settings?: {smooth, kernel, sigma, ...}}.
    Clicks are MATLAB axes coordinates (x = column, y = row, pixel centres at
    1..n). click2 stands in for the second ginput after re-thresholding; by
    default the first click is used again. threshold defaults to 0.01, what
    the original was called with (0 means Otsu, as in the original)."""
    body, refused = await _body(request)
    if refused:
        return refused
    processed, raw = body.get("processed"), body.get("raw")
    click, click2 = _point(body.get("click")), _point(body.get("click2"))
    threshold = _threshold(body.get("threshold", 0.01))
    if not isinstance(processed, str) or (raw is not None and not isinstance(raw, str)):
        return bad_request("processed (and raw) must be image ids")
    if click is None or (body.get("click2") is not None and click2 is None):
        return bad_request("click must be [x, y]")
    if threshold is None:
        return bad_request("threshold must be between 0 and 1")
    settings, why = _settings(body.get("settings"))
    if settings is None:
        return bad_request(why)
    try:
        result = await run(_library(request).trace, processed, raw, click, click2, threshold, settings)
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse(result)


def _traces(value: Any) -> list[list[list[int]]] | None:
    """A list of traces, each a list of [x, y] whole-number pixels."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1000:
        return None
    for trace in value:
        if (not isinstance(trace, list) or len(trace) > 20000
                or not all(isinstance(p, list) and len(p) == 2
                           and all(isinstance(c, int) and not isinstance(c, bool) for c in p) for p in trace)):
            return None
    return value


async def detect(request: Request) -> Response:
    """Auto mode. Body: {processed, raw?, threshold?, settings?, start?,
    exclude?: [[[x, y], ...], ...]}. Every AIS found on the image without a
    click (app/analysis/detect.py); start is both | brighter | dimmer | soma
    (a .czi only) | fitted | fitted2, exclude the traces already accepted on it."""
    body, refused = await _body(request)
    if refused:
        return refused
    processed, raw = body.get("processed"), body.get("raw")
    threshold = _threshold(body.get("threshold", 0.01))
    start = body.get("start", "both")
    exclude = _traces(body.get("exclude"))
    if not isinstance(processed, str) or (raw is not None and not isinstance(raw, str)):
        return bad_request("processed (and raw) must be image ids")
    if threshold is None:
        return bad_request("threshold must be between 0 and 1")
    if start not in auto.STARTS:
        return bad_request("start must be one of " + ", ".join(auto.STARTS))
    if exclude is None:
        return bad_request("exclude must be lists of [x, y] pixels")
    settings, why = _settings(body.get("settings"))
    if settings is None:
        return bad_request(why)
    try:
        result = await run(_library(request).detect, processed, raw, threshold, settings, start, exclude)
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse(result)


# --- batches and results (app/models/ais.py) ---------------------------------


def _names(request: Request) -> dict[int, str]:
    return {u.id: u.display_name for u in users.list_users(get_store(request))}


def _has(request: Request) -> Callable[[dict[str, Any]], bool]:
    """Whether the server can show a batch's file: it has the bytes, or (while
    local folders are allowed) knows where on this machine it lives."""
    library = _library(request)
    by_path = get_config(request).local_folders_enabled
    return lambda f: bool(by_path and f.get("path")) or library.has(f["sha"])


def _batch_json(request: Request, batch: dict[str, Any]) -> dict[str, Any]:
    """The batch with, per file, whether the server can show it already."""
    has = _has(request)
    images = []
    for image in batch["images"]:
        files = {role: f | {"stored": has(f)} for role, f in image["files"].items()}
        images.append(image | {"files": files})
    names = _names(request)
    assigned = {share["user_id"] for share in (batch.get("assignment") or {}).get("shares", [])}
    return batch | {"images": images, "created_by_name": names.get(batch["created_by"], ""),
                    "assignee_names": {str(u): names.get(u, "") for u in assigned}}


def _activity(request: Request) -> batches.Activity:
    return request.app.state.ais_activity


async def batch_list(request: Request) -> Response:
    """Every batch with its progress: uploads, completion, per assignee, and
    any auto run going on (the Batches screen polls this as its monitor)."""
    rows = await run(batches.list_batches, get_store(request), _user_id(request), _has(request))
    names = await run(_names, request)
    live = _activity(request).current()
    for row in rows:
        row["created_by_name"] = names.get(row["created_by"], "")
        for a in row["assignees"]:
            a["name"] = names.get(a["user_id"], "")
        row["activity"] = [a | {"name": names.get(a["user_id"], "")} for a in live.get(row["id"], [])]
    return JSONResponse({"batches": rows})


async def batch_create(request: Request) -> Response:
    """Body: {name}: an empty batch, its images added afterwards."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.new_batch, get_store(request), body.get("name"), "upload", _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(await run(_batch_json, request, batch))


async def _own_batch(request: Request) -> tuple[dict[str, Any] | None, Response | None]:
    """The batch in the path, if whoever asks opened it or is an admin."""
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, get_store(request), batch_id) if batch_id else None
    if batch is None:
        return None, not_found("no such batch")
    actor = actor_from(request)
    if batch["created_by"] != actor.user.id and not actor.is_admin:
        return None, forbidden("only whoever opened the batch, or an admin, can change it")
    return batch, None


async def batch_rename(request: Request) -> Response:
    """Body: {name}. Its accepted AIS carry the new name too."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch, refused = await _own_batch(request)
    if refused:
        return refused
    try:
        renamed = await run(batches.rename_batch, get_store(request), batch["id"], body.get("name"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if renamed is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, renamed))


async def batch_archive(request: Request) -> Response:
    """Body: {archived}: archive the batch (hidden, results kept) or bring it back."""
    body, refused = await _body(request)
    if refused:
        return refused
    if not isinstance(body.get("archived"), bool):
        return bad_request("archived is required")
    batch, refused = await _own_batch(request)
    if refused:
        return refused
    archived = await run(batches.archive_batch, get_store(request), batch["id"], body["archived"])
    if archived is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, archived))


async def batch_order(request: Request) -> Response:
    """Body: {ids}: the team's priority order, first on top (admins)."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        await run(batches.order_batches, get_store(request), body.get("ids"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse({"ok": True})


async def batch_add(request: Request) -> Response:
    """Body: {files: [{name, rel, sha, size}]}: more files picked in the
    browser for an existing batch. Upload them afterwards as for a new one."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        batch = await run(batches.add_files, get_store(request), batch_id, "upload", body.get("files"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, batch))


async def batch_status(request: Request) -> Response:
    """Per image: files on the server, accepted AIS, done, duplicate, assignee."""
    store = get_store(request)
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, store, batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    rows = await run(batches.list_results, store, batch_id)
    images = await run(batches.image_status, batch, rows, _has(request))
    names = await run(_names, request)
    for image in images:
        image["assignee_name"] = names.get(image["assignee"], "") if image["assignee"] else ""
    return JSONResponse({"id": batch["id"], "images": images})


async def batch_activity(request: Request) -> Response:
    """Body: {kind: "auto", state, done, total}: how far this person's auto
    run on the batch has got, so everyone's Batches screen can show it."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        item = _activity(request).report(batch_id, _user_id(request), body)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(item)


async def batch_get(request: Request) -> Response:
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, get_store(request), batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, batch))


async def batch_upload(request: Request) -> Response:
    """Body: {name, files: [{name, rel, sha, size}]} -- a folder picked in the
    browser, hashed there. Upload the files afterwards with POST /api/ais/files."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.create_batch, get_store(request), body.get("name"), "upload",
                          body.get("files"), _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(await run(_batch_json, request, batch))


async def batch_delete(request: Request) -> Response:
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, store, batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    actor = actor_from(request)
    if batch["created_by"] != actor.user.id and not actor.is_admin:
        return forbidden("only whoever opened the batch, or an admin, can delete it")
    await run(batches.delete_batch, store, batch_id)
    return JSONResponse({"ok": True})


async def batch_done(request: Request) -> Response:
    """Body: {image, done}: mark an image done by hand (shared progress)."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id or not isinstance(body.get("image"), str) or not isinstance(body.get("done"), bool):
        return bad_request("image and done are required")
    try:
        batch = await run(batches.set_done, get_store(request), batch_id, body["image"], body["done"])
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse({"skipped": batch["skipped"]})


async def batch_reset(request: Request) -> Response:
    """Body: {scope: all | auto}: delete the batch's results (admins), to run
    it again. The Batches screen offers a backup export first."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        out = await run(batches.reset_batch, get_store(request), batch_id, body.get("scope"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if out is None:
        return not_found("no such batch")
    batch, deleted = out
    return JSONResponse({"batch": await run(_batch_json, request, batch), "deleted": deleted})


async def batch_assign(request: Request) -> Response:
    """Body: {shares: [{user_id, percent}]}: split the batch among these
    people (admins). An empty list clears the assignment."""
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    shares = body.get("shares")
    enabled = {u.id for u in await run(users.list_users, store) if not u.disabled}
    if isinstance(shares, list) and any(isinstance(s, dict) and s.get("user_id") not in enabled for s in shares):
        return bad_request("every share must be an enabled user")
    try:
        batch = await run(batches.assign, store, batch_id, shares, _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, batch))


async def _may_change(request: Request, row: dict[str, Any]) -> bool:
    """Whoever accepted it, the image's assignee, or an admin."""
    actor = actor_from(request)
    if row["created_by"] == actor.user.id or actor.is_admin:
        return True
    batch = await run(batches.get_batch, get_store(request), row["batch_id"])
    return batch is not None and batches.assignee_of(batch, row["image"]) == actor.user.id


async def result_list(request: Request) -> Response:
    """?batch=<id> for one batch, anything else for all."""
    batch_id = parse_id(request.query_params.get("batch", ""))
    rows = await run(batches.list_results, get_store(request), batch_id)
    return JSONResponse({"results": rows})


async def result_add(request: Request) -> Response:
    """Body: {batch_id, image, row} with row the accepted trace's numbers."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = body.get("batch_id")
    if not isinstance(batch_id, int) or isinstance(batch_id, bool) or not isinstance(body.get("image"), str):
        return bad_request("batch_id and image are required")
    try:
        row = await run(batches.add_result, get_store(request), batch_id, body["image"], body.get("row"),
                        _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(row)


async def result_delete(request: Request) -> Response:
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    result_id = parse_id(request.path_params["result_id"])
    row = await run(batches.get_result, store, result_id) if result_id else None
    if row is None:
        return not_found("no such result")
    if not await _may_change(request, row):
        return forbidden("only whoever accepted it, the image's assignee, or an admin, can delete it")
    renumbered = await run(batches.delete_result, store, result_id)
    return JSONResponse({"ok": True, "renumbered": renumbered})


async def result_update(request: Request) -> Response:
    """Body: {row}: an accepted AIS traced again (the Edit tool). It keeps its
    number and origin."""
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    result_id = parse_id(request.path_params["result_id"])
    row = await run(batches.get_result, store, result_id) if result_id else None
    if row is None:
        return not_found("no such result")
    if not await _may_change(request, row):
        return forbidden("only whoever accepted it, the image's assignee, or an admin, can change it")
    try:
        updated = await run(batches.update_result, store, result_id, body.get("row"), _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if updated is None:
        return not_found("no such result")
    return JSONResponse(updated)


async def result_import(request: Request) -> Response:
    """Body: {name, rows}: results kept in a browser before they lived here."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.import_rows, get_store(request), body.get("rows"), _user_id(request),
                          body.get("name") or "Imported from browser")
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse({"batch_id": batch["id"]})


# --- folders on this machine (app/analysis/local.py) ------------------------
#
# Registered for admins with a browser session only, and each call checks
# Config.local_folders_enabled, which is off unless the server listens on
# loopback outside the container.


async def local_status(request: Request) -> Response:
    actor = actor_from(request)
    cfg = get_config(request)
    enabled = bool(cfg.local_folders_enabled and actor.is_admin and actor.session is not None)
    found = enabled and matlab.find_matlab(cfg.matlab) is not None
    return JSONResponse({"enabled": enabled, "platform": local.platform(), "matlab": found})


async def _local_body(request: Request) -> tuple[dict[str, Any] | None, Response | None]:
    if not get_config(request).local_folders_enabled:
        return None, forbidden("local folders are switched off")
    return await _body(request)


async def local_list(request: Request) -> Response:
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        return JSONResponse(await run(local.listing, body.get("path")))
    except ImageError as exc:
        return bad_request(str(exc))


async def batch_path(request: Request) -> Response:
    """Body: {path}: an Open-path batch, hashed and recorded by the server."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        folder, files = await run(local.hashed_files, body.get("path"))
        name = folder.rstrip("/\\").replace("\\", "/").split("/")[-1] or folder
        batch = await run(batches.create_batch, get_store(request), name, "path", files, _user_id(request), folder)
    except (ImageError, batches.BatchError) as exc:
        return bad_request(str(exc))
    return JSONResponse(await run(_batch_json, request, batch))


async def batch_add_path(request: Request) -> Response:
    """Body: {path}: a folder on this machine added to an existing batch."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        folder, files = await run(local.hashed_files, body.get("path"))
        batch = await run(batches.add_files, get_store(request), batch_id, "path", files, folder)
    except (ImageError, batches.BatchError) as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, batch))


async def local_reveal(request: Request) -> Response:
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        await run(local.reveal, body.get("path"))
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse({"ok": True})


async def local_open(request: Request) -> Response:
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        await run(local.open_file, body.get("path"))
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse({"ok": True})


async def local_choose(request: Request) -> Response:
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        path = await run(local.choose)
    except ImageError as exc:
        return bad_request(str(exc))
    return JSONResponse({"path": path, "cancelled": path is None})


async def local_matlab(request: Request) -> Response:
    """Body: {mode: open|run|replay, processed, raw?, cell, threshold?,
    settings?, clicks?: [[x, y], ...]}. Starts MATLAB's desktop on the original
    ais_auto.m for that image (app/analysis/matlab.py). processed is the
    traced image's id, raw the profile image's when the cell has both."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    mode = body.get("mode", "run")
    processed, raw, cell = body.get("processed"), body.get("raw"), body.get("cell")
    threshold = _threshold(body.get("threshold", 0.01))
    if mode not in matlab.MODES:
        return bad_request("mode must be open, run or replay")
    if not isinstance(processed, str) or (raw is not None and not isinstance(raw, str)) or not isinstance(cell, str):
        return bad_request("processed, raw and cell must be strings")
    if threshold is None:
        return bad_request("threshold must be between 0 and 1")
    settings, why = _settings(body.get("settings"))
    if settings is None:
        return bad_request(why)
    clicks = None
    if mode == "replay":
        raw_clicks = body.get("clicks")
        clicks = [_point(c) for c in raw_clicks] if isinstance(raw_clicks, list) and 1 <= len(raw_clicks) <= 2 else None
        if not clicks or None in clicks:
            return bad_request("replay needs one or two clicks as [x, y]")
    cfg = get_config(request)
    binary = matlab.find_matlab(cfg.matlab)
    if binary is None:
        return bad_request("MATLAB not found: set server.matlab in config.yaml")
    library = _library(request)
    user = _user_id(request)
    try:
        processed_tiff, raw_tiff = await run(library.matlab_pair, processed, raw)
        stem = await run(matlab.stage, cfg.storage_dir / "ais-matlab" / str(int(user)), cell, processed_tiff, raw_tiff)
        await run(matlab.launch, binary, mode, stem, threshold, clicks, settings)
    except ImageError as exc:
        return bad_request(str(exc))
    except OSError as exc:
        return bad_request(f"could not start MATLAB: {exc.strerror or exc}")
    return JSONResponse({"ok": True, "folder": str(stem.parent), "matlab": binary})
