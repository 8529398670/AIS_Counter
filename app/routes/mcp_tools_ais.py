"""The AIS tools /mcp offers: everything a person does on the Process and
Batches screens, for an agent with an API key -- batches and folders, the
images in them, tracing and auto mode, results and recorded lines,
treatments and blinding, and the reports and comparison as JSON.

Each tool is the HTTP route of the same name, called in-process: the tool
builds the request the route would get (same actor, same key, a JSON body)
and awaits the route's own handler, then hands its answer back -- an error
answer as a Refusal with the route's own wording. So a rule a route enforces
(who may change a row, what a blinded user may see, what a value may be)
holds through /mcp without being written twice, and a fix to a route is a
fix to its tool. The route guards are mirrored by admin_only: a tool for an
`admins` route is admin_only, and no tool reaches a route that needs a
browser session (RequireSession) -- those stay out on purpose, see
mcp_tools.py.

What is not here: deleting a batch or a folder, resetting a whole batch,
opening a folder on this machine, and sending a run to a MATLAB helper.
Deletes are limited to one result, one recorded line, and a batch's auto
results (reset_batch_auto).

Files do not travel through /mcp (its body limit is the server's 1 MiB, and
a TIFF pair is several MB): upload_instructions says how to POST each file's
bytes to /api/ais/files with the same API key.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from app.analysis import auto_params as ap
from app.analysis import auto_runner
from app.mcp.registry import Call, Content, InvalidArguments, Refusal, Registry, Tool
from app.models import ais as batches
from app.routes import ais
from app.routes.helpers import get_config

# --- argument schemas ---------------------------------------------------------------

BATCH_ID = {"type": "integer", "minimum": 1, "description": "The batch's id, from list_batches."}
IMAGE = {"type": "string", "description": "The image's key in the batch (batch_status or get_batch: key)."}
RESULT_ID = {"type": "integer", "minimum": 1, "description": "The result's id, from list_results."}
MEASUREMENT_ID = {"type": "integer", "minimum": 1, "description": "The recorded line's id, from list_measurements."}
FOLDER_ID = {"type": "integer", "minimum": 1, "description": "The folder's id, from list_folders."}
PARENT_ID = {"type": ["integer", "null"], "description": "The parent folder's id, or null for the top."}
EXPECT = {"type": "integer", "minimum": 0,
          "description": "The rev you last saw (optional). If someone changed it since, the call is refused with the current one."}
CLIENT_ID = {"type": "string", "pattern": "^[A-Za-z0-9-]{8,64}$",
             "description": "Your own id for this create (8-64 letters, digits, -). Sent again, it finds the first one instead of adding a second."}
POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
         "description": "[x, y] in MATLAB axes: x = column, y = row, pixel centres at 1..n."}
FILES = {"type": "array", "description": "The files, hashed on your side: name and rel (path inside the picked folder) as they are, sha256 of the bytes, size in bytes.",
         "items": {"type": "object", "required": ["name", "rel", "sha", "size"],
                   "properties": {"name": {"type": "string"}, "rel": {"type": "string"},
                                  "sha": {"type": "string", "description": "sha-256 of the file, lower-case hex."},
                                  "size": {"type": "integer"}, "modified": {"type": "number"},
                                  "layout": {"type": "object", "description": "Its channels, for channels: {kind: czi | tiff, names: [...]} (a .czi's channel names; a TIFF's planes as Red/Green/Blue or Channel N)."},
                                  "zstack": {"type": "object", "description": "A .czi with more than one Z plane (a Z-stack): {slices, phases (ApoTome grid phases, 1 without), z_step_um, pixel_um} from its metadata (Scaling X and Z, in microns). Needs layout."}}}}
TRANSLATIONS = {"type": "array", "description": "__Translation.txt files that came with them: [{dir, text}].",
                "items": {"type": "object", "properties": {"dir": {"type": "string"}, "text": {"type": "string"}}}}
CHANNELS = {"type": "array", "description": "Channel roles per layout: [{layout: {kind, names}, roles: [{role: ais | soma | other, label}]}], one role per channel, exactly one ais, at most one soma, a label for each other. Images whose file layout matches get them; left out, the AIS is guessed (a .czi's Alexa Fluor 488, a TIFF's first plane).",
            "items": {"type": "object", "properties": {"layout": {"type": "object"}, "roles": {"type": "array"}}}}
STACK = {"type": "object", "description": "Z-stack TIFF slices (name_zNNN.tif) become one image each stack: {plane: 0 red | 1 green | 2 blue | 3, z_step_um, pixel_um}.",
         "properties": {"plane": {"type": "integer"}, "z_step_um": {"type": "number"}, "pixel_um": {"type": "number"}}}
CZI_STACK = {"type": "object", "description": "Z-stack .czi files (files with zstack) become one image each: {apotome: sectioned (default) | widefield}, how an ApoTome stack's grid phases are made into slices. Their AIS channel is guessed (Alexa Fluor 488) unless channels says.",
             "properties": {"apotome": {"type": "string", "enum": ["sectioned", "widefield"]}}}
RANDOMIZE = {"type": "boolean", "description": "Blind the names (default true): images get random n-n-n names, the originals kept for admins."}
GENERAL = {"type": "object", "description": "Settings' general auto mode fields (see auto_defaults), e.g. {auto_method: 'fitted', fitted_min_length: 13}. Left out: the defaults."}
SETTINGS = {"type": "object", "description": "The method settings (see auto_defaults: settings), e.g. {pixconv: 0.161}. Left out: the defaults."}
THRESHOLD = {"type": "number", "minimum": 0, "maximum": 1, "description": "Default 0.01 (0 = Otsu)."}
ENGINE = {"type": ["string", "null"], "enum": ["fast", None], "description": "fast: Settings' Method 'ais_auto.m (fast)', the same answer, sooner."}
ROW = {"type": "object", "description": "The row as save_result takes it: the 'row' a trace_click or detect_image candidate gives, or your own numbers (app/models/ais.py RESULT_NUMBERS)."}
MEASUREMENT = {"type": "object", "description": "{a_x, a_y, b_x, b_y, length_px, length_um, pixconv, label?, type?}: a line's ends in MATLAB axes and its length."}
# Args a tool's shape reads, never sent to the route.
SHAPE_ONLY = {"limit", "offset", "include_pixels", "archived", "q"}
PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Rows to return. Default 200."},
        "offset": {"type": "integer", "minimum": 0, "description": "Rows to skip: the next value of the previous page."}}

_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _schema(props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = list(required)
    return out


def _bind(call: Call, schema: dict[str, Any]) -> dict[str, Any]:
    """The arguments checked against the tool's schema at the top level:
    no unknown names, the required ones present, each of its type. What is
    inside an object or list is the route's to check."""
    props = schema["properties"]
    unknown = sorted(set(call.args) - set(props))
    if unknown:
        raise InvalidArguments(f"invalid arguments: unknown field {unknown[0]!r}")
    for name in schema.get("required", []):
        if name not in call.args:
            raise InvalidArguments(f"invalid arguments: {name} is required")
    for name, value in call.args.items():
        kinds = props[name].get("type")
        if kinds is None:
            continue
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_JSON_TYPES[k](value) for k in kinds):
            raise InvalidArguments(f"invalid arguments: {name} must be {' or '.join(kinds)}")
    return dict(call.args)


