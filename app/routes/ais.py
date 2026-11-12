"""AIS analysis: batches of TIFFs shared by every signed-in user, each click
on an image one POST that runs the ais_auto.m port (app/analysis/), and the
accepted AIS stored with their batch (app/models/ais.py).

Uploads are a file's raw bytes (CSRF token in a header), or JSON like every
other POST here (base64 file + CSRF token), with a larger body limit on that
one route; a TIFF pair is ~6 MB. A batch is created
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
from app.analysis import auto_params as ap
from app.analysis import auto_runner, compare, local, matlab, matlab_bundle, pairing, report, zlength
from app.analysis import channels as views
from app.analysis.auto_runner import AutoRuns
from app.analysis.images import ImageError
from app.analysis.service import Library, NotStored
from app.core.middleware import from_this_computer
from app.core.security import actor_from, check_csrf
from app.models import ais as batches
from app.models import users
from app.routes.helpers import bad_request, conflict, error, forbidden, get_config, get_store, not_found, parse_id, read_json, run

UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024
MAX_IMPORT_SHAS = 200_000


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


def _expect(body: dict[str, Any]) -> tuple[int | None, Response | None]:
    """The rev the caller last saw (optional): a stale one is a 409, so an
    edit queued while offline cannot overwrite someone else's since."""
    expect = body.get("expect")
    if expect is None:
        return None, None
    if not isinstance(expect, int) or isinstance(expect, bool) or expect < 0:
        return None, bad_request("expect must be a whole number")
    return expect, None


def _stale(exc: batches.RevConflict) -> Response:
    return conflict(str(exc), current=exc.current)


async def upload(request: Request) -> Response:
    """The file's bytes as application/octet-stream with the CSRF token in
    X-CSRF-Token (what the page sends: no base64, no JSON parse of a 6 MB
    string), or JSON {data: base64} like every other POST."""
    if request.headers.get("content-type", "").split(";")[0].strip() == "application/octet-stream":
        if not check_csrf(request, request.headers.get("x-csrf-token")):
            return forbidden("invalid csrf token")
        raw = await request.body()
    else:
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


def _unshown(exc: ImageError) -> Response:
    """Why a file's view, channels or thumbnail is not there: 404 while the
    server does not have the file, 422 when it has one it cannot read (a .czi
    without the channels it needs, say), so the page does not call that file
    "not uploaded"."""
    return not_found(str(exc)) if isinstance(exc, NotStored) else error(422, str(exc))


