"""The API docs for ais.py's routes on files, tracing, batches, folders, the
trash and comparing (the results, measurements, auto runs, report, local
folders and MATLAB have theirs elsewhere): config/openapi.json and
config/api.md are written from these by scripts/api_docs.sh (see app/apidocs)."""
from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from app.apidocs import ADMIN, SESSION_ONLY, Field, doc
from app.routes import ais

CSRF_DOC = "From GET /api/me. Browser sessions only."
BATCH_DOC = ("The batch record: its images (each file with stored, and for admins the original names), adds, "
             "assignment, skipped, created_by_name, assignee_names, adder_names and excluded.")
FILE_MCP = "File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key."
BACKUP_MCP = "A backup zip: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key."
TRASH_MCP = "The trash only holds what the Batches screen deleted, which agents cannot do."


# --- shared shapes ------------------------------------------------------------


class ShaParams(TypedDict):
    sha: Annotated[str, Field(path="sha", doc="The file's sha-256, as POST /api/ais/files answered.")]


class ShaIndexParams(TypedDict):
    sha: Annotated[str, Field(path="sha", doc="The file's sha-256, as POST /api/ais/files answered.")]
    index: Annotated[int, Field(path="index", minimum=0, doc="0-based.")]


class BatchParams(TypedDict):
    batch_id: Annotated[int, Field(path="batch_id", minimum=1)]


class FolderParams(TypedDict):
    folder_id: Annotated[int, Field(path="folder_id", minimum=1)]


class TrashParams(TypedDict):
    trash_id: Annotated[int, Field(path="trash_id", minimum=1)]


class CsrfBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]


class OkReply(TypedDict):
    ok: bool


class OkTrashReply(TypedDict):
    ok: bool
    trash_id: Annotated[int, Field(doc="Its entry in GET /api/ais/trash.")]


class ChosenFile(TypedDict):
    name: str
    rel: NotRequired[Annotated[str, Field(doc="Its path under the folder picked. Default name.")]]
    sha: Annotated[str, Field(doc="sha-256, hex.")]
    size: NotRequired[int]
    layout: NotRequired[Annotated[dict[str, Any], Field(doc="Its channels as the browser read them.")]]
    modified: NotRequired[Annotated[str, Field(doc="When it was last changed, ISO.")]]


class Translation(TypedDict):
    dir: str
    text: Annotated[str, Field(doc="A __Translation.txt's contents.")]


class ChannelRole(TypedDict):
    role: Annotated[str, Field(enum=("ais", "soma", "other"))]
    label: Annotated[str, Field(doc="The channel's name; empty unless role is other.")]


class ChannelChoice(TypedDict):
    layout: Annotated[dict[str, Any], Field(doc="{kind, names}: a layout as GET .../layouts gives it.")]
    roles: Annotated[list[ChannelRole], Field(doc="One per channel: exactly one ais, at most one soma.")]


class StackOptions(TypedDict):
    plane: Annotated[int, Field(minimum=0, maximum=3, doc="The channel of each slice that is the AIS.")]
    z_step_um: float
    pixel_um: float


class Folder(TypedDict):
    id: int
    name: str
    parent_id: Annotated[int | None, Field(doc="null at the top.")]
    position: int
    created_by: int
    created_at: str
    updated_at: str


class Assignee(TypedDict):
    user_id: int
    name: str
    percent: float
    images: int
    completed: int
    ais: int
    last_at: Annotated[str | None, Field(doc="When an AIS on their images was last accepted or edited.")]


class Activity(TypedDict):
    user_id: int
    kind: Annotated[str, Field(enum=("auto",))]
    state: Annotated[str, Field(enum=("running", "paused", "finished", "stopped"))]
    done: int
    total: int
    at: str


class LiveActivity(Activity):
    name: str


class BatchRow(TypedDict):
    id: int
    name: str
    source: Annotated[str, Field(enum=("upload", "path"))]
    path: Annotated[str | None, Field(doc="An Open-path batch's folder.")]
    created_by: int
    created_by_name: str
    created_at: str
    updated_at: str
    archived_at: str | None
    position: int
    folder_id: int | None
    images: int
    included: int
    completed: int
    adds: Annotated[list[dict[str, Any]], Field(doc="Each time images were added, with added_by_name.")]
    earlier: Annotated[int, Field(doc="Images from before adds were recorded.")]
    randomized: bool
    unnamed: int
    duplicates: int
    ais: int
    auto: int
    files: int
    stored: Annotated[int, Field(doc="Of files, how many the server can show.")]
    assignees: list[Assignee]
    mine: Annotated[Assignee | None, Field(doc="Your own share, if you have one.")]
    activity: Annotated[list[LiveActivity], Field(doc="Auto runs going on in people's browsers.")]
    treatments: NotRequired[Annotated[list[list[Any]], Field(doc="Admins: [[name, images], ...], most images first.")]]
    untreated: NotRequired[Annotated[int, Field(doc="Admins: included images with no treatment.")]]