# --- calling a route in-process ----------------------------------------------------------


@dataclass
class Answer:
    status: int
    media_type: str
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


async def _route(call: Call, handler: Callable[[Request], Any], method: str, path: str,
                 path_params: dict[str, Any] | None = None, query: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None) -> Answer:
    """handler's answer to the request it would get for this call: the /mcp
    request's scope (its actor, key and app) at another path."""
    origin = call.request.scope
    params = {k: str(v) for k, v in (path_params or {}).items()}
    for k, v in params.items():
        path = path.replace("{" + k + "}", quote(v, safe=""))
    qs = urlencode({k: ("1" if v is True else "0" if v is False else v) for k, v in (query or {}).items()
                    if v is not None})
    data = json.dumps(body or {}).encode() if method == "POST" else b""
    headers = [(k, v) for k, v in origin.get("headers", []) if k not in (b"content-length", b"content-type")]
    headers += [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]
    scope = dict(origin) | {"method": method, "path": path, "raw_path": path.encode(), "query_string": qs.encode(),
                            "path_params": params, "headers": headers}
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": data, "more_body": False}

    response: Response = await handler(Request(scope, receive))
    return Answer(response.status_code, response.media_type or "", bytes(response.body))


def _ok(answer: Answer) -> Any:
    """The answer's JSON, or a Refusal worded as the route's error."""
    if answer.status >= 400:
        try:
            payload = answer.json()
        except ValueError:
            payload = {}
        message = payload.pop("error", None) if isinstance(payload, dict) else None
        raise Refusal(message or f"refused ({answer.status})", payload if isinstance(payload, dict) else None)
    if answer.media_type.startswith("application/json"):
        return answer.json()
    if answer.media_type.startswith("text/"):
        return {"text": answer.body.decode("utf-8", "replace")}
    raise Refusal("the answer is not JSON")


# --- one tool per route -------------------------------------------------------------------


@dataclass
class AisTool(Tool):
    """A Tool with its own hand-written arguments schema, standing for its
    declared route all the same (endpoint names the route in mcp.json and
    test_mcp_parity.py). The AIS tools call their route in-process (_route)
    with arguments shaped for an agent, so their schema is theirs, not the
    route's request type."""

    schema: dict[str, Any] | None = None

    def arguments(self) -> dict[str, Any]:
        return self.schema or {"type": "object", "properties": {}, "additionalProperties": False}



@dataclass
class Spec:
    """A tool that is one route: which args go in its path, query and body."""

    name: str
    title: str
    description: str
    handler: Callable[[Request], Any]
    path: str
    method: str = "GET"
    props: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    path_args: tuple[str, ...] = ()
    query_args: tuple[str, ...] = ()
    # An arg whose query parameter has another name: batch_id -> ?batch=.
    query_names: dict[str, str] = field(default_factory=dict)
    fixed: dict[str, Any] = field(default_factory=dict)   # always in the body
    defaults: dict[str, Any] = field(default_factory=dict)   # in the body unless the call says otherwise
    # The route's answer made into the tool's: (answer, call) -> result.
    shape: Callable[[Any, Call], Any] | None = None
    admin_only: bool = False
    read_only: bool = False
    destructive: bool = False

    def body_args(self) -> set[str]:
        if self.method != "POST":
            return set()
        return set(self.props) - set(self.path_args) - set(self.query_args) - SHAPE_ONLY

    def tool(self) -> Tool:
        schema = _schema(self.props, self.required)

        async def run(call: Call) -> Any:
            args = _bind(call, schema)
            path_params = {k: args.pop(k) for k in self.path_args if k in args}
            query = {self.query_names.get(k, k): args.pop(k) for k in self.query_args if k in args}
            # What only the shape reads (image, include_pixels, paging) stays out of the body.
            args = {k: v for k, v in args.items() if k in self.body_args()}
            body = (self.defaults | args | self.fixed) if self.method == "POST" else None
            out = _ok(await _route(call, self.handler, self.method, self.path, path_params, query, body))
            return self.shape(out, call) if self.shape else out

        return AisTool(name=self.name, title=self.title, description=self.description, call=run, schema=schema,
                    read_only=self.read_only, destructive=self.destructive, admin_only=self.admin_only,
                    endpoint=self.handler)