async def view(request: Request) -> Response:
    try:
        png = await run(_library(request).preview, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def channels(request: Request) -> Response:
    """A .czi's channels [{index, name, color}] for the channel buttons; [] for a TIFF."""
    try:
        found = await run(_library(request).channels, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return JSONResponse({"channels": found}, headers={"Cache-Control": "private, max-age=86400"})


async def somata(request: Request) -> Response:
    """An image's soma outlines (soma.py), each its edge pixels as 1-based
    [x, y], for the Soma button: from its soma channel, else whichever channel
    shows cell bodies; [] when none does (and for a Z-stack)."""
    try:
        found = await run(_library(request).soma, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return JSONResponse({"somata": found.outlines if found else []}, headers={"Cache-Control": "private, max-age=86400"})


MAX_PAIR_TRACES = 500


def _trace_pixels(value: Any) -> list[list[int]] | None:
    """A trace's pixels as 1-based [x, y] whole numbers, else None."""
    if not isinstance(value, list) or not value:
        return None
    out = []
    for p in value:
        if (not isinstance(p, list) or len(p) != 2
                or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in p)):
            return None
        out.append([p[0], p[1]])
    return out


def _soma_shape(value: Any) -> tuple[pairing.SomaShape | None, Response | None]:
    """The soma size and roundness a pair asks for (the defaults when none):
    0 <= min_um < max_um <= 200, 0 <= roundness <= 1."""
    if value is None:
        return pairing.SomaShape(), None
    if not isinstance(value, dict):
        return None, bad_request("soma must be {min_um, max_um, roundness}")
    out = pairing.SomaShape()
    for key in ("min_um", "max_um", "roundness"):
        v = value.get(key, getattr(out, key))
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return None, bad_request(f"soma.{key} must be a number")
        setattr(out, key, float(v))
    if not (0 <= out.min_um < out.max_um <= 200 and 0 <= out.roundness <= 1):
        return None, bad_request("soma needs 0 <= min_um < max_um <= 200 and 0 <= roundness <= 1")
    return out, None


async def pair(request: Request) -> Response:
    """Body {pixel_um, traces: [{id, pixels}], split?, soma?: {min_um, max_um,
    roundness}}: for each accepted AIS
    on the image, the Measure tool's guess (app/analysis/pairing.py): which
    end starts at the soma (the thicker), the soma in front of it, and B on
    that soma's ellipse; and the image's soma ellipses (split, the default:
    one per hotspot, else one per outline). {pairs: [{id, end, by, widths,
    a, b, body, gap_um, angle_deg, confident, other}], bodies: [{cx, cy, a,
    b, angle_deg, ais (the id it faces) | null}]}."""
    body, refused = await _body(request)
    if refused:
        return refused
    pixel_um = body.get("pixel_um")
    if (not isinstance(pixel_um, (int, float)) or isinstance(pixel_um, bool) or not math.isfinite(pixel_um)
            or pixel_um <= 0):
        return bad_request("pixel_um must be a positive number")
    split = body.get("split", True)
    if not isinstance(split, bool):
        return bad_request("split must be true or false")
    shape, bad = _soma_shape(body.get("soma"))
    if bad:
        return bad
    traces = body.get("traces")
    if not isinstance(traces, list) or len(traces) > MAX_PAIR_TRACES:
        return bad_request(f"traces must be a list of at most {MAX_PAIR_TRACES}")
    ids, pixels = [], []
    for t in traces:
        found = _trace_pixels(t.get("pixels")) if isinstance(t, dict) else None
        if found is None:
            return bad_request("each trace needs pixels, a list of 1-based [x, y] whole numbers")
        ids.append(t.get("id"))
        pixels.append(found)
    try:
        found = await run(_library(request).pair, request.path_params["sha"], pixels, float(pixel_um), split, shape)
    except ImageError as exc:
        return _unshown(exc)
    bodies = [b | {"ais": None if b["ais"] is None else ids[b["ais"]]} for b in found["bodies"]]
    return JSONResponse({"pairs": [{"id": i} | p for i, p in zip(ids, found["pairs"])], "bodies": bodies})


async def channel(request: Request) -> Response:
    try:
        index = int(request.path_params["index"])
        png = await run(_library(request).channel_png, request.path_params["sha"], index)
    except ImageError as exc:
        return _unshown(exc)
    except ValueError as exc:
        return not_found(str(exc))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def slice_view(request: Request) -> Response:
    """One slice of a Z-stack, for the viewer's Z slider."""
    try:
        index = int(request.path_params["index"])
        png = await run(_library(request).slice_png, request.path_params["sha"], index)
    except ImageError as exc:
        return _unshown(exc)
    except ValueError as exc:
        return not_found(str(exc))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def composite(request: Request) -> Response:
    """A .czi's channels merged in their display colors, for exports."""
    try:
        png = await run(_library(request).composite_png, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def thumb(request: Request) -> Response:
    try:
        png = await run(_library(request).thumbnail, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


async def file_bytes(request: Request) -> Response:
    """The stored file itself (a .czi or TIFF as it was added), for exports."""
    try:
        path = await run(_library(request).file_path, request.path_params["sha"])
        data = await run(path.read_bytes)
    except ImageError as exc:
        return _unshown(exc)
    kind = "image/tiff" if path.suffix.lower() in (".tif", ".tiff") else "application/octet-stream"
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


async def processed_tif(request: Request) -> Response:
    """A .czi's processed AIS channel as a TIFF (what tracing uses), for exports."""
    try:
        data = await run(_library(request).processed_tiff, request.path_params["sha"])
    except ImageError as exc:
        return _unshown(exc)
    return Response(data, media_type="image/tiff", headers={"Cache-Control": "private, max-age=86400"})


async def channel_tif(request: Request) -> Response:
    """One .czi channel, its data as a 16-bit TIFF, for exports."""
    try:
        index = int(request.path_params["index"])
        data = await run(_library(request).channel_tiff, request.path_params["sha"], index)
    except ImageError as exc:
        return _unshown(exc)
    except ValueError as exc:
        return not_found(str(exc))
    return Response(data, media_type="image/tiff", headers={"Cache-Control": "private, max-age=86400"})


def _point(value: Any) -> tuple[float, float] | None:
    if not (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except OverflowError:   # JSON integers have no limit
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


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


def _z_method(value: Any) -> tuple[str | None, str]:
    """The Z method a body asks for (zlength.METHODS). (None, why) when it
    can't be used; on an ordinary image nothing reads it."""
    try:
        return zlength.method(value).id, ""
    except ValueError as exc:
        return None, str(exc)


def _engine(value: Any) -> bool | None:
    """Whether a body's engine asks for app/analysis/fast.py; None if it is
    neither that nor left out."""
    return True if value == "fast" else False if value is None else None


async def trace(request: Request) -> Response:
    """Body: {processed, raw?, click: [x, y], click2?: [x, y], threshold?,
    settings?: {smooth, kernel, sigma, ...}, engine?: "fast"}.
    Clicks are MATLAB axes coordinates (x = column, y = row, pixel centres at
    1..n). click2 stands in for the second ginput after re-thresholding; by
    default the first click is used again. threshold defaults to 0.01, what
    the original was called with (0 means Otsu, as in the original). engine
    "fast" is Settings' Method "ais_auto.m (fast)": the same answer, sooner."""
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
    quick = _engine(body.get("engine"))
    if quick is None:
        return bad_request("engine must be fast, or left out")
    z_method, why = _z_method(body.get("z_method"))
    if z_method is None:
        return bad_request(why)
    library = _library(request)
    try:
        result = await run(library.trace_fast if quick else library.trace, processed, raw, click, click2, threshold,
                           settings, z_method)
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
    exclude?: [[[x, y], ...], ...], engine?: "fast"}. Every AIS found on the image without a
    click (app/analysis/detect.py); start is both | brighter | dimmer | soma
    (a .czi only) | fitted | fitted2 | learned, exclude the traces already
    accepted on it."""
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
    quick = _engine(body.get("engine"))
    if quick is None:
        return bad_request("engine must be fast, or left out")
    z_method, why = _z_method(body.get("z_method"))
    if z_method is None:
        return bad_request(why)
    library = _library(request)
    try:
        result = await run(library.detect_fast if quick else library.detect, processed, raw, threshold, settings, start,
                           exclude, z_method)
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

    def one(f: dict[str, Any]) -> bool:
        return bool(by_path and f.get("path")) or library.has(f["sha"])

    # A stack's own sha is no file: it is there when its slices are.
    return lambda f: all(one(part) for part in f["slices"]) if "slices" in f else one(f)


def _blind(request: Request) -> bool:
    """Whether original names must be kept from whoever asks: everyone but admins."""
    return not actor_from(request).is_admin


def _unnamed_file(f: dict[str, Any]) -> dict[str, Any]:
    """A blinded file without what it was called: its original name, the
    path on this machine (which has that name in it) and the random names it
    had before (which old exports could be matched against). A stack's slices
    keep their names at rest, so here they lose them."""
    if "original" not in f:
        return f
    out = {k: v for k, v in f.items() if k not in ("original", "path", "earlier")}
    if "slices" in out:
        out["slices"] = [{k: part[k] for k in ("z", "sha", "size", "stored") if k in part} for part in out["slices"]]
    return out


def _unnamed_image(image: dict[str, Any]) -> dict[str, Any]:
    # A treatment gives away what blinding hides as much as a name does.
    return {k: v for k, v in image.items()
            if k not in ("original_cell", "original_key", "original_dir", "earlier_keys", "treatment")}


def _unnamed_add(add: dict[str, Any]) -> dict[str, Any]:
    """An add without what was picked, kept for admins when it was a stack's folder."""
    return {k: v for k, v in add.items() if k not in ("original_name", "original_path")}


def _stored(f: dict[str, Any], has: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """f with whether the server can show it, and each slice of a stack with its own."""
    out = f | {"stored": has(f)}
    if "slices" in f:
        out["slices"] = [part | {"stored": has(part)} for part in f["slices"]]
    return out


def _batch_json(request: Request, batch: dict[str, Any]) -> dict[str, Any]:
    """The batch with, per file, whether the server can show it already, and
    (admins only) the original names of blinded files."""
    has = _has(request)
    blind = _blind(request)
    images = []
    for image in batch["images"]:
        files = {role: _stored(f, has) for role, f in image["files"].items()}
        if blind:
            files = {role: _unnamed_file(f) for role, f in files.items()}
            image = _unnamed_image(image)
        images.append(image | {"files": files})
    names = _names(request)
    assigned = {share["user_id"] for share in (batch.get("assignment") or {}).get("shares", [])}
    adders = {a.get("added_by") for a in batch.get("adds", [])}
    adds = [_unnamed_add(a) if blind else a for a in batch.get("adds", [])]
    return batch | {"images": images, "created_by_name": names.get(batch["created_by"], ""),
                    "assignee_names": {str(u): names.get(u, "") for u in assigned},
                    "adds": [a | {"added_by_name": names.get(a.get("added_by"), "")} for a in adds],
                    "excluded": sorted(batches.excluded_keys(batch)),
                    "adder_names": {str(u): names.get(u, "") for u in adders if u is not None}}


def _activity(request: Request) -> batches.Activity:
    return request.app.state.ais_activity


async def batch_list(request: Request) -> Response:
    """Every batch with its progress: uploads, completion, per assignee, and
    any auto run going on (the Batches screen polls this as its monitor)."""
    rows = await run(_batch_rows, request)
    folders = await run(batches.list_folders, get_store(request))
    return JSONResponse({"batches": rows, "folders": folders})


def _batch_rows(request: Request) -> list[dict[str, Any]]:
    """list_batches as whoever asks may see it, with the names of the people
    in it and the live activity (batch_list, report)."""
    rows = batches.list_batches(get_store(request), _user_id(request), _has(request))
    names = _names(request)
    live = _activity(request).current()
    blind = _blind(request)
    for row in rows:
        row["created_by_name"] = names.get(row["created_by"], "")
        for a in row["assignees"]:
            a["name"] = names.get(a["user_id"], "")
        row["activity"] = [a | {"name": names.get(a["user_id"], "")} for a in live.get(row["id"], [])]
        row["adds"] = [(_unnamed_add(a) if blind else a) | {"added_by_name": names.get(a.get("added_by"), "")}
                       for a in row["adds"]]
        if blind:
            # A treatment gives away what blinding hides as much as a name does.
            row.pop("treatments", None)
            row.pop("untreated", None)
    return rows


async def batch_create(request: Request) -> Response:
    """Body: {name, folder_id?}: an empty batch, its images added afterwards,
    in that folder (the one the Batches screen is showing) or at the top."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.new_batch, get_store(request), body.get("name"), "upload", _user_id(request),
                          None, body.get("folder_id"))
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


MAX_FILL = 50


def _fill_areas(library: Library, store: Any, batch: dict[str, Any], after: int, limit: int,
                with_soma: bool = False) -> dict[str, Any]:
    """Up to limit of a batch's accepted AIS with no area (batches.needs_area),
    ids above after, traced again to fill it in (Library.remeasure); with_soma:
    only those whose soma distance has been measured."""
    images = {im["key"]: im for im in batch["images"]}
    todo = sorted((r for r in batches.list_results(store, batch["id"]) if batches.needs_area(r) and r["id"] > after
                   and (not with_soma or r.get("soma_um") is not None)), key=lambda r: r["id"])
    filled, failed, last = 0, [], after
    for row in todo[:limit]:
        last = row["id"]
        image = images.get(row["image"])
        values = None
        if image is not None:
            files = image["files"]
            processed = batches.traced_sha(image, ap.traced(files))
            raw = batches.traced_sha(image, "raw") if ap.kind(files) == "pair" else None
            try:
                values = library.remeasure(processed, raw, row)
            except (ImageError, NotStored, ValueError):
                values = None
        if values and batches.set_measures(store, row["id"], values) is not None:
            filled += 1
        else:
            failed.append(row["id"])
    return {"filled": filled, "failed": failed, "after": last, "remaining": max(len(todo) - limit, 0)}


async def batch_fill_areas(request: Request) -> Response:
    """Body: {after?: result id, limit?: 1-50, with_soma?: only AIS with a
    soma distance}: fill in the area (and on a
    Z-stack the volume) of the batch's accepted AIS that have none, by
    tracing each again from its saved clicks and settings; only one that
    comes out on the same pixels is filled in. A few at a time: call again
    with after until remaining is 0. {filled, failed: [ids], after, remaining}."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    store = get_store(request)
    batch = await run(batches.get_batch, store, batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    after, limit = body.get("after", 0), body.get("limit", 10)
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        return bad_request("after must be a result id")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_FILL:
        return bad_request(f"limit must be 1 to {MAX_FILL}")
    with_soma = body.get("with_soma", False)
    if not isinstance(with_soma, bool):
        return bad_request("with_soma must be true or false")
    return JSONResponse(await run(_fill_areas, _library(request), store, batch, after, limit, with_soma))


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


async def batch_move(request: Request) -> Response:
    """Body: {ids, folder_id}: those batches into that folder, null for the
    top (admins)."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        moved = await run(batches.move_batches, get_store(request), body.get("ids"), body.get("folder_id"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse({"moved": moved})


# --- the Batches screen's folders (admins change them) --------------------------


async def folder_list(request: Request) -> Response:
    return JSONResponse({"folders": await run(batches.list_folders, get_store(request))})


async def folder_create(request: Request) -> Response:
    """Body: {name, parent_id}: a new folder, first in its parent (null: the top)."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        folder = await run(batches.create_folder, get_store(request), body.get("name"), body.get("parent_id"),
                           _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(folder)


def _folder_id(request: Request) -> int | None:
    return parse_id(request.path_params["folder_id"])


async def folder_rename(request: Request) -> Response:
    """Body: {name}."""
    body, refused = await _body(request)
    if refused:
        return refused
    folder_id = _folder_id(request)
    try:
        folder = await run(batches.rename_folder, get_store(request), folder_id, body.get("name")) if folder_id else None
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(folder) if folder else not_found("no such folder")


async def folder_move(request: Request) -> Response:
    """Body: {parent_id}: into another folder, null for the top."""
    body, refused = await _body(request)
    if refused:
        return refused
    folder_id = _folder_id(request)
    try:
        folder = await run(batches.move_folder, get_store(request), folder_id, body.get("parent_id")) if folder_id else None
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(folder) if folder else not_found("no such folder")


async def folder_delete(request: Request) -> Response:
    """The folder gone, what was in it moved up to its parent."""
    body, refused = await _body(request)
    if refused:
        return refused
    folder_id = _folder_id(request)
    folder = await run(batches.delete_folder, get_store(request), folder_id, _user_id(request)) if folder_id else None
    return JSONResponse({"ok": True, "trash_id": folder["trash_id"]}) if folder else not_found("no such folder")


async def folder_order(request: Request) -> Response:
    """Body: {parent_id, ids}: the order of one folder's folders."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        await run(batches.order_folders, get_store(request), body.get("parent_id"), body.get("ids"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse({"ok": True})


def _randomize(body: dict[str, Any]) -> bool:
    """Whether an add blinds its names: yes unless the body says false."""
    return body.get("randomize", True) is not False


def _add_name(body: dict[str, Any]) -> str | None:
    name = body.get("add_name")
    return name if isinstance(name, str) else None


async def batch_add(request: Request) -> Response:
    """Body: {files: [{name, rel, sha, size, modified?}], randomize?, add_name?,
    translations?: [{dir, text}]}: more files picked in the browser for an
    existing batch, named by any __Translation.txt picked with them, blinded
    unless randomize is false. Upload them afterwards as for a new one."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        batch = await run(batches.add_files, get_store(request), batch_id, "upload", body.get("files"),
                          randomize_names=_randomize(body), user_id=_user_id(request), name=_add_name(body),
                          translations=body.get("translations"), stack=body.get("stack"),
                          channel_roles=body.get("channels"))
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
    images = await run(_status_rows, request, batch, rows)
    return JSONResponse({"id": batch["id"], "images": images})


def _status_rows(request: Request, batch: dict[str, Any], rows: list[dict[str, Any]],
                 names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """image_status as whoever asks may see it (batch_status, report)."""
    images = batches.image_status(batch, rows, _has(request))
    names = _names(request) if names is None else names
    blind = _blind(request)
    for image in images:
        image["assignee_name"] = names.get(image["assignee"], "") if image["assignee"] else ""
        if blind:
            image.pop("original_key", None)
    return images


async def batch_include(request: Request) -> Response:
    """Body: {keys, included}: include these images, or leave them out, for
    the whole team."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        batch = await run(batches.set_included, get_store(request), batch_id, body.get("keys"), body.get("included"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_json, request, batch))


async def batch_rerandomize(request: Request) -> Response:
    """New random names for one folder of the batch (admins); its results,
    done marks, exclusions and assignment move with them."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    raw = request.path_params["add_id"]
    add_id: Any = "earlier" if raw == "earlier" else parse_id(raw)
    if not batch_id or not add_id:
        return not_found("no such folder")
    try:
        out = await run(batches.rerandomize, get_store(request), batch_id, add_id)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if out is None:
        return not_found("no such batch")
    batch, renamed, measured = out
    return JSONResponse(await run(_batch_json, request, batch) | {"renamed": renamed, "measured": measured})


async def batch_translation(request: Request) -> Response:
    """The batch's __Translation.txt (admins): original/random per file."""
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, get_store(request), batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    return Response(batches.translation(batch), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="__Translation.txt"'})


async def batch_treatments(request: Request) -> Response:
    """Each image's original name, saved treatment and guessed one (admins)."""
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, get_store(request), batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    return JSONResponse({"treatments": await run(batches.review_treatments, get_store(request), batch)})


async def batch_treatments_set(request: Request) -> Response:
    """Body: {treatments: {key: name}} (admins); "" takes one off."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    try:
        batch = await run(batches.set_treatments, get_store(request), batch_id, body.get("treatments")) if batch_id else None
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if batch is None:
        return not_found("no such batch")
    return JSONResponse({"treatments": await run(batches.review_treatments, get_store(request), batch)})


async def compare_batches(request: Request) -> Response:
    """Body: {batch_ids, labels?, tests?, units?, design?}: the batches' measurements
    grouped by treatment, and with two or more, tested and plotted (admins:
    it has the original names and treatments). tests/units pick the stats
    rows (every one when left out); design the two-way ANOVA's factors. See app/analysis/compare.py."""
    body, refused = await _body(request)
    if refused:
        return refused
    # sheets: true (agents, scripts) adds the comparison.xlsx sheets as JSON
    # (app/analysis/report.py) and keeps the SVG plots only when plots is
    # true too. Without it the answer is what the Batches screen has always had.
    sheets, plots = body.get("sheets", False), body.get("plots", True)
    if not isinstance(sheets, bool) or not isinstance(plots, bool):
        return bad_request("sheets and plots must be true or false")
    try:
        if sheets:
            out = await run(report.comparison, get_store(request), body.get("batch_ids"), body.get("labels"),
                            body.get("tests"), body.get("units"), plots, body.get("design"))
        else:
            out = await run(compare.compare, get_store(request), body.get("batch_ids"), body.get("labels"),
                            body.get("tests"), body.get("units"), body.get("design"))
    except compare.CompareError as exc:
        return bad_request(str(exc))
    return JSONResponse(out)


def _report_ids(raw: str) -> list[int] | None:
    """?batch=: "all", or batch ids separated by commas. None when malformed;
    [] means all."""
    if raw == "all":
        return []
    ids = [parse_id(part.strip()) for part in raw.split(",")] if raw else []
    return ids if ids and all(ids) else None


def _flag(request: Request, name: str) -> bool | None:
    raw = request.query_params.get(name, "")
    return {"": False, "0": False, "false": False, "1": True, "true": True}.get(raw)


def _report(request: Request, ids: list[int], everything: bool, unblind: bool) -> dict[str, Any] | None:
    """The batch report's sheets as JSON (app/analysis/report.py), as the
    Batches screen's export gathers them (static/js/batches.js gather). None
    when a batch asked for does not exist."""
    store = get_store(request)
    listed = _batch_rows(request)
    if ids:
        by_id = {b["id"]: b for b in listed}
        if any(i not in by_id for i in ids):
            return None
        chosen = [by_id[i] for i in dict.fromkeys(ids)]
    else:
        chosen = listed
    one = len(chosen) == 1
    results = batches.list_results(store, chosen[0]["id"] if one else None)
    lines = batches.list_measurements(store, chosen[0]["id"] if one else None)
    names = _names(request)
    items, full = [], {}
    for b in chosen:
        batch = batches.get_batch(store, b["id"])
        if batch is None:
            continue
        full[b["id"]] = batch
        own = [r for r in results if r["batch_id"] == b["id"]]
        status = _status_rows(request, batch, own, names)
        out = {im["key"] for im in status if not im["included"] and not everything}
        items.append({"batch": b, "images": [im for im in status if im["key"] not in out],
                      "rows": [r for r in own if r["image"] not in out],
                      "measurements": [m for m in lines if m["batch_id"] == b["id"] and m["image"] not in out]})
    admin = not _blind(request)
    if unblind and admin:
        items = report.unrandomized(items, full)
    sheets = report.sheets(items)
    if admin:
        sheets |= report.extra_sheets(store, [item["batch"]["id"] for item in items])
    return {"batches": [{"id": item["batch"]["id"], "name": item["batch"]["name"]} for item in items],
            "unblinded": bool(unblind and admin), "everything": everything, "sheets": sheets}


async def batch_report(request: Request) -> Response:
    """?batch=<id>[,<id>...] | all, everything=0|1, unblind=0|1 (admins),
    sheets=<name>[,<name>...]: the Batches screen's report (report.xlsx) as
    JSON, for agents and scripts. Images the team left out are not in it
    unless everything; unblind puts blinded images under their original
    names, for admins only (anyone else gets the blinded report)."""
    ids = _report_ids(request.query_params.get("batch", "all"))
    if ids is None:
        return bad_request("batch must be all, or batch ids separated by commas")
    everything, unblind = _flag(request, "everything"), _flag(request, "unblind")
    if everything is None or unblind is None:
        return bad_request("everything and unblind must be 0 or 1")
    wanted = [s for s in request.query_params.get("sheets", "").split(",") if s]
    if any(s not in report.SHEETS for s in wanted):
        return bad_request("sheets must be some of " + ", ".join(report.SHEETS))
    try:
        out = await run(_report, request, ids, everything, unblind)
    except compare.CompareError as exc:
        return bad_request(str(exc))
    if out is None:
        return not_found("no such batch")
    if wanted:
        out["sheets"] = {k: v for k, v in out["sheets"].items() if k in wanted}
    return JSONResponse(out)


# --- auto runs on the server (app/analysis/auto_runner.py) ----------------------


def _runs(request: Request) -> AutoRuns:
    return request.app.state.ais_runs


async def auto_defaults(request: Request) -> Response:
    """What a run uses unless it says otherwise, and what it may say: the
    browser's Settings defaults (static/js/settings.js)."""
    return JSONResponse({"general": ap.DEFAULTS, "ranges": {k: list(v) for k, v in ap.RANGES.items()},
                         "methods": list(ap.METHODS), "starts": list(ap.STARTS), "threshold": ap.THRESHOLD,
                         "settings": ap.METHOD_SETTINGS, "engines": [None, "fast"],
                         "z_methods": [m.id for m in zlength.METHODS if m.ready]})


async def auto_start(request: Request) -> Response:
    """Body: {general?, settings?, threshold?, engine?, skip_done?, mark_done?,
    images?}: auto mode over the batch, run by the server and saved as the
    browser's review "all" saves (each kept AIS straight to the batch).
    general: Settings' general fields (auto_method, fitted_min_length, ...);
    settings: the method's (pixconv, smooth, ...); images: only these keys.
    Answers at once with the run; GET /api/ais/auto/{run_id} follows it."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    general, settings = body.get("general"), body.get("settings")
    if (general is not None and not isinstance(general, dict)) or (settings is not None and not isinstance(settings, dict)):
        return bad_request("general and settings must be objects")
    skip, mark = body.get("skip_done"), body.get("mark_done", False)
    if (skip is not None and not isinstance(skip, bool)) or not isinstance(mark, bool):
        return bad_request("skip_done and mark_done must be true or false")
    try:
        choices = auto_runner.plan(general, settings, body.get("threshold"), body.get("engine"))
        out = await run(lambda: _runs(request).start(batch_id, _user_id(request), choices, skip_done=skip,
                                                     mark_done=mark, images=body.get("images")))
    except ap.ParamError as exc:
        return bad_request(str(exc))
    except auto_runner.RunError as exc:
        if str(exc) == "no such batch":
            return not_found(str(exc))
        return conflict(str(exc)) if "already" in str(exc) else bad_request(str(exc))
    return JSONResponse(out)


async def auto_list(request: Request) -> Response:
    """?batch=<id>: the runs on that batch (else every one), newest first."""
    raw = request.query_params.get("batch", "")
    batch_id = parse_id(raw) if raw else None
    if raw and batch_id is None:
        return bad_request("batch must be a batch id")
    return JSONResponse({"runs": _runs(request).list(batch_id)})


async def auto_get(request: Request) -> Response:
    out = _runs(request).get(request.path_params["run_id"])
    return JSONResponse(out) if out else not_found("no such run")


async def auto_cancel(request: Request) -> Response:
    """Stop a run after the image it is on: whoever started it, or an admin."""
    body, refused = await _body(request)
    if refused:
        return refused
    runs = _runs(request)
    found = runs.get(request.path_params["run_id"])
    if found is None:
        return not_found("no such run")
    actor = actor_from(request)
    if found["user_id"] != actor.user.id and not actor.is_admin:
        return forbidden("only whoever started the run, or an admin, can stop it")
    return JSONResponse(runs.cancel(found["id"]))


async def batch_translation_load(request: Request) -> Response:
    """Body: {text}: a __Translation.txt for a batch blinded somewhere else
    (admins): the original names of the files it names."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    if not batch_id:
        return not_found("no such batch")
    try:
        out = await run(batches.apply_translation, get_store(request), batch_id, body.get("text"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if out is None:
        return not_found("no such batch")
    batch, named, unnamed = out
    return JSONResponse(await run(_batch_json, request, batch) | {"named": named, "unnamed": unnamed})


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


def _batch_channels(library: Library, batch: dict[str, Any]) -> dict[str, Any]:
    """The channels of a batch's included .czi files by name, in the order
    first met, each with how many files have it, for the Export dialog. Only
    what the server holds is looked at, so opening the dialog does not copy
    in an Open-path batch; unread counts the rest and files it cannot read."""
    found: dict[str, dict[str, Any]] = {}
    excluded = batches.excluded_keys(batch)
    czis = unread = 0
    for image in batch["images"]:
        czi = image["files"].get("czi")
        if not czi or image["key"] in excluded:
            continue
        czis += 1
        try:
            channels = library.channels(czi["sha"]) if library.has(czi["sha"]) else None
        except ImageError:
            channels = None
        if channels is None:
            unread += 1
            continue
        for channel in channels:
            entry = found.setdefault(channel["name"], {"name": channel["name"], "color": channel["color"], "files": 0})
            entry["files"] += 1
    return {"channels": list(found.values()), "czis": czis, "unread": unread}


async def batch_channels(request: Request) -> Response:
    batch_id = parse_id(request.path_params["batch_id"])
    batch = await run(batches.get_batch, get_store(request), batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_channels, _library(request), batch))


def _image_layouts(library: Library, images: list[dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    """key -> (role, layout) for images with no channel roles yet, read from
    their stored files (batches.channel_file); those not stored are left out."""
    out = {}
    for image in images:
        if image.get("channels"):
            continue
        found = batches.channel_file(image)
        if not found:
            continue
        role, sha = found
        try:
            if library.has(sha):
                out[image["key"]] = (role, library.layout(sha))
        except ImageError:
            continue
    return out


def _add_param(request: Request) -> tuple[int | None, bool]:
    """(add id or None for the whole batch, whether it was well formed)."""
    raw = request.query_params.get("add", "")
    if not raw:
        return None, True
    add_id = parse_id(raw)
    return add_id, bool(add_id)


def _batch_layouts(library: Library, store: Any, batch: dict[str, Any], add_id: int | None) -> dict[str, Any]:
    """The channel layouts of a batch's (or an add's) images for the Channels
    dialog: channels.summarize's entries, each with how many of its images
    already have results; unread counts images whose file isn't stored yet."""
    images = batches.channel_scope(batch, add_id)
    read = _image_layouts(library, images)
    with_results = {r["image"] for r in batches.list_results(store, batch["id"])}
    found, roles, keys = [], [], []
    for image in images:
        chosen = image.get("channels")
        layout = chosen["layout"] if chosen else read.get(image["key"], (None, None))[1]
        if layout is None:
            continue
        colors = None
        if layout["kind"] == "czi":
            role, sha = batches.channel_file(image)
            try:
                colors = [c["color"] for c in library.channels(sha)] if library.has(sha) else None
            except ImageError:
                colors = None
        found.append((layout, colors))
        roles.append(chosen["roles"] if chosen else None)
        keys.append(image["key"])
    out = views.summarize(found, roles)
    for entry in out:
        entry["results"] = sum(1 for (layout, _), key in zip(found, keys)
                               if views.same(layout, entry["layout"]) and key in with_results)
    return {"layouts": out, "images": len(images), "unread": len(images) - len(found),
            "stacks": batches.stack_calibration(images), "pixel": batches.image_pixel_size(images)}


async def batch_layouts(request: Request) -> Response:
    """?add=<id>: the channel layouts of a batch's images, or one add's."""
    batch_id = parse_id(request.path_params["batch_id"])
    add_id, ok = _add_param(request)
    if not ok:
        return bad_request("add must be an add's id")
    store = get_store(request)
    batch = await run(batches.get_batch, store, batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    return JSONResponse(await run(_batch_layouts, _library(request), store, batch, add_id))


async def batch_layouts_set(request: Request) -> Response:
    """Body: {add?, channels: [{layout, roles}], stack?: {z_step_um,
    pixel_um}, pixel_um?: number or null}: new channel roles for the images
    of a batch (or one add) with those layouts, for its Z-stacks a new z step
    and pixel size, and for its other images the microns per pixel they are
    measured with (null: back to Settings', 40x by default).
    Answers with the batch and the keys of the images now traced from other
    channels or calibration."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = parse_id(request.path_params["batch_id"])
    store = get_store(request)
    batch = await run(batches.get_batch, store, batch_id) if batch_id else None
    if batch is None:
        return not_found("no such batch")
    add_id = body.get("add")
    if add_id is not None and (not isinstance(add_id, int) or isinstance(add_id, bool)):
        return bad_request("add must be an add's id")
    layouts = await run(_image_layouts, _library(request), batches.channel_scope(batch, add_id))
    try:
        found = await run(batches.set_channels, store, batch_id, add_id, body.get("channels"), layouts,
                          body.get("stack"), body["pixel_um"] if "pixel_um" in body else ...)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if found is None:
        return not_found("no such batch")
    record, changed = found
    return JSONResponse({"batch": await run(_batch_json, request, record), "changed": changed})


async def batch_upload(request: Request) -> Response:
    """Body: {name, files: [{name, rel, sha, size}], translations?: [{dir,
    text}]} -- a folder picked in the browser, hashed there. Upload the files afterwards with POST /api/ais/files."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.create_batch, get_store(request), body.get("name"), "upload",
                          body.get("files"), _user_id(request), randomize_names=_randomize(body),
                          translations=body.get("translations"), stack=body.get("stack"),
                          channel_roles=body.get("channels"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(await run(_batch_json, request, batch))


def _backup(request: Request, batch_id: int) -> dict[str, Any] | None:
    """A batch as data (batches.backup_batch), with the names of the people
    in it and which of its files the server can hand out."""
    backup = batches.backup_batch(get_store(request), batch_id)
    if backup is None:
        return None
    named = batches.backup_user_ids(backup)
    has = _has(request)
    stored = {f["sha"] for image in batches.get_batch(get_store(request), batch_id)["images"]
              for f in batches.real_files(image) if has(f)}
    return backup | {"format": batches.BACKUP_FORMAT, "version": batches.BACKUP_VERSION,
                     "users": {str(i): n for i, n in _names(request).items() if i in named},
                     "stored": sorted(stored)}


async def batch_backup(request: Request) -> Response:
    """What a backup ZIP holds besides the image files. Admins only: it has
    the original names in it."""
    batch_id = parse_id(request.path_params["batch_id"])
    backup = await run(_backup, request, batch_id) if batch_id else None
    if backup is None:
        return not_found("no such batch")
    return JSONResponse(backup)


async def batch_import_missing(request: Request) -> Response:
    """Body: {shas}. Which of a backup's files the store does not have yet,
    to upload with POST /api/ais/files before importing."""
    body, refused = await _body(request)
    if refused:
        return refused
    shas = body.get("shas")
    if (not isinstance(shas, list) or len(shas) > MAX_IMPORT_SHAS
            or not all(isinstance(s, str) and batches.SHA_RE.match(s) for s in shas)):
        return bad_request("shas must be a list of sha-256 hex digests")
    library = _library(request)
    return JSONResponse({"missing": await run(lambda: [s for s in shas if not library.has(s)])})


async def batch_import(request: Request) -> Response:
    """Body: one batch of a backup ({format, version, users, batch, results}),
    which becomes a new batch."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        batch = await run(batches.import_batch, get_store(request), body, _names(request), _user_id(request))
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
    trash_id = await run(batches.delete_batch, store, batch_id, actor.user.id)
    if trash_id is None:
        return not_found("no such batch")
    return JSONResponse({"ok": True, "trash_id": trash_id})


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
        out = await run(batches.reset_batch, get_store(request), batch_id, body.get("scope"), _user_id(request))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if out is None:
        return not_found("no such batch")
    batch, deleted, trash_id = out
    return JSONResponse({"batch": await run(_batch_json, request, batch), "deleted": deleted, "trash_id": trash_id})


# --- trash (deleted batches and folders, reset results) ------------------------


def _may_restore(request: Request, entry: dict[str, Any]) -> bool:
    """A batch: whoever deleted it or an admin, as for deleting it. A folder
    or a reset: admins, who are the only ones who can do those."""
    actor = actor_from(request)
    if actor.is_admin:
        return True
    return entry["kind"] == "batch" and entry.get("deleted_by") == actor.user.id


async def trash_list(request: Request) -> Response:
    """What was deleted in the last TRASH_DAYS days, newest first, each with
    can_restore for whoever asks."""
    store = get_store(request)
    entries = await run(batches.list_trash, store)
    names = await run(_names, request)
    for entry in entries:
        entry["deleted_by_name"] = names.get(entry["deleted_by"], "")
        entry["can_restore"] = _may_restore(request, entry)
    return JSONResponse({"entries": entries, "days": batches.TRASH_DAYS})


async def trash_restore(request: Request) -> Response:
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    trash_id = parse_id(request.path_params["trash_id"])
    entry = await run(batches.get_trash, store, trash_id) if trash_id else None
    if entry is None:
        return not_found("not in the trash")
    if not _may_restore(request, entry):
        return forbidden("only whoever deleted it, or an admin, can put it back")
    try:
        restored = await run(batches.restore_trash, store, trash_id)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if restored is None:
        return not_found("not in the trash")
    return JSONResponse(restored)


async def trash_purge(request: Request) -> Response:
    """Delete an entry for good (admins)."""
    body, refused = await _body(request)
    if refused:
        return refused
    trash_id = parse_id(request.path_params["trash_id"])
    gone = await run(batches.purge_trash, get_store(request), trash_id) if trash_id else False
    return JSONResponse({"ok": True}) if gone else not_found("not in the trash")


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
                        _user_id(request), body.get("client_id"))
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
    expect, bad = _expect(body)
    if bad:
        return bad
    try:
        renumbered = await run(batches.delete_result, store, result_id, expect)
    except batches.RevConflict as exc:
        return _stale(exc)
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
    expect, bad = _expect(body)
    if bad:
        return bad
    try:
        updated = await run(batches.update_result, store, result_id, body.get("row"), _user_id(request), expect)
    except batches.RevConflict as exc:
        return _stale(exc)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if updated is None:
        return not_found("no such result")
    return JSONResponse(updated)


async def result_soma(request: Request) -> Response:
    """Body: {soma}: an accepted AIS's distance to its soma (the Measure tool),
    or null to clear it. The trace is left as it is."""
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
    expect, bad = _expect(body)
    if bad:
        return bad
    try:
        updated = await run(batches.set_soma, store, result_id, body.get("soma"), _user_id(request), expect)
    except batches.RevConflict as exc:
        return _stale(exc)
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


# --- recorded measurements (the Measure tool's Record switch) ----------------


async def measure_types(request: Request) -> Response:
    """The team's measurement types for the Measure tool's Type picker."""
    types = await run(batches.measure_types, get_store(request))
    return JSONResponse({"types": types})


async def measure_types_set(request: Request) -> Response:
    """Body: {types: [name, ...]}: the team's new list (admins)."""
    body, refused = await _body(request)
    if refused:
        return refused
    try:
        types = await run(batches.set_measure_types, get_store(request), body.get("types"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse({"types": types})


async def measurement_list(request: Request) -> Response:
    """?batch=<id> for one batch, anything else for all."""
    batch_id = parse_id(request.query_params.get("batch", ""))
    lines = await run(batches.list_measurements, get_store(request), batch_id)
    return JSONResponse({"measurements": lines})


async def measurement_add(request: Request) -> Response:
    """Body: {batch_id, image, measurement}: a line recorded on an image."""
    body, refused = await _body(request)
    if refused:
        return refused
    batch_id = body.get("batch_id")
    if not isinstance(batch_id, int) or isinstance(batch_id, bool) or not isinstance(body.get("image"), str):
        return bad_request("batch_id and image are required")
    try:
        line = await run(batches.add_measurement, get_store(request), batch_id, body["image"], body.get("measurement"),
                         _user_id(request), body.get("client_id"))
    except batches.BatchError as exc:
        return bad_request(str(exc))
    return JSONResponse(line)


async def measurement_update(request: Request) -> Response:
    """Body: {measurement}: a recorded line's new ends, length and label."""
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    line_id = parse_id(request.path_params["measurement_id"])
    line = await run(batches.get_measurement, store, line_id) if line_id else None
    if line is None:
        return not_found("no such measurement")
    if not await _may_change(request, line):
        return forbidden("only whoever recorded it, the image's assignee, or an admin, can change it")
    expect, bad = _expect(body)
    if bad:
        return bad
    try:
        updated = await run(batches.update_measurement, store, line_id, body.get("measurement"), _user_id(request), expect)
    except batches.RevConflict as exc:
        return _stale(exc)
    except batches.BatchError as exc:
        return bad_request(str(exc))
    if updated is None:
        return not_found("no such measurement")
    return JSONResponse(updated)


async def measurement_delete(request: Request) -> Response:
    body, refused = await _body(request)
    if refused:
        return refused
    store = get_store(request)
    line_id = parse_id(request.path_params["measurement_id"])
    line = await run(batches.get_measurement, store, line_id) if line_id else None
    if line is None:
        return not_found("no such measurement")
    if not await _may_change(request, line):
        return forbidden("only whoever recorded it, the image's assignee, or an admin, can delete it")
    expect, bad = _expect(body)
    if bad:
        return bad
    try:
        renumbered = await run(batches.delete_measurement, store, line_id, expect)
    except batches.RevConflict as exc:
        return _stale(exc)
    return JSONResponse({"ok": True, "renumbered": renumbered})


# --- folders on this machine (app/analysis/local.py) ------------------------
#
# Registered for admins with a browser session only, and each call checks
# Config.local_folders_enabled, which is off unless the server listens on
# loopback outside the container.


async def local_status(request: Request) -> Response:
    actor = actor_from(request)
    cfg = get_config(request)
    enabled = bool(cfg.local_folders_enabled and actor.is_admin and actor.session is not None)
    # MATLAB opens on this machine, so it is only offered to someone sitting at
    # it; anyone else needs their own helper.
    found = enabled and from_this_computer(request.scope, cfg) and matlab.find_matlab(cfg.matlab) is not None
    helper_on = bool(cfg.matlab_helper and cfg.api_keys_enabled)
    return JSONResponse({"enabled": enabled, "platform": local.platform(), "matlab": found,
                         "helper_enabled": helper_on,
                         "helper": helper_on and request.app.state.matlab_jobs.live(actor.user.id)})


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


async def local_stacks(request: Request) -> Response:
    """Body: {path}. The Z-stacks under a folder, by name, for the Add dialog
    to ask about before the server hashes anything."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        return JSONResponse({"stacks": await run(local.stacks_under, body.get("path"))})
    except ImageError as exc:
        return bad_request(str(exc))


async def local_channels(request: Request) -> Response:
    """Body: {path}. The channel layouts of a folder's images, for the Add
    dialog to ask about before the server hashes anything."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        return JSONResponse({"layouts": await run(local.layouts_under, body.get("path"))})
    except ImageError as exc:
        return bad_request(str(exc))


def _hashed(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """An Open-path folder's files. With stacks, refused if the file limit
    would leave one short."""
    if body.get("stack") is not None:
        local.stacks_under(body.get("path"))
    return local.hashed_files(body.get("path"))


def _path_name(folder: str, body: dict[str, Any]) -> str:
    """What an Open-path add is called: its folder, unless that is a blinded
    stack's folder, which would say what it is."""
    if body.get("stack") is not None and _randomize(body):
        return "Z-stacks"
    return folder.rstrip("/\\").replace("\\", "/").split("/")[-1] or folder


async def batch_path(request: Request) -> Response:
    """Body: {path}: an Open-path batch, hashed and recorded by the server."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    try:
        folder, files = await run(_hashed, body)
        name = _path_name(folder, body)
        translations = await run(local.translations_under, folder)
        batch = await run(batches.create_batch, get_store(request), name, "path", files, _user_id(request), folder,
                          randomize_names=_randomize(body), translations=translations, stack=body.get("stack"),
                                  channel_roles=body.get("channels"))
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
        folder, files = await run(_hashed, body)
        name = _path_name(folder, body)
        translations = await run(local.translations_under, folder)
        batch = await run(batches.add_files, get_store(request), batch_id, "path", files, folder,
                          randomize_names=_randomize(body), user_id=_user_id(request), name=name,
                          translations=translations, stack=body.get("stack"),
                          channel_roles=body.get("channels"))
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


def matlab_run(body: dict[str, Any]) -> tuple[matlab.Run | None, str]:
    """Body: {mode: open|run|replay, processed, raw?, cell, threshold?,
    settings?, clicks?: [[x, y], ...]}, as a matlab.Run or (None, why).
    processed is the traced image's id, raw the profile image's when the cell
    has both. cell is the name the browser shows: a randomized batch's blind
    name stays blind because nothing here looks the original up."""
    mode = body.get("mode", "run")
    processed, raw, cell = body.get("processed"), body.get("raw"), body.get("cell")
    threshold = _threshold(body.get("threshold", 0.01))
    if not isinstance(mode, str) or mode not in matlab.MODES:
        return None, "mode must be open, run or replay"
    if not isinstance(processed, str) or (raw is not None and not isinstance(raw, str)) or not isinstance(cell, str):
        return None, "processed, raw and cell must be strings"
    if threshold is None:
        return None, "threshold must be between 0 and 1"
    settings, why = _settings(body.get("settings"))
    if settings is None:
        return None, why
    clicks = None
    if mode == "replay":
        raw_clicks = body.get("clicks")
        clicks = [_point(c) for c in raw_clicks] if isinstance(raw_clicks, list) and 1 <= len(raw_clicks) <= 2 else None
        if not clicks or None in clicks:
            return None, "replay needs one or two clicks as [x, y]"
    return matlab.Run(mode, processed, raw, cell, threshold, clicks, settings), ""


async def bundle_response(request: Request, job: matlab.Run) -> Response:
    """The run as a zip for the signed-in person (app/analysis/matlab_bundle.py),
    their own MATLAB path inside. ImageError is the caller's to answer."""
    processed, raw = await run(_library(request).matlab_pair, job.processed, job.raw)
    name, data = await run(matlab_bundle.build, job, processed, raw, actor_from(request).user.matlab_path)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def matlab_bundle_download(request: Request) -> Response:
    """Body: see matlab_run. The zip "Download MATLAB Replay" saves: the same
    images /file and /processed.tif already give a signed-in person, so this
    needs nothing more than that."""
    body, refused = await _body(request)
    if refused:
        return refused
    job, why = matlab_run(body)
    if job is None:
        return bad_request(why)
    try:
        return await bundle_response(request, job)
    except ImageError as exc:
        return bad_request(str(exc))


async def local_matlab(request: Request) -> Response:
    """Body: see matlab_run. Starts MATLAB's desktop on the original ais_auto.m
    for that image, on this machine (app/analysis/matlab.py)."""
    body, refused = await _local_body(request)
    if refused:
        return refused
    cfg = get_config(request)
    if not from_this_computer(request.scope, cfg):
        return forbidden("MATLAB would open on the server, not your computer: run the MATLAB helper instead")
    job, why = matlab_run(body)
    if job is None:
        return bad_request(why)
    binary = matlab.find_matlab(cfg.matlab)
    if binary is None:
        return bad_request("MATLAB not found: set server.matlab in config.yaml")
    library = _library(request)
    user = _user_id(request)
    try:
        processed_tiff, raw_tiff = await run(library.matlab_pair, job.processed, job.raw)
        stem = await run(matlab.stage, cfg.storage_dir / "ais-matlab" / str(int(user)), job.cell, processed_tiff, raw_tiff)
        await run(matlab.launch, binary, job.mode, stem, job.threshold, job.clicks, job.settings)
    except ImageError as exc:
        return bad_request(str(exc))
    except OSError as exc:
        return bad_request(f"could not start MATLAB: {exc.strerror or exc}")
    return JSONResponse({"ok": True, "folder": str(stem.parent), "matlab": binary})
