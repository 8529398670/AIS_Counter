"""The API docs for ais.py's routes on accepted AIS, measurements, auto runs,
the report and this machine's folders: config/openapi.json and config/api.md
are written from these by scripts/api_docs.sh (see app/apidocs)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, NotRequired, TypedDict

from app.apidocs import ADMIN, SESSION_ONLY, Field, doc, schema
from app.routes import ais

CSRF = Field(doc="From GET /api/me. Browser sessions only.")
EXPECT = Field(doc="The rev you last saw. Answers 409, with the record as it is now, if it has moved on.", minimum=0)


# --- shared shapes ---------------------------------------------------------------


@schema(name="AISResult", doc="One accepted AIS (app/models/ais.py): the trace's measures, clicks and pixels, numbered n on its image. Lengths are µm; null where the trace had no value.")
class AISResultSchema(TypedDict):
    id: int
    batch_id: int
    batch_name: str
    image: Annotated[str, Field(doc="The image's key in its batch.")]
    cell: str
    n: Annotated[int, Field(doc="Its number on the image, 1..k.")]
    created_by: Annotated[int, Field(doc="Who accepted it.")]
    accepted_at: datetime
    client_id: NotRequired[Annotated[str, Field(doc="The browser's own id for it, when it sent one.")]]
    rev: NotRequired[Annotated[int, Field(doc="Bumped by each change; missing until the first.")]]
    edited_at: NotRequired[datetime]
    edited_by: NotRequired[int]
    length_um: float | None
    start_um: float | None
    end_um: float | None
    mid_um: float | None
    max_um: float | None
    arc_um: float | None
    threshold_initial: float | None
    threshold: float | None
    click_x: float | None
    click_y: float | None
    click2_x: float | None
    click2_y: float | None
    profile_points: float | None
    pixconv: float | None
    f: float | None
    kernel: float | None
    sigma: float | None
    strel: float | None
    min_pixels: float | None
    max_path: float | None
    max_passes: float | None
    spline_p: float | None
    window_um: float | None
    width_um: NotRequired[float | None]
    brightness: NotRequired[float | None]
    area_blob_um2: NotRequired[Annotated[float | None, Field(doc="Missing on AIS accepted before area was measured.")]]
    area_width_um2: NotRequired[float | None]
    soma_um: NotRequired[Annotated[float | None, Field(doc="Distance from its start to the soma (the Measure tool); null when cleared.")]]
    soma_px: NotRequired[float | None]
    soma_ais_x: NotRequired[float | None]
    soma_ais_y: NotRequired[float | None]
    soma_x: NotRequired[float | None]
    soma_y: NotRequired[float | None]
    soma_xy_um: NotRequired[float]
    soma_dz_um: NotRequired[float]
    soma_at: NotRequired[datetime | None]
    soma_by: NotRequired[int | None]
    length_str: str
    source: str
    notes: str
    file: str
    sha: str
    smooth: str
    origin: Annotated[str, Field(doc="auto for one auto mode found, empty for a click.")]
    pixels: Annotated[list[list[int]], Field(doc="The trace, as [x, y] pairs.")]
    length_3d_um: NotRequired[float]
    length_xy_um: NotRequired[float]
    z_start: NotRequired[float]
    z_end: NotRequired[float]
    z_span_um: NotRequired[float]
    z_step_um: NotRequired[float]
    z_confidence: NotRequired[float]
    z_clipped: NotRequired[Annotated[float, Field(doc="0 or 1.")]]
    volume_voxel_um3: NotRequired[float]
    volume_tube_um3: NotRequired[float]
    z_ais_start: NotRequired[Annotated[float, Field(doc="Ends from the slices: the AIS start found on the 3D route, a profile point.")]]
    z_ais_end: NotRequired[Annotated[float, Field(doc="Ends from the slices: the AIS end found on the 3D route, a profile point.")]]
    z_method: NotRequired[str]
    z_path: NotRequired[Annotated[list[Any], Field(doc="The z of each pixel (a number), null outside the AIS. Z-stacks only.")]]
    auto_method: NotRequired[str]
    auto_review: NotRequired[str]
    auto_start: NotRequired[str]
    auto_min_length: NotRequired[float]
    auto_min_length_shown: NotRequired[float]
    auto_min_brightness: NotRequired[float]
    auto_min_contrast: NotRequired[float]
    auto_min_width: NotRequired[float]
    auto_max_soma_gap: NotRequired[float]
    auto_max_branchiness: NotRequired[float]
    auto_min_score: NotRequired[float]


@schema(name="Measurement", doc="A line the Measure tool recorded on an image: its ends in MATLAB axes, its length, and the pixel size that length was worked out with.")
class MeasurementSchema(TypedDict):
    id: int
    batch_id: int
    batch_name: str
    image: str
    n: Annotated[int, Field(doc="Its number on the image, 1..k.")]
    created_by: int
    created_at: datetime
    client_id: NotRequired[str]
    rev: NotRequired[int]
    edited_at: NotRequired[datetime]
    edited_by: NotRequired[int]
    a_x: float
    a_y: float
    b_x: float
    b_y: float
    length_px: float
    length_um: float
    pixconv: float
    label: str
    type: NotRequired[Annotated[str, Field(doc="One of the team's measurement types, or empty.")]]


class AutoRunSchemaError(TypedDict):
    image: Annotated[str | None, Field(doc="The image's key; null when the run failed between images.")]
    error: str


class AutoRunSchemaChoices(TypedDict):
    general: Annotated[dict[str, Any], Field(doc="Settings' general fields, as GET /api/ais/auto/defaults lists them.")]
    settings: Annotated[dict[str, Any], Field(doc="The method's settings.")]
    threshold: float
    engine: Annotated[str | None, Field(doc="fast, or null for the original port.")]


@schema(name="AutoRun", doc="An auto run on the server (app/analysis/auto_runner.py). Kept in memory: a restart forgets it.")
class AutoRunSchema(TypedDict):
    id: str
    batch_id: int
    user_id: Annotated[int, Field(doc="Who started it.")]
    state: Annotated[str, Field(enum=("queued", "running", "finished", "stopped", "failed"))]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    done: Annotated[int, Field(doc="Images worked through.")]
    total: Annotated[int, Field(doc="Images it will work through.")]
    found: Annotated[int, Field(doc="AIS that passed the filters.")]
    hidden: Annotated[int, Field(doc="AIS the filters left out.")]
    saved: Annotated[int, Field(doc="AIS saved to the batch.")]
    marked_done: int
    errors: list[AutoRunSchemaError]
    current: Annotated[str | None, Field(doc="The image it is on.")]
    skip_done: bool
    mark_done: bool
    choices: AutoRunSchemaChoices
    images: Annotated[list[str], Field(doc="The image keys it works through, in order.")]


class MatlabRunBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    mode: NotRequired[Annotated[str, Field(enum=("open", "run", "replay"), doc="Default run.")]]
    processed: Annotated[str, Field(doc="The traced image's file id (its sha-256).")]
    raw: NotRequired[Annotated[str | None, Field(doc="The profile image's file id, when the cell has both.")]]
    cell: Annotated[str, Field(doc="The cell's name as the browser shows it: a blinded name stays blind.")]
    threshold: NotRequired[Annotated[float, Field(minimum=0, maximum=1, doc="Default 0.01.")]]
    settings: NotRequired[Annotated[dict[str, Any] | None, Field(doc="The method settings (app/analysis/ais_auto.Settings); missing ones are the original's.")]]
    clicks: NotRequired[Annotated[list[list[float]], Field(doc="replay: one or two clicks as [x, y].")]]


class RenumberedItem(TypedDict):
    id: int
    n: int


# --- accepted AIS ----------------------------------------------------------------


class ResultListParams(TypedDict):
    batch: Annotated[str, Field(query="batch", doc="A batch id; anything else lists every batch's.")]


class ResultListReply(TypedDict):
    results: Annotated[list[AISResultSchema], Field(doc="Oldest first.")]


doc(
    ais.result_list,
    summary="Accepted AIS",
    tag="AIS",
    description="?batch=<id> for one batch, anything else for all.",
    params=ResultListParams,
    reply=ResultListReply,
    errors=(401,),
)


class ResultAddBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    batch_id: int
    image: Annotated[str, Field(doc="The image's key in the batch.")]
    row: Annotated[dict[str, Any], Field(doc="The accepted trace's numbers, texts and pixels, as POST /api/ais/trace gives them.")]
    client_id: NotRequired[Annotated[str, Field(doc="Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the AIS already made.")]]


doc(
    ais.result_add,
    summary="Accept an AIS",
    tag="AIS",
    description="Body: {batch_id, image, row} with row the accepted trace's numbers.",
    body=ResultAddBody,
    reply=AISResultSchema,
    errors=(400, 401, 403),
)


class ResultImportBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    name: NotRequired[Annotated[str, Field(doc="The new batch's name. Default Imported from browser.")]]
    rows: Annotated[list[dict[str, Any]], Field(doc="1 to 5000 accepted rows, each with its image (the cell) and optionally its sha.")]


class ResultImportReply(TypedDict):
    batch_id: Annotated[int, Field(doc="The new batch they went into.")]


doc(
    ais.result_import,
    summary="Import results",
    tag="AIS",
    description="Body: {name, rows}: results kept in a browser before they lived here.",
    mcp_http="A results file upload: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key.",
    body=ResultImportBody,
    reply=ResultImportReply,
    errors=(400, 401, 403),
)


class ResultParams(TypedDict):
    result_id: Annotated[int, Field(path="result_id")]


class ResultDeleteBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    expect: NotRequired[Annotated[int, EXPECT]]


class ResultDeleteReply(TypedDict):
    ok: bool
    renumbered: Annotated[list[RenumberedItem], Field(doc="The image's other AIS whose number changed, with their new n.")]


doc(
    ais.result_delete,
    summary="Delete an accepted AIS",
    tag="AIS",
    params=ResultParams,
    body=ResultDeleteBody,
    reply=ResultDeleteReply,
    errors=(400, 401, 403, 404, 409),
)


class ResultUpdateBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    expect: NotRequired[Annotated[int, EXPECT]]
    row: Annotated[dict[str, Any], Field(doc="The new trace's numbers, texts and pixels, as POST /api/ais/trace gives them.")]


doc(
    ais.result_update,
    summary="Change an accepted AIS",
    tag="AIS",
    description="Body: {row}: an accepted AIS traced again (the Edit tool). It keeps its number and origin.",
    params=ResultParams,
    body=ResultUpdateBody,
    reply=AISResultSchema,
    errors=(400, 401, 403, 404, 409),
)


class SomaBody(TypedDict):
    soma_um: float
    soma_px: float
    soma_ais_x: float
    soma_ais_y: float
    soma_x: float
    soma_y: float
    soma_xy_um: NotRequired[Annotated[float, Field(doc="Z-stacks: the distance across the image.")]]
    soma_dz_um: NotRequired[Annotated[float, Field(doc="Z-stacks: the distance in depth.")]]


class ResultSomaBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    expect: NotRequired[Annotated[int, EXPECT]]
    soma: Annotated[SomaBody | None, Field(doc="Every number 0 or more; null clears it.")]


doc(
    ais.result_soma,
    summary="Set an accepted AIS's soma",
    tag="AIS",
    description="Body: {soma}: an accepted AIS's distance to its soma (the Measure tool), or null to clear it. The trace is left as it is.",
    params=ResultParams,
    body=ResultSomaBody,
    reply=AISResultSchema,
    errors=(400, 401, 403, 404, 409),
)


# --- recorded measurements --------------------------------------------------------


class MeasureTypesReply(TypedDict):
    types: list[str]


doc(
    ais.measure_types,
    summary="The team's measurement types for the Measure tool's Type picker",
    tag="AIS",
    description="The team's measurement types for the Measure tool's Type picker.",
    reply=MeasureTypesReply,
    errors=(401,),
)


class MeasureTypesSetBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    types: Annotated[list[str], Field(doc="1 to 50 names, up to 100 characters each, in order. Repeats are dropped.")]


class MeasureTypesSetReply(TypedDict):
    types: Annotated[list[str], Field(doc="The list as saved.")]


doc(
    ais.measure_types_set,
    summary="Set the measurement types",
    tag="AIS",
    description="Body: {types: [name, ...]}: the team's new list (admins).",
    role=ADMIN,
    body=MeasureTypesSetBody,
    reply=MeasureTypesSetReply,
    errors=(400, 401, 403),
)


class MeasurementListParams(TypedDict):
    batch: Annotated[str, Field(query="batch", doc="A batch id; anything else lists every batch's.")]


class MeasurementListReply(TypedDict):
    measurements: Annotated[list[MeasurementSchema], Field(doc="Oldest first.")]


doc(
    ais.measurement_list,
    summary="Recorded measurements",
    tag="AIS",
    description="?batch=<id> for one batch, anything else for all.",
    params=MeasurementListParams,
    reply=MeasurementListReply,
    errors=(401,),
)


class MeasurementBody(TypedDict):
    a_x: float
    a_y: float
    b_x: float
    b_y: float
    length_px: float
    length_um: float
    pixconv: float
    label: NotRequired[str]
    type: NotRequired[Annotated[str, Field(doc="One of the team's measurement types, or empty.")]]


class MeasurementAddBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    batch_id: int
    image: Annotated[str, Field(doc="The image's key in the batch.")]
    measurement: Annotated[MeasurementBody, Field(doc="Every number 0 or more.")]
    client_id: NotRequired[Annotated[str, Field(doc="Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the line already made.")]]


doc(
    ais.measurement_add,
    summary="Record a measurement",
    tag="AIS",
    description="Body: {batch_id, image, measurement}: a line recorded on an image.",
    body=MeasurementAddBody,
    reply=MeasurementSchema,
    errors=(400, 401, 403),
)


class MeasurementParams(TypedDict):
    measurement_id: Annotated[int, Field(path="measurement_id")]


class MeasurementUpdateBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    expect: NotRequired[Annotated[int, EXPECT]]
    measurement: MeasurementBody


doc(
    ais.measurement_update,
    summary="Change a measurement",
    tag="AIS",
    description="Body: {measurement}: a recorded line's new ends, length and label.",
    params=MeasurementParams,
    body=MeasurementUpdateBody,
    reply=MeasurementSchema,
    errors=(400, 401, 403, 404, 409),
)


class MeasurementDeleteBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    expect: NotRequired[Annotated[int, EXPECT]]


class MeasurementDeleteReply(TypedDict):
    ok: bool
    renumbered: Annotated[list[RenumberedItem], Field(doc="The image's other lines whose number changed, with their new n.")]


doc(
    ais.measurement_delete,
    summary="Delete a measurement",
    tag="AIS",
    params=MeasurementParams,
    body=MeasurementDeleteBody,
    reply=MeasurementDeleteReply,
    errors=(400, 401, 403, 404, 409),
)


# --- auto runs on the server ------------------------------------------------------


class AutoListParams(TypedDict):
    batch: Annotated[int, Field(query="batch", doc="A batch id: only its runs.")]


class AutoListReply(TypedDict):
    runs: Annotated[list[AutoRunSchema], Field(doc="Newest first.")]


doc(
    ais.auto_list,
    summary="Auto runs on the server",
    tag="AIS",
    description="The auto runs the server has done since it started, newest first. ?batch=<id> narrows them.",
    params=AutoListParams,
    reply=AutoListReply,
    errors=(400, 401),
)


class AutoDefaultsReply(TypedDict):
    general: Annotated[dict[str, Any], Field(doc="Settings' general fields and their defaults.")]
    ranges: Annotated[dict[str, list[float]], Field(doc="The [lowest, highest] each number in general may be.")]
    methods: list[str]
    starts: list[str]
    threshold: float
    settings: Annotated[dict[str, Any], Field(doc="The method's settings and their defaults.")]
    engines: Annotated[list[Any], Field(doc="Each null (the original port) or fast (app/analysis/fast.py).")]
    z_methods: Annotated[list[str], Field(doc="The Z-stack length methods ready to use.")]


doc(
    ais.auto_defaults,
    summary="Auto mode defaults",
    tag="AIS",
    description="What a run uses unless it says otherwise (static/js/settings.js defaults), and what it may set: general, ranges, methods, starts, threshold, settings, engines, z_methods.",
    reply=AutoDefaultsReply,
    errors=(401,),
)


class AutoRunParams(TypedDict):
    run_id: Annotated[str, Field(path="run_id")]


doc(
    ais.auto_get,
    summary="One auto run",
    tag="AIS",
    description="How far the run has got: state (queued, running, finished, stopped, failed), done, total, found, hidden, saved, errors.",
    params=AutoRunParams,
    reply=AutoRunSchema,
    errors=(401, 404),
)


class AutoCancelBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]


doc(
    ais.auto_cancel,
    summary="Stop an auto run",
    tag="AIS",
    description="Stops after the image it is on; what it saved stays. Whoever started it, or an admin.",
    params=AutoRunParams,
    body=AutoCancelBody,
    reply=AutoRunSchema,
    errors=(400, 401, 403, 404),
)


# --- the report -------------------------------------------------------------------


class ReportParams(TypedDict):
    batch: Annotated[str, Field(query="batch", doc="all (default), a batch id, or ids separated by commas")]
    everything: Annotated[str, Field(query="everything", enum=("0", "1", "false", "true"), doc="0 or 1: also the images left out")]
    unblind: Annotated[str, Field(query="unblind", enum=("0", "1", "false", "true"), doc="0 or 1 (admins): original names")]
    sheets: Annotated[str, Field(query="sheets", doc="sheet names separated by commas: only those")]


class ReportBatch(TypedDict):
    id: int
    name: str


class ReportSheet(TypedDict):
    columns: list[str]
    rows: Annotated[list[dict[str, Any]], Field(doc="One object per row, keyed by column.")]


class BatchReportReply(TypedDict):
    batches: list[ReportBatch]
    unblinded: Annotated[bool, Field(doc="Whether blinded images are under their original names.")]
    everything: bool
    sheets: Annotated[dict[str, ReportSheet], Field(doc="By name: summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment and statistics once images have treatments.")]


doc(
    ais.batch_report,
    summary="The batch report as JSON",
    tag="AIS",
    description="The Batches screen's report (report.xlsx) as JSON sheets, each {columns, rows}: summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment and statistics. Images left out are not in it unless everything=1; unblind=1 (admins only) puts blinded images under their original names. See app/analysis/report.py.",
    params=ReportParams,
    reply=BatchReportReply,
    errors=(400, 401, 404),
)


# --- folders on this machine, and MATLAB ---------------------------------------------


class LocalStatusReply(TypedDict):
    enabled: Annotated[bool, Field(doc="Open path works for you: an admin with a browser session, on a server that allows it.")]
    platform: Annotated[str, Field(enum=("mac", "windows", "linux"), doc="The server's.")]
    matlab: Annotated[bool, Field(doc="MATLAB can open on this machine and you are sitting at it.")]
    helper_enabled: Annotated[bool, Field(doc="The MATLAB helper is switched on.")]
    helper: Annotated[bool, Field(doc="Your MATLAB helper has polled lately.")]


doc(
    ais.local_status,
    summary="Whether folders on this computer and MATLAB are available",
    tag="AIS",
    mcp_http="Whether Open path and MATLAB work on this machine: those routes need a browser session.",
    reply=LocalStatusReply,
    errors=(401,),
)


class LocalPathBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]
    path: Annotated[str, Field(doc="An absolute path on this machine.")]


class LocalListReplyFile(TypedDict):
    name: str
    size: Annotated[int, Field(doc="Bytes.")]


class LocalListReply(TypedDict):
    path: str
    parent: Annotated[str | None, Field(doc="null at the top.")]
    dirs: list[str]
    files: Annotated[list[LocalListReplyFile], Field(doc="Its TIFFs.")]


doc(
    ais.local_list,
    summary="List a folder on this computer",
    tag="AIS",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=LocalListReply,
    errors=(400, 401, 403),
)


class LocalStacksReplyStack(TypedDict):
    cell: str
    slices: int


class LocalStacksReply(TypedDict):
    stacks: list[LocalStacksReplyStack]


doc(
    ais.local_stacks,
    summary="Find Z-stacks in a folder on this computer",
    tag="AIS",
    description="Body: {path}. The Z-stacks under a folder, by name, for the Add dialog to ask about before the server hashes anything.",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=LocalStacksReply,
    errors=(400, 401, 403),
)


class ChannelLayout(TypedDict):
    kind: Annotated[str, Field(enum=("czi", "tiff"))]
    names: list[str]


class ChannelRole(TypedDict):
    role: Annotated[str, Field(enum=("ais", "soma", "other"))]
    label: str


class LocalChannelsReplyLayout(TypedDict):
    layout: ChannelLayout
    colors: Annotated[list[str] | None, Field(doc="#rrggbb per channel, for a .czi; null for a TIFF.")]
    count: Annotated[int, Field(doc="Files with this layout.")]
    roles: list[ChannelRole]
    stacks: Annotated[int, Field(doc="How many of those files are Z-stack slices.")]


class LocalChannelsReply(TypedDict):
    layouts: list[LocalChannelsReplyLayout]


doc(
    ais.local_channels,
    summary="Find channel layouts in a folder on this computer",
    tag="AIS",
    description="Body: {path}. The channel layouts of a folder's images, for the Add dialog to ask about before the server hashes anything.",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=LocalChannelsReply,
    errors=(400, 401, 403),
)


class LocalOkReply(TypedDict):
    ok: bool


doc(
    ais.local_reveal,
    summary="Show a file in Finder",
    tag="AIS",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=LocalOkReply,
    errors=(400, 401, 403),
)


doc(
    ais.local_open,
    summary="Open a file on this computer",
    tag="AIS",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=LocalOkReply,
    errors=(400, 401, 403),
)


class LocalChooseBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, CSRF]]


class LocalChooseReply(TypedDict):
    path: Annotated[str | None, Field(doc="null when cancelled.")]
    cancelled: bool


doc(
    ais.local_choose,
    summary="Pick a folder on this computer",
    tag="AIS",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalChooseBody,
    reply=LocalChooseReply,
    errors=(400, 401, 403),
)


class LocalMatlabReply(TypedDict):
    ok: bool
    folder: Annotated[str, Field(doc="Where the image was staged for MATLAB.")]
    matlab: Annotated[str, Field(doc="The MATLAB that was started.")]


doc(
    ais.local_matlab,
    summary="Verify an image in MATLAB on this computer",
    tag="AIS",
    description="Body: see matlab_run. Starts MATLAB's desktop on the original ais_auto.m for that image, on this machine (app/analysis/matlab.py).",
    access=SESSION_ONLY,
    role=ADMIN,
    body=MatlabRunBody,
    reply=LocalMatlabReply,
    errors=(400, 401, 403),
)


doc(
    ais.matlab_bundle_download,
    summary="Download a MATLAB replay zip",
    tag="AIS",
    description="Body: see matlab_run. The zip \"Download MATLAB Replay\" saves: the same images /file and /processed.tif already give a signed-in person, so this needs nothing more than that.",
    mcp_http="A MATLAB run as a zip download for a person's computer.",
    body=MatlabRunBody,
    reply_type="application/zip",
    errors=(400, 401, 403),
)