class TrashSummary(TypedDict):
    id: int
    kind: Annotated[str, Field(enum=("batch", "folder", "reset"))]
    name: str
    deleted_at: str
    deleted_by: int | None
    expires_at: str
    folders: NotRequired[Annotated[int, Field(doc="A folder: the folders it held.")]]
    batches: NotRequired[Annotated[int, Field(doc="A folder: the batches it held.")]]
    results: NotRequired[Annotated[int, Field(doc="A batch or reset: the AIS.")]]
    measurements: NotRequired[Annotated[int, Field(doc="A batch or reset: the recorded lines.")]]
    images: NotRequired[Annotated[int, Field(doc="A batch.")]]
    batch_id: NotRequired[Annotated[int, Field(doc="A batch or reset.")]]
    scope: NotRequired[Annotated[str, Field(enum=("all", "auto"), doc="A reset.")]]


class TrashEntry(TrashSummary):
    deleted_by_name: str
    can_restore: Annotated[bool, Field(doc="Whether you may put it back.")]


class Treatment(TypedDict):
    key: str
    original: Annotated[str, Field(doc="The image's original name.")]
    folder: str
    treatment: Annotated[str, Field(doc="Saved; empty if none.")]
    guess: str
    guess_written: str
    guess_key: str
    included: bool


class TreatmentsReply(TypedDict):
    treatments: list[Treatment]


# --- files ----------------------------------------------------------------------


class UploadParams(TypedDict):
    csrf: Annotated[str, Field(header="X-CSRF-Token", doc="With a raw body from a browser session: its CSRF token.")]


class UploadReply(TypedDict):
    sha256: str
    width: int
    height: int
    dtype: Annotated[str, Field(doc="The pixels' numpy type, uint16 say.")]
    czi: bool


doc(
    ais.upload,
    summary="Upload an image (TIFF or .czi)",
    tag="AIS",
    description=("The file's bytes as application/octet-stream with the CSRF token in X-CSRF-Token (what the page "
                 "sends: no base64, no JSON parse of a 6 MB string), or JSON {data: base64} like every other POST."),
    params=UploadParams,
    body_type="application/octet-stream",
    reply=UploadReply,
    errors=(400, 401, 403),
)

doc(
    ais.view,
    summary="An image for the viewer",
    tag="AIS",
    params=ShaParams,
    reply_type="image/png",
    errors=(401, 404),
)

doc(
    ais.thumb,
    summary="An image's thumbnail",
    tag="AIS",
    mcp_http="Reached through get_image with kind thumb.",
    params=ShaParams,
    reply_type="image/png",
    errors=(401, 404),
)


class FileChannel(TypedDict):
    index: int
    name: str
    color: Annotated[str, Field(doc="#rrggbb.")]


class ChannelsReply(TypedDict):
    channels: list[FileChannel]


doc(
    ais.channels,
    summary="A .czi's channels",
    tag="AIS",
    description="A .czi's channels [{index, name, color}] for the channel buttons; [] for a TIFF.",
    mcp_http="Viewer detail for the Process screen's channel picker; get_batch names each image's files.",
    params=ShaParams,
    reply=ChannelsReply,
    errors=(401, 404),
)

doc(
    ais.channel,
    summary="One .czi channel, for the viewer",
    tag="AIS",
    mcp_http="Viewer images for the Process screen; get_image gives an agent the processed view.",
    params=ShaIndexParams,
    reply_type="image/png",
    errors=(401, 404),
)

doc(
    ais.slice_view,
    summary="One slice of a Z-stack, for the viewer's Z slider",
    tag="AIS",
    description="One slice of a Z-stack, for the viewer's Z slider.",
    mcp_http="Viewer images for the Process screen's z-stack slider; get_image gives an agent the processed view.",
    params=ShaIndexParams,
    reply_type="image/png",
    errors=(401, 404),
)

doc(
    ais.composite,
    summary="A .czi's channels merged in their display colors, for exports",
    tag="AIS",
    description="A .czi's channels merged in their display colors, for exports.",
    mcp_http="Reached through get_image with kind composite.",
    params=ShaParams,
    reply_type="image/png",
    errors=(401, 404),
)


class SomataReply(TypedDict):
    somata: Annotated[list[list[list[int]]], Field(doc="Per soma, its edge pixels as 1-based [x, y].")]


doc(
    ais.somata,
    summary="A .czi's soma outlines",
    tag="AIS",
    description="A .czi's soma outlines (soma.py), each its edge pixels as 1-based [x, y], for the Soma button; [] for a TIFF.",
    mcp_http="Viewer overlay for the Process screen; detect_image and trace_click give an agent the results.",
    params=ShaParams,
    reply=SomataReply,
    errors=(401, 404),
)


class PairTrace(TypedDict):
    id: Annotated[Any, Field(doc="Yours, given back with its pair.")]
    pixels: Annotated[list[list[int]], Field(doc="1-based [x, y] whole numbers.")]


class SomaShape(TypedDict):
    min_um: NotRequired[float]
    max_um: NotRequired[float]
    roundness: NotRequired[Annotated[float, Field(minimum=0, maximum=1)]]


class PairBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    pixel_um: Annotated[float, Field(doc="Microns per pixel, above 0.")]
    traces: Annotated[list[PairTrace], Field(doc="At most 500.")]
    split: NotRequired[Annotated[bool, Field(doc="One soma per hotspot. Default true.")]]
    soma: NotRequired[Annotated[SomaShape, Field(doc="0 <= min_um < max_um <= 200.")]]


class PairEnd(TypedDict):
    end: Annotated[str, Field(enum=("first", "last"))]
    a: list[float]
    b: list[float] | None
    body: int | None
    gap_um: float | None