def _brief(batch: dict[str, Any]) -> dict[str, Any]:
    """A batch an edit answers with, without its image list (get_batch has it)."""
    images = batch.get("images", [])
    missing = sorted({f["sha"] for im in images for f in _real(im) if not f.get("stored")})
    out = {k: batch.get(k) for k in ("id", "name", "source", "created_by", "created_at", "updated_at", "archived_at",
                                     "folder_id", "excluded", "skipped", "assignment", "rev")}
    out |= {"images": len(images), "missing_files": len(missing)}
    extra = {k: batch[k] for k in ("renamed", "measured", "named", "unnamed", "deleted") if k in batch}
    return out | extra


def _real(image: dict[str, Any]) -> list[dict[str, Any]]:
    return [part for f in image.get("files", {}).values() for part in f.get("slices", [f])]


def _shape_brief(out: Any, _: Call) -> Any:
    if isinstance(out, dict) and "batch" in out and isinstance(out["batch"], dict):
        return out | {"batch": _brief(out["batch"])}
    return _brief(out) if isinstance(out, dict) and "images" in out else out


def _page(rows: list[Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
    limit, offset = args.get("limit", 200), args.get("offset", 0)
    if not 1 <= limit <= 1000:
        raise Refusal("limit must be 1-1000")
    if offset < 0:
        raise Refusal("offset must be 0 or more")
    total = len(rows)
    start = min(offset, total)
    end = min(start + limit, total)
    return {name: rows[start:end], "next": end if end < total else None, "total": total}


def _shape_results(out: Any, call: Call) -> Any:
    args = call.args
    rows = out["results"]
    if "image" in args:
        rows = [r for r in rows if r["image"] == args["image"]]
    if not args.get("include_pixels"):
        rows = [{k: v for k, v in r.items() if k not in ("pixels", "z_path")} for r in rows]
    return _page(rows, "results", args)


def _shape_measurements(out: Any, call: Call) -> Any:
    args = call.args
    lines = out["measurements"]
    if "image" in args:
        lines = [m for m in lines if m["image"] == args["image"]]
    return _page(lines, "measurements", args)


def _shape_batches(out: Any, call: Call) -> Any:
    args = call.args
    rows = out["batches"]
    if not args.get("archived"):
        rows = [b for b in rows if not b.get("archived_at")]
    if "folder_id" in args:
        rows = [b for b in rows if b.get("folder_id") == args["folder_id"]]
    if args.get("q"):
        q = args["q"].lower()
        rows = [b for b in rows if q in b["name"].lower()]
    return _page(rows, "batches", args) | {"folders": out["folders"]}


def _shape_status(out: Any, call: Call) -> Any:
    args = call.args
    return _page(out["images"], "images", args) | {"id": out["id"]}


def _upload_recipe(call: Call) -> dict[str, Any]:
    base = str(call.request.base_url).rstrip("/")
    url = base + "/api/ais/files"
    return {"url": url, "method": "POST",
            "headers": {"Authorization": "Bearer <your API key>", "Content-Type": "application/octet-stream"},
            "body": f"the file's raw bytes (up to {get_config(call.request).upload_limit_bytes // 2**20} MiB)",
            "answer": "{sha256, width, height, dtype, czi, z?}: sha256 must be the one you listed",
            "curl": f"curl -sS -X POST {url} -H 'Authorization: Bearer $AIS_KEY' "
                    "-H 'Content-Type: application/octet-stream' --data-binary @<file>"}


def _missing(batch: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for image in batch.get("images", []):
        for f in _real(image):
            if not f.get("stored") and f["sha"] not in seen:
                seen[f["sha"]] = {"sha": f["sha"], "name": f.get("name"), "rel": f.get("rel"), "image": image["key"]}
    return list(seen.values())


def _shape_created(out: Any, call: Call) -> Any:
    """A batch files were added to: what the server still needs, and how to send it."""
    return {"batch": _brief(out), "missing": _missing(out), "upload": _upload_recipe(call)}


# --- tools that do more than pass a call on ----------------------------------------------


async def _image(call: Call, batch_id: int, key: str) -> dict[str, Any]:
    batch = await run_in_threadpool(batches.get_batch, call.store, batch_id)
    if batch is None:
        raise Refusal("no such batch")
    image = next((im for im in batch["images"] if im["key"] == key), None)
    if image is None:
        raise Refusal("no such image in this batch")
    return image


def _image_body(image: dict[str, Any], settings: dict[str, Any], threshold: float, engine: Any,
                z_method: str) -> dict[str, Any]:
    """What Ais.traceBody and AisAuto.find send for an image."""
    files = image["files"]
    kind = ap.kind(files)
    body = {"processed": batches.traced_sha(image, ap.traced(files)),
            "raw": batches.traced_sha(image, "raw") if kind == "pair" else None,
            "threshold": threshold, "settings": settings | ({"pixconv": image["pixel_um"]}
                                                             if image.get("pixel_um") and not files.get("stack") else {})}
    if engine:
        body["engine"] = engine
    if files.get("stack"):
        body["z_method"] = z_method
    return body


TRACE_SCHEMA = _schema({"batch_id": BATCH_ID, "image": IMAGE, "click": POINT,
                        "click2": POINT | {"description": "The second click after re-thresholding; default the first again."},
                        "threshold": THRESHOLD, "settings": SETTINGS, "engine": ENGINE,
                        "z_method": {"type": "string", "description": "A Z-stack's method (default trace_lift)."}},
                       ("batch_id", "image", "click"))


async def trace_click(call: Call) -> dict[str, Any]:
    args = _bind(call, TRACE_SCHEMA)
    image = await _image(call, args["batch_id"], args["image"])
    try:
        g = ap.general({"z_method": args["z_method"]} if "z_method" in args else None)
        choices = auto_runner.plan(None, args.get("settings"), args.get("threshold"), args.get("engine"))
    except ap.ParamError as exc:
        raise Refusal(str(exc)) from None
    body = _image_body(image, choices["settings"], choices["threshold"], choices["engine"], g["z_method"])
    body["click"] = args["click"]
    if "click2" in args:
        body["click2"] = args["click2"]
    result = _ok(await _route(call, ais.trace, "POST", "/api/ais/trace", body=body))
    out = {"result": result}
    if result.get("ok") and result.get("pixels"):
        out["row"] = ap.row_for(image["files"], result, "", ap.kind(image["files"]),
                                batches.traced_sha(image, ap.traced(image["files"])))
    return out


DETECT_SCHEMA = _schema({"batch_id": BATCH_ID, "image": IMAGE, "general": GENERAL, "settings": SETTINGS,
                         "threshold": THRESHOLD, "engine": ENGINE,
                         "include_hidden": {"type": "boolean", "description": "Also list the candidates the filters leave out (default false)."},
                         "verbose": {"type": "boolean", "description": "Keep each candidate's whole trace data (path, spline, profile, component). Default false."}},
                        ("batch_id", "image"))
# What a candidate keeps unless verbose: what the filters and a person look at.
_CANDIDATE_KEEP = ("ok", "stage", "error", "threshold_initial", "threshold", "clicks", "start", "measures", "notes",
                   "shape", "filter", "soma_gap_um", "z", "settings_changed", "rethresholded")


async def detect_image(call: Call) -> dict[str, Any]:
    """AisAuto.find for one image, with the filters applied and each kept
    candidate's row ready for save_result (auto_review "each": you choose)."""
    args = _bind(call, DETECT_SCHEMA)
    image = await _image(call, args["batch_id"], args["image"])
    try:
        choices = auto_runner.plan(args.get("general"), args.get("settings"), args.get("threshold"), args.get("engine"))
    except ap.ParamError as exc:
        raise Refusal(str(exc)) from None
    p = choices["filters"]
    files = image["files"]
    kind = ap.kind(files)
    saved = await run_in_threadpool(batches.list_results, call.store, args["batch_id"])
    body = _image_body(image, choices["settings"], choices["threshold"], choices["engine"], choices["general"]["z_method"])
    body |= {"start": ap.start_for(kind, p["start"], ap.has_soma(image)),
             "exclude": [r["pixels"] for r in saved if r["image"] == image["key"] and r.get("pixels")]}
    out = _ok(await _route(call, ais.detect, "POST", "/api/ais/detect", body=body))
    candidates = []
    for index, c in enumerate(out.get("candidates", [])):
        kept = ap.passes(c, p)
        if not kept and not args.get("include_hidden"):
            continue
        item = c if args.get("verbose") else {k: c[k] for k in _CANDIDATE_KEEP if k in c}
        candidates.append({"index": index, "passes": kept, "row": ap.auto_row(files, c, p, "each", ap.has_soma(image),
                                                                                   batches.traced_sha(image, ap.traced(files))), "candidate": item})
    return {"image": image["key"], "kind": kind, "found": len(out.get("candidates", [])),
            "kept": sum(1 for c in out.get("candidates", []) if ap.passes(c, p)), "candidates": candidates,
            "filters": p, "components": out.get("components"), "failed": out.get("failed")}


UPLOAD_SCHEMA = _schema({"batch_id": BATCH_ID | {"description": "A batch: also list the files it still needs."}})


async def upload_instructions(call: Call) -> dict[str, Any]:
    args = _bind(call, UPLOAD_SCHEMA)
    out: dict[str, Any] = {"upload": _upload_recipe(call)}
    if "batch_id" in args:
        batch = _ok(await _route(call, ais.batch_get, "GET", "/api/ais/batches/{batch_id}",
                                 {"batch_id": args["batch_id"]}))
        out["missing"] = _missing(batch)
    return out


STORED_SCHEMA = _schema({"shas": {"type": "array", "items": {"type": "string"}, "maxItems": 10000,
                                  "description": "sha-256s, lower-case hex."}}, ("shas",))


def files_stored(call: Call) -> dict[str, Any]:
    args = _bind(call, STORED_SCHEMA)
    library = call.request.app.state.ais
    out = {}
    for sha in args["shas"]:
        try:
            out[sha] = isinstance(sha, str) and library.has(sha)
        except Exception:  # noqa: BLE001 -- not a sha: not stored
            out[sha] = False
    return {"stored": out}


IMAGE_SCHEMA = _schema({"sha": {"type": "string", "description": "The file's sha (get_batch: images[].files[role].sha)."},
                        "kind": {"type": "string", "enum": ["view", "thumb", "composite"],
                                 "description": "view (default): the processed image as the Process screen shows it; thumb: small; composite: a .czi's channels together."}},
                       ("sha",))


async def get_image(call: Call) -> Content:
    args = _bind(call, IMAGE_SCHEMA)
    kind = args.get("kind", "view")
    handler = {"view": ais.view, "thumb": ais.thumb, "composite": ais.composite}.get(kind)
    if handler is None:
        raise Refusal("kind must be view, thumb or composite")
    answer = await _route(call, handler, "GET", f"/api/ais/files/{{sha}}/{kind}.png", {"sha": args["sha"]})
    if answer.status >= 400:
        _ok(answer)
    data = base64.b64encode(answer.body).decode()
    return Content([{"type": "image", "data": data, "mimeType": "image/png"}],
                   {"sha": args["sha"], "kind": kind, "bytes": len(answer.body)})


# --- the list ----------------------------------------------------------------------


def _specs() -> list[Spec]:
    b = {"batch_id": BATCH_ID}
    return [
        # browse
        Spec("list_batches", "List batches",
             "Batches in the team's order, a page at a time, with progress (images, included, completed, ais, auto, stored, assignees, live activity) and the folders. Archived ones only with archived: true. next is the offset of the following page, or null.",
             ais.batch_list, "/api/ais/batches",
             props={"archived": {"type": "boolean"}, "folder_id": FOLDER_ID, "q": {"type": "string", "description": "Only names containing this."}} | PAGE,
             shape=_shape_batches, read_only=True),
        Spec("list_folders", "List folders", "The batch folders, each with its parent and order.",
             ais.folder_list, "/api/ais/folders", read_only=True),
        Spec("get_batch", "Get a batch",
             "One batch whole: its images (key, cell, dir, files per role with sha and whether the server has them stored), adds, done marks (skipped), excluded images, assignment. Admins also see original names.",
             ais.batch_get, "/api/ais/batches/{batch_id}", props=b, required=("batch_id",), path_args=("batch_id",),
             read_only=True),
        Spec("batch_status", "Batch image status",
             "Per image, a page at a time: files and how many are stored, accepted AIS (and how many by auto mode), done, duplicate of, assignee, included.",
             ais.batch_status, "/api/ais/batches/{batch_id}/status", props=b | PAGE, required=("batch_id",),
             path_args=("batch_id",), shape=_shape_status, read_only=True),
        Spec("batch_channels", "Batch .czi channels", "The channels of the batch's included .czi files, by name, with how many files have each.",
             ais.batch_channels, "/api/ais/batches/{batch_id}/channels", props=b, required=("batch_id",),
             path_args=("batch_id",), read_only=True),
        Spec("list_results", "List results",
             "Accepted AIS, a page at a time: one batch's, or every batch's without batch_id; image narrows it to one image. Each row's numbers as the export has them (length_um, ...), its rev for update_result, created_by. pixels only with include_pixels: true.",
             ais.result_list, "/api/ais/results",
             props={"batch_id": BATCH_ID, "image": IMAGE, "include_pixels": {"type": "boolean"}} | PAGE,
             query_args=("batch_id",), query_names={"batch_id": "batch"}, shape=_shape_results, read_only=True),
        Spec("list_measurements", "List recorded lines",
             "Lines recorded with the Measure tool, a page at a time: one batch's, or every batch's; image narrows it.",
             ais.measurement_list, "/api/ais/measurements", props={"batch_id": BATCH_ID, "image": IMAGE} | PAGE,
             query_args=("batch_id",), query_names={"batch_id": "batch"}, shape=_shape_measurements, read_only=True),
        Spec("list_measure_types", "List measurement types", "The team's types a recorded line can have.",
             ais.measure_types, "/api/ais/measure-types", read_only=True),
        # batches
        Spec("create_batch", "Create an empty batch", "A new batch with no images yet, in that folder or at the top. Add files with add_files_to_batch.",
             ais.batch_create, "/api/ais/batches", "POST",
             props={"name": {"type": "string"}, "folder_id": FOLDER_ID}, required=("name",), shape=_shape_brief),
        Spec("create_batch_from_files", "Create a batch from files",
             "A new batch from files you hashed (name, rel, sha, size each), grouped into images as the browser does (<cell>.tif raw, '<cell>.tif - Processed method 2.5.tif' processed, .czi, *_zNNN.tif with stack). Duplicates start left out. Answers with the files the server still needs and how to upload them (POST each file's bytes to /api/ais/files with your API key).",
             ais.batch_upload, "/api/ais/batches/upload", "POST",
             props={"name": {"type": "string"}, "files": FILES, "randomize": RANDOMIZE, "translations": TRANSLATIONS,
                    "stack": STACK, "czi_stack": CZI_STACK, "channels": CHANNELS},
             required=("name", "files"), shape=_shape_created),
        Spec("add_files_to_batch", "Add files to a batch",
             "More files into an existing batch, as create_batch_from_files. add_name names this add (a folder name).",
             ais.batch_add, "/api/ais/batches/{batch_id}/upload", "POST",
             props=b | {"files": FILES, "randomize": RANDOMIZE, "add_name": {"type": "string"},
                        "translations": TRANSLATIONS, "stack": STACK, "czi_stack": CZI_STACK, "channels": CHANNELS},
             required=("batch_id", "files"), path_args=("batch_id",), shape=_shape_created),
        Spec("get_channel_layouts", "List a batch's channel layouts",
             "The channel layouts of a batch's images (or one add's): each with its channel names, how many images, the roles in use and how many already have results.",
             ais.batch_layouts, "/api/ais/batches/{batch_id}/layouts", props=b | {"add": {"type": "integer"}},
             required=("batch_id",), path_args=("batch_id",), query_args=("add",), read_only=True),
        Spec("set_channel_roles", "Set channel roles",
             "Which channel is the AIS, soma/dendrite or other, for a batch's (or one add's) images with those layouts; stack: {z_step_um, pixel_um} also sets its Z-stacks' slice spacing and pixel size (the files don't record them); pixel_um sets the microns per pixel its other images are measured with (null: back to the 40x default). Images now traced from other channels or calibration are no longer done; their results stay (3D measures as measured), so look at them again.",
             ais.batch_layouts_set, "/api/ais/batches/{batch_id}/layouts", "POST",
             props=b | {"add": {"type": "integer"}, "channels": CHANNELS,
                        "stack": {"type": "object", "properties": {"z_step_um": {"type": "number"}, "pixel_um": {"type": "number"}}},
                        "pixel_um": {"type": ["number", "null"]}},
             required=("batch_id", "channels"), path_args=("batch_id",)),
        Spec("fill_missing_areas", "Fill in missing AIS areas",
             "For a batch's accepted AIS saved before area (and on Z-stacks volume) was measured: trace each again from its saved clicks and settings and, when it comes out on the same pixels, fill in area_blob_um2, area_width_um2 (and volume_voxel_um3, volume_tube_um3); nothing else changes. with_soma: only AIS whose soma distance has been measured. A few at a time: call again with after until remaining is 0.",
             ais.batch_fill_areas, "/api/ais/batches/{batch_id}/fill-areas", "POST",
             props=b | {"after": {"type": "integer"}, "limit": {"type": "integer"}, "with_soma": {"type": "boolean"}},
             required=("batch_id",), path_args=("batch_id",)),
        Spec("rename_batch", "Rename a batch", "Its accepted AIS carry the new name too. Whoever opened it, or an admin.",
             ais.batch_rename, "/api/ais/batches/{batch_id}/rename", "POST", props=b | {"name": {"type": "string"}},
             required=("batch_id", "name"), path_args=("batch_id",), shape=_shape_brief),
        Spec("archive_batch", "Archive or bring back a batch", "archived: true hides it from the list (its results stay); false brings it back.",
             ais.batch_archive, "/api/ais/batches/{batch_id}/archive", "POST", props=b | {"archived": {"type": "boolean"}},
             required=("batch_id", "archived"), path_args=("batch_id",), shape=_shape_brief),
        Spec("set_images_included", "Include or leave out images",
             "Include these images (included: true) or leave them out for the whole team. Left-out images are skipped by auto runs and the report.",
             ais.batch_include, "/api/ais/batches/{batch_id}/include", "POST",
             props=b | {"keys": {"type": "array", "items": {"type": "string"}}, "included": {"type": "boolean"}},
             required=("batch_id", "keys", "included"), path_args=("batch_id",), shape=_shape_brief),
        Spec("set_image_done", "Mark an image done", "Mark (done: true) or unmark an image done by hand: for images with no AIS worth accepting.",
             ais.batch_done, "/api/ais/batches/{batch_id}/done", "POST",
             props=b | {"image": IMAGE, "done": {"type": "boolean"}}, required=("batch_id", "image", "done"),
             path_args=("batch_id",)),
        Spec("assign_batch", "Assign a batch (admin)", "Split the batch's images among people: shares [{user_id, percent}] (ids from list_team). An empty list clears it.",
             ais.batch_assign, "/api/ais/batches/{batch_id}/assign", "POST",
             props=b | {"shares": {"type": "array", "items": {"type": "object"}}}, required=("batch_id", "shares"),
             path_args=("batch_id",), shape=_shape_brief, admin_only=True),
        Spec("order_batches", "Order batches (admin)", "The team's priority order: batch ids, first on top.",
             ais.batch_order, "/api/ais/batches/order", "POST", props={"ids": {"type": "array", "items": {"type": "integer"}}},
             required=("ids",), admin_only=True),
        Spec("move_batches", "Move batches into a folder (admin)", "Those batches into that folder; folder_id null for the top.",
             ais.batch_move, "/api/ais/batches/move", "POST",
             props={"ids": {"type": "array", "items": {"type": "integer"}}, "folder_id": PARENT_ID},
             required=("ids", "folder_id"), admin_only=True),
        Spec("create_folder", "Create a folder (admin)", "A new folder, first in its parent (null: the top).",
             ais.folder_create, "/api/ais/folders", "POST", props={"name": {"type": "string"}, "parent_id": PARENT_ID},
             required=("name",), admin_only=True),
        Spec("rename_folder", "Rename a folder (admin)", "", ais.folder_rename, "/api/ais/folders/{folder_id}/rename", "POST",
             props={"folder_id": FOLDER_ID, "name": {"type": "string"}}, required=("folder_id", "name"),
             path_args=("folder_id",), admin_only=True),
        Spec("move_folder", "Move a folder (admin)", "Into another folder; parent_id null for the top.",
             ais.folder_move, "/api/ais/folders/{folder_id}/move", "POST",
             props={"folder_id": FOLDER_ID, "parent_id": PARENT_ID}, required=("folder_id", "parent_id"),
             path_args=("folder_id",), admin_only=True),
        Spec("order_folders", "Order folders (admin)", "The order of one folder's folders (parent_id null: the top).",
             ais.folder_order, "/api/ais/folders/order", "POST",
             props={"parent_id": PARENT_ID, "ids": {"type": "array", "items": {"type": "integer"}}},
             required=("parent_id", "ids"), admin_only=True),
        Spec("get_treatments", "Get treatments (admin)", "Each image's original name, saved treatment and the guessed one.",
             ais.batch_treatments, "/api/ais/batches/{batch_id}/treatments", props=b, required=("batch_id",),
             path_args=("batch_id",), read_only=True, admin_only=True),
        Spec("set_treatments", "Set treatments (admin)", "treatments: {image key: treatment name}; \"\" takes one off.",
             ais.batch_treatments_set, "/api/ais/batches/{batch_id}/treatments", "POST",
             props=b | {"treatments": {"type": "object"}}, required=("batch_id", "treatments"), path_args=("batch_id",),
             admin_only=True),
        Spec("get_translation", "Get __Translation.txt (admin)", "The batch's original/random name per file, as text.",
             ais.batch_translation, "/api/ais/batches/{batch_id}/translation.txt", props=b, required=("batch_id",),
             path_args=("batch_id",), read_only=True, admin_only=True),
        Spec("load_translation", "Load a __Translation.txt (admin)", "For a batch blinded somewhere else: the original names of the files it names.",
             ais.batch_translation_load, "/api/ais/batches/{batch_id}/translation", "POST",
             props=b | {"text": {"type": "string"}}, required=("batch_id", "text"), path_args=("batch_id",),
             shape=_shape_brief, admin_only=True),
        Spec("rerandomize_add", "New random names for a folder (admin)",
             "New random names for one add of the batch (add_id from get_batch adds, or \"earlier\"); its results, done marks, exclusions and assignment move with them.",
             ais.batch_rerandomize, "/api/ais/batches/{batch_id}/adds/{add_id}/randomize", "POST",
             props=b | {"add_id": {"type": ["integer", "string"]}}, required=("batch_id", "add_id"),
             path_args=("batch_id", "add_id"), shape=_shape_brief, admin_only=True),
        Spec("get_backup", "Back up a batch (admin)", "The batch as data, with its results and recorded lines and the people in it: what a restorable backup's manifest holds.",
             ais.batch_backup, "/api/ais/batches/{batch_id}/backup", props=b, required=("batch_id",),
             path_args=("batch_id",), read_only=True, admin_only=True),
        # results and lines
        Spec("save_result", "Save an AIS",
             "Accept an AIS on an image: row as trace_click or detect_image gives it (or your own numbers). Give a client_id so a retry never saves it twice.",
             ais.result_add, "/api/ais/results", "POST",
             props={"batch_id": BATCH_ID, "image": IMAGE, "row": ROW, "client_id": CLIENT_ID},
             required=("batch_id", "image", "row")),
        Spec("update_result", "Change an AIS", "An accepted AIS traced again: it keeps its number and origin. Whoever accepted it, the image's assignee, or an admin.",
             ais.result_update, "/api/ais/results/{result_id}/update", "POST",
             props={"result_id": RESULT_ID, "row": ROW, "expect": EXPECT}, required=("result_id", "row"),
             path_args=("result_id",)),
        Spec("set_result_soma", "Set an AIS's soma distance",
             "soma: {soma_um, soma_px, soma_ais_x, soma_ais_y, soma_x, soma_y}, plus on a Z-stack soma_xy_um and soma_dz_um (soma_um is then the 3D distance), or null to clear it. The trace stays as it is.",
             ais.result_soma, "/api/ais/results/{result_id}/soma", "POST",
             props={"result_id": RESULT_ID, "soma": {"type": ["object", "null"]}, "expect": EXPECT},
             required=("result_id", "soma"), path_args=("result_id",)),
        Spec("delete_result", "Delete an AIS", "One accepted AIS gone; the image's others renumbered. Whoever accepted it, the image's assignee, or an admin. Cannot be undone.",
             ais.result_delete, "/api/ais/results/{result_id}/delete", "POST",
             props={"result_id": RESULT_ID, "expect": EXPECT}, required=("result_id",), path_args=("result_id",),
             destructive=True),
        Spec("add_measurement", "Record a line", "A line measured on an image (the Measure tool's Record).",
             ais.measurement_add, "/api/ais/measurements", "POST",
             props={"batch_id": BATCH_ID, "image": IMAGE, "measurement": MEASUREMENT, "client_id": CLIENT_ID},
             required=("batch_id", "image", "measurement")),
        Spec("update_measurement", "Change a recorded line", "Its new ends, length, label and type.",
             ais.measurement_update, "/api/ais/measurements/{measurement_id}/update", "POST",
             props={"measurement_id": MEASUREMENT_ID, "measurement": MEASUREMENT, "expect": EXPECT},
             required=("measurement_id", "measurement"), path_args=("measurement_id",)),
        Spec("delete_measurement", "Delete a recorded line", "Cannot be undone.",
             ais.measurement_delete, "/api/ais/measurements/{measurement_id}/delete", "POST",
             props={"measurement_id": MEASUREMENT_ID, "expect": EXPECT}, required=("measurement_id",),
             path_args=("measurement_id",), destructive=True),
        Spec("set_measure_types", "Set measurement types (admin)", "The team's new list of types: names.",
             ais.measure_types_set, "/api/ais/measure-types", "POST",
             props={"types": {"type": "array", "items": {"type": "string"}}}, required=("types",), admin_only=True),
        Spec("reset_batch_auto", "Delete a batch's auto AIS (admin)",
             "Deletes every AIS auto mode saved on the batch (the rest renumbered) and the done marks of the images they were on, to run auto again. What went is kept in the Batches screen's Trash for 30 days, where a person can put it back.",
             ais.batch_reset, "/api/ais/batches/{batch_id}/reset", "POST", props=b, required=("batch_id",),
             path_args=("batch_id",), fixed={"scope": "auto"}, shape=_shape_brief, destructive=True, admin_only=True),
        # auto runs
        Spec("auto_defaults", "Auto mode defaults",
             "What an auto run or detect_image uses unless told otherwise, and what may be set: general (methods, filters), settings (the method's), threshold, engines, z_methods.",
             ais.auto_defaults, "/api/ais/auto/defaults", read_only=True),
        Spec("start_auto_run", "Start an auto run",
             "Auto mode over a whole batch, run by the server: every included image (less the complete ones unless skip_done: false), each AIS the filters keep saved straight to the batch, as the browser's review 'all'. Answers at once; follow it with get_auto_run. mark_done also marks each image done. images: only these keys.",
             ais.auto_start, "/api/ais/batches/{batch_id}/auto", "POST",
             props=b | {"general": GENERAL, "settings": SETTINGS, "threshold": THRESHOLD, "engine": ENGINE,
                        "skip_done": {"type": "boolean"}, "mark_done": {"type": "boolean"},
                        "images": {"type": "array", "items": {"type": "string"}}},
             required=("batch_id",), path_args=("batch_id",)),
        Spec("get_auto_run", "Auto run status",
             "How far a run has got: state (queued, running, finished, stopped, failed), done/total images, found, hidden, saved, errors per image.",
             ais.auto_get, "/api/ais/auto/{run_id}", props={"run_id": {"type": "string"}}, required=("run_id",),
             path_args=("run_id",), read_only=True),
        Spec("list_auto_runs", "List auto runs", "The server's auto runs since it started, newest first; batch_id narrows them.",
             ais.auto_list, "/api/ais/auto", props={"batch_id": BATCH_ID}, query_args=("batch_id",),
             query_names={"batch_id": "batch"}, read_only=True),
        Spec("cancel_auto_run", "Stop an auto run", "Stops after the image it is on; what it saved stays. Whoever started it, or an admin.",
             ais.auto_cancel, "/api/ais/auto/{run_id}/cancel", "POST", props={"run_id": {"type": "string"}},
             required=("run_id",), path_args=("run_id",)),
        # exports
        Spec("export_report", "Export a report as JSON",
             "The Batches screen's report (report.xlsx) as JSON sheets -- summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment, statistics -- each {columns, rows}. batch: one id, several separated by commas, or all. Left-out images only with everything. unblind (admins): blinded images under their original names. sheets narrows it to those.",
             ais.batch_report, "/api/ais/report",
             props={"batch": {"type": ["integer", "string"], "description": "A batch id, ids separated by commas, or all."},
                    "everything": {"type": "boolean"}, "unblind": {"type": "boolean"},
                    "sheets": {"type": "string", "description": "Sheet names separated by commas."}},
             required=("batch",), query_args=("batch", "everything", "unblind", "sheets"), read_only=True),
        Spec("compare_batches", "Compare batches by treatment (admin)",
             "The comparison export (comparison.xlsx) as JSON: per measure the culture means, the treatment summary, every test with Holm-corrected p and stars, all values and original names, each sheet {columns, rows}; plus the raw groups, pooled, stats. Two batches or more (one culture each) for the tests between cultures. tests: anova, tukey, welch, dunnett, twoway, paired, unpaired, ks; units: culture means, individual values (every one when left out; nothing is averaged per image: each AIS of a treatment within a culture counts alike, and each culture is one n). design: the two-way ANOVA's factors, \"drug x add-on\" (default) or \"treatment x culture\". plots: true adds the box and cumulative plots as SVG.",
             ais.compare_batches, "/api/ais/compare", "POST",
             props={"batch_ids": {"type": "array", "items": {"type": "integer"}},
                    "tests": {"type": "array", "items": {"type": "string"}},
                    "units": {"type": "array", "items": {"type": "string"}},
                    "design": {"type": "string", "enum": ["drug x add-on", "treatment x culture"]},
                    "labels": {"type": "object", "description": "{measure id: name} for the plots' titles."},
                    "plots": {"type": "boolean"}},
             required=("batch_ids",), fixed={"sheets": True}, defaults={"plots": False}, read_only=True,
             admin_only=True),
    ]


def register(registry: Registry) -> None:
    """Every tool names the route it stands for (test_mcp_parity.py). The two
    upload helpers both name POST /api/ais/files: the bytes go there over HTTP,
    and they say how and which are still needed. get_image names view.png; its
    thumb and composite kinds are the other two image routes."""
    for spec in _specs():
        registry.register(spec.tool())
    registry.register(AisTool(
        name="upload_instructions", endpoint=ais.upload, title="How to upload files",
        description="Image bytes do not go through MCP: POST each file's raw bytes to the url given, with your API key (Content-Type: application/octet-stream). With batch_id, also the files that batch still needs (sha, name, rel, image).",
        call=upload_instructions, schema=UPLOAD_SCHEMA, read_only=True))
    registry.register(AisTool(
        name="files_stored", endpoint=ais.upload, title="Which files the server has",
        description="For each sha-256, whether the server already holds that file (so it need not be uploaded again).",
        call=files_stored, schema=STORED_SCHEMA, read_only=True))
    registry.register(AisTool(
        name="get_image", endpoint=ais.view, title="Look at an image",
        description="An image as PNG: the processed view the Process screen traces on (view), a thumbnail (thumb), or a .czi's channels together (composite).",
        call=get_image, schema=IMAGE_SCHEMA, read_only=True))
    registry.register(AisTool(
        name="trace_click", endpoint=ais.trace, title="Trace an AIS from a click",
        description="What a click on the Process screen does: the AIS traced from that point, with the row to save (save_result) when it worked. Uses the auto_defaults settings unless given.",
        call=trace_click, schema=TRACE_SCHEMA, read_only=True))
    registry.register(AisTool(
        name="detect_image", endpoint=ais.detect, title="Find AIS on one image",
        description="Auto mode on one image without saving: every candidate the filters keep (include_hidden: the rest too), each with passes and the row save_result takes -- so you can review and save them yourself. The image's saved AIS are left out of the search.",
        call=detect_image, schema=DETECT_SCHEMA, read_only=True))