class Pair(TypedDict):
    id: Any
    end: Annotated[str, Field(enum=("first", "last"), doc="The end at the soma.")]
    by: Annotated[str, Field(enum=("width", "soma", "default"))]
    widths: Annotated[list[float | None], Field(doc="[first, last] in um.")]
    a: list[float]
    b: list[float] | None
    body: Annotated[int | None, Field(doc="Index into bodies.")]
    soma: Annotated[int | None, Field(doc="The same as body.")]
    gap_um: float | None
    angle_deg: float | None
    confident: bool
    other: Annotated[PairEnd, Field(doc="The same from the other end.")]


class SomaBody(TypedDict):
    cx: float
    cy: float
    a: float
    b: float
    angle_deg: float
    z: NotRequired[Annotated[float, Field(doc="A Z-stack's: the soma's depth, in slice numbers.")]]
    ais: Annotated[Any, Field(doc="The id of the AIS it faces, or null.")]


class PairReply(TypedDict):
    pairs: list[Pair]
    bodies: list[SomaBody]


doc(
    ais.pair,
    summary="Guess each AIS's soma end and soma, and the soma ellipses",
    tag="AIS",
    description=("Body {pixel_um, traces: [{id, pixels}], split?, soma?: {min_um, max_um, roundness}}: for each "
                 "accepted AIS on the image, the Measure tool's guess (app/analysis/pairing.py): which end starts at "
                 "the soma (the thicker), the soma in front of it, and B on that soma's ellipse (the largest inside "
                 "it the soma size and roundness allow); and the image's soma ellipses (split, the default: one per "
                 "hotspot, else one per outline). {pairs: [{id, end, by, widths, a, b, body, gap_um, angle_deg, "
                 "confident, other}], bodies: [{cx, cy, a, b, angle_deg, ais}]}."),
    mcp_http="A first guess for the Measure tool on the Process screen; it stores nothing.",
    params=ShaParams,
    body=PairBody,
    reply=PairReply,
    errors=(400, 401, 403, 404),
)

doc(
    ais.file_bytes,
    summary="The stored file itself (a .czi or TIFF as it was added), for exports",
    tag="AIS",
    description="The stored file itself (a .czi or TIFF as it was added), for exports.",
    mcp_http=FILE_MCP,
    params=ShaParams,
    reply_type="application/octet-stream",
    reply_description="Success: image/tiff for a TIFF, else application/octet-stream.",
    errors=(401, 404),
)

doc(
    ais.processed_tif,
    summary="A .czi's processed AIS channel as a TIFF (what tracing uses), for exports",
    tag="AIS",
    description="A .czi's processed AIS channel as a TIFF (what tracing uses), for exports.",
    mcp_http=FILE_MCP,
    params=ShaParams,
    reply_type="image/tiff",
    errors=(401, 404),
)

doc(
    ais.channel_tif,
    summary="One .czi channel, its data as a 16-bit TIFF, for exports",
    tag="AIS",
    description="One .czi channel, its data as a 16-bit TIFF, for exports.",
    mcp_http=FILE_MCP,
    params=ShaIndexParams,
    reply_type="image/tiff",
    errors=(401, 404),
)


# --- tracing --------------------------------------------------------------------


class TraceBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    processed: Annotated[str, Field(doc="The traced image's sha.")]
    raw: NotRequired[Annotated[str | None, Field(doc="The raw image's sha, for a TIFF pair.")]]
    click: Annotated[list[float], Field(doc="[x, y].")]
    click2: NotRequired[Annotated[list[float] | None, Field(doc="[x, y].")]]
    threshold: NotRequired[Annotated[float, Field(minimum=0, maximum=1, doc="Default 0.01; 0 is Otsu.")]]
    settings: NotRequired[Annotated[dict[str, Any], Field(doc="The method's settings; missing ones are the original's.")]]
    engine: NotRequired[Annotated[str | None, Field(enum=("fast",))]]
    z_method: NotRequired[Annotated[str, Field(doc="On a Z-stack: how its 3D length is measured.")]]


doc(
    ais.trace,
    summary="Trace an AIS from a click (ais_auto.m)",
    tag="AIS",
    description=("Body: {processed, raw?, click: [x, y], click2?: [x, y], threshold?, settings?: {smooth, kernel, "
                 "sigma, ...}, engine?: \"fast\"}. Clicks are MATLAB axes coordinates (x = column, y = row, pixel "
                 "centres at 1..n). click2 stands in for the second ginput after re-thresholding; by default the "
                 "first click is used again. threshold defaults to 0.01, what the original was called with (0 means "
                 "Otsu, as in the original). engine \"fast\" is Settings' Method \"ais_auto.m (fast)\": the same "
                 "answer, sooner."),
    body=TraceBody,
    reply=dict[str, Any],
    reply_description="ais_auto.m's answer: ok, pixels, measures, shape, notes, and z on a Z-stack.",
    errors=(400, 401, 403),
)


class DetectBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    processed: Annotated[str, Field(doc="The traced image's sha.")]
    raw: NotRequired[Annotated[str | None, Field(doc="The raw image's sha, for a TIFF pair.")]]
    threshold: NotRequired[Annotated[float, Field(minimum=0, maximum=1, doc="Default 0.01; 0 is Otsu.")]]
    settings: NotRequired[Annotated[dict[str, Any], Field(doc="The method's settings; missing ones are the original's.")]]
    start: NotRequired[Annotated[str, Field(enum=("both", "brighter", "dimmer", "soma", "fitted", "fitted2", "learned"))]]
    exclude: NotRequired[Annotated[list[list[list[int]]] | None, Field(doc="The traces already accepted, each [[x, y], ...].")]]
    engine: NotRequired[Annotated[str | None, Field(enum=("fast",))]]
    z_method: NotRequired[Annotated[str, Field(doc="On a Z-stack: how its 3D length is measured.")]]


class DetectReply(TypedDict):
    candidates: Annotated[list[dict[str, Any]], Field(doc="Each a trace's answer, plus seed, filter and soma_gap_um.")]
    components: int
    merged: int
    known: int
    failed: int
    somata: NotRequired[Annotated[list[list[list[int]]], Field(doc="The soma outlines, when it found any.")]]


doc(
    ais.detect,
    summary="Find every AIS on an image (auto mode)",
    tag="AIS",
    description=("Auto mode. Body: {processed, raw?, threshold?, settings?, start?, exclude?: [[[x, y], ...], ...], "
                 "engine?: \"fast\"}. Every AIS found on the image without a click (app/analysis/detect.py); start is "
                 "both | brighter | dimmer | soma (a .czi only) | fitted | fitted2 | learned, exclude the traces "
                 "already accepted on it."),
    body=DetectBody,
    reply=DetectReply,
    errors=(400, 401, 403),
)


# --- batches --------------------------------------------------------------------


class BatchListReply(TypedDict):
    batches: list[BatchRow]
    folders: list[Folder]


doc(
    ais.batch_list,
    summary="Every batch with its progress",
    tag="AIS",
    description=("Every batch with its progress: uploads, completion, per assignee, and any auto run going on (the "
                 "Batches screen polls this as its monitor)."),
    reply=BatchListReply,
    errors=(401,),
)


class BatchCreateBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    name: str
    folder_id: NotRequired[Annotated[int | None, Field(doc="The folder to put it in; null for the top.")]]


doc(
    ais.batch_create,
    summary="Create a batch",
    tag="AIS",
    description="Body: {name}: an empty batch, its images added afterwards.",
    body=BatchCreateBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403),
)


class BatchUploadBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    name: str
    files: Annotated[list[ChosenFile], Field(doc="1 to 5000.")]
    translations: NotRequired[list[Translation]]
    randomize: NotRequired[Annotated[bool, Field(doc="Blind the names. Default true.")]]
    stack: NotRequired[Annotated[StackOptions | None, Field(doc="Group the files into Z-stacks.")]]
    channels: NotRequired[Annotated[list[ChannelChoice] | None, Field(doc="Channel roles per layout.")]]


doc(
    ais.batch_upload,
    summary="Create a batch from an uploaded folder",
    tag="AIS",
    description=("Body: {name, files: [{name, rel, sha, size}], translations?: [{dir, text}]} -- a folder picked in "
                 "the browser, hashed there. Upload the files afterwards with POST /api/ais/files."),
    body=BatchUploadBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403),
)


class BatchOrderBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    ids: list[int]


doc(
    ais.batch_order,
    summary="Set the batches' priority order",
    tag="AIS",
    description="Body: {ids}: the team's priority order, first on top (admins).",
    role=ADMIN,
    body=BatchOrderBody,
    reply=OkReply,
    errors=(400, 401, 403),
)


class BatchMoveBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    ids: list[int]
    folder_id: Annotated[int | None, Field(doc="null for the top.")]


class BatchMoveReply(TypedDict):
    moved: Annotated[int, Field(doc="How many of ids were there to move.")]


doc(
    ais.batch_move,
    summary="File batches in a folder",
    tag="AIS",
    description="Body: {ids, folder_id}: those batches into that folder, null for the top (admins).",
    role=ADMIN,
    body=BatchMoveBody,
    reply=BatchMoveReply,
    errors=(400, 401, 403),
)


class BatchImportBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    format: Annotated[str, Field(enum=("ais-batch-backup",))]
    version: Annotated[int, Field(enum=(1,))]
    users: NotRequired[Annotated[dict[str, str], Field(doc="user id -> name, in the backup.")]]
    batch: dict[str, Any]
    results: list[dict[str, Any]]
    measurements: NotRequired[list[dict[str, Any]]]


doc(
    ais.batch_import,
    summary="Import a batch backup",
    tag="AIS",
    description="Body: one batch of a backup ({format, version, users, batch, results}), which becomes a new batch.",
    role=ADMIN,
    mcp_http=BACKUP_MCP,
    body=BatchImportBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403),
)


class ImportMissingBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    shas: Annotated[list[str], Field(doc="sha-256 hex digests, at most 200000.")]


class ImportMissingReply(TypedDict):
    missing: Annotated[list[str], Field(doc="Those of shas the server does not have.")]


doc(
    ais.batch_import_missing,
    summary="Add the images a batch import was missing",
    tag="AIS",
    description=("Body: {shas}. Which of a backup's files the store does not have yet, to upload with POST "
                 "/api/ais/files before importing."),
    role=ADMIN,
    mcp_http=BACKUP_MCP,
    body=ImportMissingBody,
    reply=ImportMissingReply,
    errors=(400, 401, 403),
)

doc(
    ais.batch_backup,
    summary="What a backup ZIP holds besides the image files",
    tag="AIS",
    description="What a backup ZIP holds besides the image files. Admins only: it has the original names in it.",
    role=ADMIN,
    params=BatchParams,
    reply=dict[str, Any],
    reply_description="{format, version, users, stored, batch, results, measurements}: what POST /api/ais/batches/import takes.",
    errors=(401, 403, 404),
)

doc(
    ais.batch_get,
    summary="One batch",
    tag="AIS",
    params=BatchParams,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(401, 404),
)


class ImageStatus(TypedDict):
    key: str
    cell: str
    dir: str
    files: int
    stored: int
    ais: int
    auto: int
    done: bool
    dup_of: Annotated[str | None, Field(doc="The key of the image it duplicates.")]
    assignee: int | None
    assignee_name: str
    included: bool
    add_id: int | None
    original_key: NotRequired[Annotated[str, Field(doc="Admins, for a blinded image.")]]


class BatchStatusReply(TypedDict):
    id: int
    images: list[ImageStatus]


doc(
    ais.batch_status,
    summary="Each image's progress in a batch",
    tag="AIS",
    description="Per image: files on the server, accepted AIS, done, duplicate, assignee.",
    params=BatchParams,
    reply=BatchStatusReply,
    errors=(401, 404),
)


class BatchChannel(TypedDict):
    name: str
    color: str
    files: Annotated[int, Field(doc="How many files have it.")]


class BatchChannelsReply(TypedDict):
    channels: list[BatchChannel]
    czis: Annotated[int, Field(doc="Included .czi files.")]
    unread: Annotated[int, Field(doc="Of those, the ones not stored or not readable.")]


doc(
    ais.batch_channels,
    summary="A batch's channels",
    tag="AIS",
    params=BatchParams,
    reply=BatchChannelsReply,
    errors=(401, 404),
)


class LayoutsParams(TypedDict):
    batch_id: Annotated[int, Field(path="batch_id", minimum=1)]
    add: Annotated[int, Field(query="add", minimum=1, doc="Only this add's images.")]


class Layout(TypedDict):
    layout: Annotated[dict[str, Any], Field(doc="{kind, names}.")]
    colors: list[str] | None
    count: int
    roles: list[ChannelRole]
    results: Annotated[int, Field(doc="Images with this layout that have results.")]


class StackCalibration(TypedDict):
    count: int
    z_step_um: float
    pixel_um: float
    mixed: bool


class PixelSize(TypedDict):
    count: int
    pixel_um: Annotated[float | None, Field(doc="null: Settings', 40x by default.")]
    mixed: bool


class LayoutsReply(TypedDict):
    layouts: list[Layout]
    images: int
    unread: int
    stacks: StackCalibration | None
    pixel: PixelSize | None


doc(
    ais.batch_layouts,
    summary="A batch's channel layouts",
    tag="AIS",
    description=("?add=<id>: the channel layouts of a batch's images, or one add's: each with its channel names, "
                 "colours, how many images, the roles in use and how many already have results; stacks: its "
                 "Z-stacks' {count, z_step_um, pixel_um, mixed}, or null; pixel: its other images' {count, pixel_um "
                 "(null: Settings', 40x by default), mixed}, or null."),
    params=LayoutsParams,
    reply=LayoutsReply,
    errors=(400, 401, 404),
)


class StackCalibrationBody(TypedDict):
    z_step_um: float
    pixel_um: float


class LayoutsSetBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    add: NotRequired[Annotated[int | None, Field(doc="Only this add's images.")]]
    channels: list[ChannelChoice]
    stack: NotRequired[StackCalibrationBody | None]
    pixel_um: NotRequired[Annotated[float | None, Field(doc="null: back to the 40x default; left out: unchanged.")]]


class LayoutsSetReply(TypedDict):
    batch: Annotated[dict[str, Any], Field(doc=BATCH_DOC)]
    changed: Annotated[list[str], Field(doc="Keys of the images now traced from other channels or calibration.")]


doc(
    ais.batch_layouts_set,
    summary="Set a batch's channel roles",
    tag="AIS",
    description=("Body: {add?, channels: [{layout, roles}], stack?: {z_step_um, pixel_um}, pixel_um?: number or "
                 "null}: which channel is the AIS, soma/dendrite or other, for the images of a batch (or one add) "
                 "with those layouts, its Z-stacks' slice spacing and pixel size, and the microns per pixel its other "
                 "images are measured with (null: back to the 40x default; left out: unchanged). Answers with the "
                 "batch and the keys of the images now traced from other channels or calibration."),
    params=BatchParams,
    body=LayoutsSetBody,
    reply=LayoutsSetReply,
    errors=(400, 401, 403, 404),
)


class FillAreasBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    after: NotRequired[Annotated[int, Field(minimum=0, doc="A result id. Default 0.")]]
    limit: NotRequired[Annotated[int, Field(minimum=1, maximum=50, doc="Default 10.")]]
    with_soma: NotRequired[Annotated[bool, Field(doc="Only AIS whose soma distance has been measured.")]]


class FillAreasReply(TypedDict):
    filled: int
    failed: Annotated[list[int], Field(doc="Result ids not filled in.")]
    after: Annotated[int, Field(doc="Give it back as after.")]
    remaining: int


doc(
    ais.batch_fill_areas,
    summary="Fill in missing AIS areas",
    tag="AIS",
    description=("Body: {after?: result id, limit?: 1-50 (default 10), with_soma?: only AIS whose soma distance has "
                 "been measured}: fill in the area (and on a Z-stack the volume) of the batch's accepted AIS that "
                 "have none, tracing each again from its saved clicks, threshold and settings; only an AIS that comes "
                 "out on the same pixels is filled in, and nothing else about it changes. A few at a time: call again "
                 "with after until remaining is 0. {filled, failed: [result ids], after, remaining}."),
    params=BatchParams,
    body=FillAreasBody,
    reply=FillAreasReply,
    errors=(400, 401, 403, 404),
)


class BatchAddBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    files: Annotated[list[ChosenFile], Field(doc="1 to 5000.")]
    randomize: NotRequired[Annotated[bool, Field(doc="Blind the names. Default true.")]]
    add_name: NotRequired[str]
    translations: NotRequired[list[Translation]]
    stack: NotRequired[Annotated[StackOptions | None, Field(doc="Group the files into Z-stacks.")]]
    channels: NotRequired[Annotated[list[ChannelChoice] | None, Field(doc="Channel roles per layout.")]]


doc(
    ais.batch_add,
    summary="Add images to a batch",
    tag="AIS",
    description=("Body: {files: [{name, rel, sha, size, modified?}], randomize?, add_name?, translations?: [{dir, "
                 "text}]}: more files picked in the browser for an existing batch, named by any __Translation.txt "
                 "picked with them, blinded unless randomize is false. Upload them afterwards as for a new one."),
    params=BatchParams,
    body=BatchAddBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)


class BatchRenameBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    name: str


doc(
    ais.batch_rename,
    summary="Rename a batch",
    tag="AIS",
    description="Body: {name}. Its accepted AIS carry the new name too.",
    params=BatchParams,
    body=BatchRenameBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)


class BatchArchiveBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    archived: bool


doc(
    ais.batch_archive,
    summary="Archive or unarchive a batch",
    tag="AIS",
    description="Body: {archived}: archive the batch (hidden, results kept) or bring it back.",
    params=BatchParams,
    body=BatchArchiveBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)


class BatchActivityBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    kind: Annotated[str, Field(enum=("auto",))]
    state: Annotated[str, Field(enum=("running", "paused", "finished", "stopped"))]
    done: Annotated[int, Field(minimum=0)]
    total: Annotated[int, Field(minimum=0, maximum=5000)]


doc(
    ais.batch_activity,
    summary="Report an auto run on a batch",
    tag="AIS",
    description=("Body: {kind: \"auto\", state, done, total}: how far this person's auto run on the batch has got, "
                 "so everyone's Batches screen can show it."),
    mcp_http="The Process screen reporting that someone is working on a batch, not an action.",
    params=BatchParams,
    body=BatchActivityBody,
    reply=Activity,
    errors=(400, 401, 403, 404),
)


class BatchDoneBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    image: Annotated[str, Field(doc="The image's key.")]
    done: bool


class BatchDoneReply(TypedDict):
    skipped: Annotated[list[str], Field(doc="The keys of every image now marked done.")]


doc(
    ais.batch_done,
    summary="Mark an image done or not done",
    tag="AIS",
    description="Body: {image, done}: mark an image done by hand (shared progress).",
    params=BatchParams,
    body=BatchDoneBody,
    reply=BatchDoneReply,
    errors=(400, 401, 403, 404),
)


class BatchIncludeBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    keys: list[str]
    included: bool


doc(
    ais.batch_include,
    summary="Include or exclude an image",
    tag="AIS",
    description="Body: {keys, included}: include these images, or leave them out, for the whole team.",
    params=BatchParams,
    body=BatchIncludeBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)

doc(
    ais.batch_delete,
    summary="Delete a batch",
    tag="AIS",
    mcp_http="Deleting a whole batch is kept out of agents' reach on purpose.",
    params=BatchParams,
    body=CsrfBody,
    reply=OkTrashReply,
    errors=(400, 401, 403, 404),
)


class Share(TypedDict):
    user_id: int
    percent: Annotated[float, Field(doc="Above 0; the shares are scaled to sum 100.")]


class BatchAssignBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    shares: list[Share]


doc(
    ais.batch_assign,
    summary="Split a batch among people",
    tag="AIS",
    description=("Body: {shares: [{user_id, percent}]}: split the batch among these people (admins). An empty list "
                 "clears the assignment."),
    role=ADMIN,
    params=BatchParams,
    body=BatchAssignBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)


class BatchResetBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    scope: Annotated[str, Field(enum=("all", "auto"))]


class BatchResetReply(TypedDict):
    batch: Annotated[dict[str, Any], Field(doc=BATCH_DOC)]
    deleted: Annotated[int, Field(doc="AIS deleted.")]
    trash_id: Annotated[int | None, Field(doc="null when nothing went.")]


doc(
    ais.batch_reset,
    summary="Reset a batch's results",
    tag="AIS",
    description=("Body: {scope: all | auto}: delete the batch's results (admins), to run it again. The Batches screen "
                 "offers a backup export first."),
    role=ADMIN,
    params=BatchParams,
    body=BatchResetBody,
    reply=BatchResetReply,
    errors=(400, 401, 403, 404),
)

doc(
    ais.batch_translation,
    summary="The batch's __Translation.txt (admins)",
    tag="AIS",
    description="The batch's __Translation.txt (admins): original/random per file.",
    role=ADMIN,
    params=BatchParams,
    reply_type="text/plain",
    errors=(401, 403, 404),
)


class CompareBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    batch_ids: list[int]
    labels: NotRequired[Any]
    tests: NotRequired[Annotated[list[str] | None, Field(doc="The stats rows; every one when left out.")]]
    units: NotRequired[Annotated[list[str] | None, Field(doc="The stats rows; every one when left out.")]]
    design: NotRequired[Annotated[Any, Field(doc="The two-way ANOVA's factors.")]]
    sheets: NotRequired[Annotated[bool, Field(doc="Add comparison.xlsx's sheets. Default false.")]]
    plots: NotRequired[Annotated[bool, Field(doc="With sheets: keep the SVG plots. Default true.")]]


doc(
    ais.compare_batches,
    summary="Compare treatments across batches",
    tag="AIS",
    description=("Body: {batch_ids, labels?, tests?, units?, design?, sheets?, plots?}: the batches' measurements "
                 "grouped by treatment, and with two or more, tested and plotted (admins: it has the original names "
                 "and treatments). sheets: true adds comparison.xlsx's sheets as JSON ({columns, rows} each) and then "
                 "keeps the SVG plots only with plots: true. See app/analysis/compare.py and report.py."),
    role=ADMIN,
    body=CompareBody,
    reply=dict[str, Any],
    reply_description="{measures, treatments, images, values, groups, pooled, stats, dropped, plots}, and sheets with sheets: true.",
    errors=(400, 401, 403),
)

doc(
    ais.batch_treatments,
    summary="Each image's original name, saved treatment and guessed one (admins)",
    tag="AIS",
    description="Each image's original name, saved treatment and guessed one (admins).",
    role=ADMIN,
    params=BatchParams,
    reply=TreatmentsReply,
    errors=(401, 403, 404),
)


class TreatmentsSetBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    treatments: Annotated[dict[str, str], Field(doc="Image key -> treatment; \"\" takes one off.")]


doc(
    ais.batch_treatments_set,
    summary="Save a batch's treatments",
    tag="AIS",
    description="Body: {treatments: {key: name}} (admins); \"\" takes one off.",
    role=ADMIN,
    params=BatchParams,
    body=TreatmentsSetBody,
    reply=TreatmentsReply,
    errors=(400, 401, 403, 404),
)


class TranslationLoadBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    text: Annotated[str, Field(doc="A __Translation.txt's contents.")]


doc(
    ais.batch_translation_load,
    summary="Load a batch's translation file",
    tag="AIS",
    description=("Body: {text}: a __Translation.txt for a batch blinded somewhere else (admins): the original names "
                 "of the files it names."),
    role=ADMIN,
    params=BatchParams,
    body=TranslationLoadBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC + " Plus named and unnamed: how many images it named, and how many are still without.",
    errors=(400, 401, 403, 404),
)


class RerandomizeParams(TypedDict):
    batch_id: Annotated[int, Field(path="batch_id", minimum=1)]
    add_id: Annotated[str, Field(path="add_id", doc="An add's id, or earlier for the images from before adds were recorded.")]


doc(
    ais.batch_rerandomize,
    summary="Re-randomize one folder's names",
    tag="AIS",
    description=("New random names for one folder of the batch (admins); its results, done marks, exclusions and "
                 "assignment move with them."),
    role=ADMIN,
    params=RerandomizeParams,
    body=CsrfBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC + " Plus renamed and measured: images renamed, and AIS that moved with them.",
    errors=(400, 401, 403, 404),
)


class AutoStartBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    general: NotRequired[Annotated[dict[str, Any] | None, Field(doc="Settings' general fields (auto_method, fitted_min_length, ...).")]]
    settings: NotRequired[Annotated[dict[str, Any] | None, Field(doc="The method's (pixconv, smooth, ...).")]]
    threshold: NotRequired[Annotated[float | None, Field(minimum=0, maximum=1)]]
    engine: NotRequired[Annotated[str | None, Field(enum=("fast",))]]
    skip_done: NotRequired[Annotated[bool | None, Field(doc="Leave out images with an AIS or a done mark. Default: general's auto_skip_done.")]]
    mark_done: NotRequired[Annotated[bool, Field(doc="Default false.")]]
    images: NotRequired[Annotated[list[str] | None, Field(doc="Only these image keys.")]]


class AutoRunChoices(TypedDict):
    general: dict[str, Any]
    settings: dict[str, Any]
    threshold: float
    engine: str | None


class AutoRunError(TypedDict):
    image: str | None
    error: str


class AutoStartReply(TypedDict):
    id: str
    batch_id: int
    user_id: int
    state: Annotated[str, Field(enum=("queued", "running", "finished", "stopped", "failed"))]
    created_at: str
    started_at: str | None
    finished_at: str | None
    done: int
    total: int
    found: int
    hidden: int
    saved: int
    marked_done: int
    errors: list[AutoRunError]
    current: Annotated[str | None, Field(doc="The image being worked on.")]
    skip_done: bool
    mark_done: bool
    choices: AutoRunChoices
    images: Annotated[list[str], Field(doc="The image keys it goes through, in order.")]


doc(
    ais.auto_start,
    summary="Start an auto run",
    tag="AIS",
    description=("Body: {general?, settings?, threshold?, engine?, skip_done?, mark_done?, images?}: auto mode over "
                 "the batch's included images, run by the server, each AIS the filters keep saved as the browser's "
                 "review \"all\" saves it. Answers at once with the run (409 while one is going on the batch). See "
                 "app/analysis/auto_runner.py."),
    params=BatchParams,
    body=AutoStartBody,
    reply=AutoStartReply,
    errors=(400, 401, 403, 404, 409),
)


class LocalPathBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    path: Annotated[str, Field(doc="A folder on this machine.")]
    randomize: NotRequired[Annotated[bool, Field(doc="Blind the names. Default true.")]]
    stack: NotRequired[Annotated[StackOptions | None, Field(doc="Group the files into Z-stacks.")]]
    channels: NotRequired[Annotated[list[ChannelChoice] | None, Field(doc="Channel roles per layout.")]]


doc(
    ais.batch_path,
    summary="Create a batch from a folder on this computer",
    tag="AIS",
    description="Body: {path}: an Open-path batch, hashed and recorded by the server.",
    access=SESSION_ONLY,
    role=ADMIN,
    body=LocalPathBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403),
)

doc(
    ais.batch_add_path,
    summary="Add a folder on this computer to a batch",
    tag="AIS",
    description="Body: {path}: a folder on this machine added to an existing batch.",
    access=SESSION_ONLY,
    role=ADMIN,
    params=BatchParams,
    body=LocalPathBody,
    reply=dict[str, Any],
    reply_description=BATCH_DOC,
    errors=(400, 401, 403, 404),
)


# --- folders --------------------------------------------------------------------


class FolderListReply(TypedDict):
    folders: list[Folder]


doc(
    ais.folder_list,
    summary="The Batches screen's folders",
    tag="AIS",
    description="Every folder: id, name, parent_id (null at the top), position.",
    reply=FolderListReply,
    errors=(401,),
)


class FolderCreateBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    name: str
    parent_id: Annotated[int | None, Field(doc="null: the top.")]


doc(
    ais.folder_create,
    summary="Create a folder",
    tag="AIS",
    description="Body: {name, parent_id}: a new folder, first in its parent (null: the top) (admins).",
    role=ADMIN,
    body=FolderCreateBody,
    reply=Folder,
    errors=(400, 401, 403),
)


class FolderOrderBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    parent_id: Annotated[int | None, Field(doc="null: the top.")]
    ids: list[int]


doc(
    ais.folder_order,
    summary="Set the order of one folder's folders",
    tag="AIS",
    description="Body: {parent_id, ids} (admins).",
    role=ADMIN,
    body=FolderOrderBody,
    reply=OkReply,
    errors=(400, 401, 403),
)


class FolderRenameBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    name: str


doc(
    ais.folder_rename,
    summary="Rename a folder",
    tag="AIS",
    description="Body: {name} (admins).",
    role=ADMIN,
    params=FolderParams,
    body=FolderRenameBody,
    reply=Folder,
    errors=(400, 401, 403, 404),
)


class FolderMoveBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc=CSRF_DOC)]]
    parent_id: Annotated[int | None, Field(doc="null: the top.")]


doc(
    ais.folder_move,
    summary="Move a folder into another",
    tag="AIS",
    description="Body: {parent_id}: null for the top; not into itself or anything inside it (admins).",
    role=ADMIN,
    params=FolderParams,
    body=FolderMoveBody,
    reply=Folder,
    errors=(400, 401, 403, 404),
)

doc(
    ais.folder_delete,
    summary="Delete a folder",
    tag="AIS",
    description="What was in it, folders and batches, moves up to its parent (admins).",
    role=ADMIN,
    mcp_http="Deleting a folder is kept out of agents' reach on purpose.",
    params=FolderParams,
    body=CsrfBody,
    reply=OkTrashReply,
    errors=(400, 401, 403, 404),
)


# --- trash ----------------------------------------------------------------------


class TrashListReply(TypedDict):
    entries: Annotated[list[TrashEntry], Field(doc="Newest first.")]
    days: Annotated[int, Field(doc="How long an entry is kept.")]


doc(
    ais.trash_list,
    summary="The Batches screen's trash",
    tag="AIS",
    description=("What deleting a batch or folder, or resetting a batch, took away in the last 30 days, newest "
                 "first: {entries: [{id, kind (batch | folder | reset), name, deleted_at, deleted_by, "
                 "deleted_by_name, expires_at, can_restore, counts}], days}."),
    mcp_http=TRASH_MCP,
    reply=TrashListReply,
    errors=(401,),
)

doc(
    ais.trash_restore,
    summary="Restore from the trash",
    tag="AIS",
    description=("Put a deleted batch (with its AIS and lines), folder or reset back. A batch: whoever deleted it or "
                 "an admin; a folder or reset: admins."),
    mcp_http=TRASH_MCP,
    params=TrashParams,
    body=CsrfBody,
    reply=TrashSummary,
    errors=(400, 401, 403, 404),
)

doc(
    ais.trash_purge,
    summary="Delete from the trash for good",
    tag="AIS",
    description="The entry gone for good (admins).",
    role=ADMIN,
    mcp_http="Deleting for good is kept out of agents' reach on purpose.",
    params=TrashParams,
    body=CsrfBody,
    reply=OkReply,
    errors=(400, 401, 403, 404),
)
