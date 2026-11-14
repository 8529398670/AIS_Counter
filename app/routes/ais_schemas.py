"""The request and reply types of the AIS routes (app/routes/ais.py and
ais_matlab.py): config/openapi.json, config/api.md and the checks on every
request come from these and the @route(...) beside each handler. Written once
from the old ais_api.py, ais_results_api.py and ais_matlab_api.py docs."""
from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

import msgspec
from msgspec import UNSET, Meta, UnsetType

from app.apidocs import PATH, QUERY, Reply
from app.apidocs import Request as RequestType
from app.routes.helpers import DateTime



class UploadReply(Reply, kw_only=True):
    sha256: str
    width: int
    height: int
    dtype: Annotated[str, Meta(description="The pixels' numpy type, uint16 say.")]
    czi: bool


class ViewRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class ThumbRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class ChannelsRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class FileChannel(Reply, kw_only=True):
    index: int
    name: str
    color: Annotated[str, Meta(description='#rrggbb.')]


class ChannelsReply(Reply, kw_only=True):
    channels: list[FileChannel]


class ChannelRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]
    index: Annotated[int, PATH, Meta(description='0-based.', ge=0)]


class SliceViewRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]
    index: Annotated[int, PATH, Meta(description='0-based.', ge=0)]


class CompositeRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class SomataRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class SomataReply(Reply, kw_only=True):
    somata: Annotated[list[list[list[int]]], Meta(description='Per soma, its edge pixels as 1-based [x, y].')]


class PairTraceIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    id: Annotated[Any, Meta(description='Yours, given back with its pair.')]
    pixels: Annotated[list[list[int]], Meta(description='1-based [x, y] whole numbers.')]


class SomaShapeIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    min_um: float | UnsetType = UNSET
    max_um: float | UnsetType = UNSET
    roundness: Annotated[float, Meta(ge=0, le=1)] | UnsetType = UNSET


class PairRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]
    pixel_um: Annotated[float, Meta(description='Microns per pixel, above 0.')]
    traces: Annotated[list[PairTraceIn], Meta(description='At most 500.')]
    split: Annotated[bool, Meta(description='One soma per hotspot. Default true.')] | UnsetType = UNSET
    soma: Annotated[SomaShapeIn, Meta(description='0 <= min_um < max_um <= 200.')] | UnsetType = UNSET


class PairEnd(Reply, kw_only=True):
    end: Literal['first', 'last']
    a: list[float]
    b: list[float] | None
    body: int | None
    gap_um: float | None


class Pair(Reply, kw_only=True):
    id: Any
    end: Annotated[Literal['first', 'last'], Meta(description='The end at the soma.')]
    by: Literal['width', 'soma', 'default']
    widths: Annotated[list[float | None], Meta(description='[first, last] in um.')]
    a: list[float]
    b: list[float] | None
    body: Annotated[int, Meta(description='Index into bodies.')] | None
    soma: Annotated[int, Meta(description='The same as body.')] | None
    gap_um: float | None
    angle_deg: float | None
    confident: bool
    other: Annotated[PairEnd, Meta(description='The same from the other end.')]


class SomaBody(Reply, kw_only=True):
    cx: float
    cy: float
    a: float
    b: float
    angle_deg: float
    z: Annotated[float, Meta(description="A Z-stack's: the soma's depth, in slice numbers.")] | UnsetType = UNSET
    ais: Annotated[Any, Meta(description='The id of the AIS it faces, or null.')]


class PairReply(Reply, kw_only=True):
    pairs: list[Pair]
    bodies: list[SomaBody]


class FileBytesRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class ProcessedTifRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]


class ChannelTifRequest(RequestType, kw_only=True):
    sha: Annotated[str, PATH, Meta(description="The file's sha-256, as POST /api/ais/files answered.")]
    index: Annotated[int, PATH, Meta(description='0-based.', ge=0)]


class TraceRequest(RequestType, kw_only=True):
    processed: Annotated[str, Meta(description="The traced image's sha.")]
    raw: Annotated[str, Meta(description="The raw image's sha, for a TIFF pair.")] | None | UnsetType = UNSET
    click: Annotated[list[float], Meta(description='[x, y].')]
    click2: Annotated[list[float], Meta(description='[x, y].')] | None | UnsetType = UNSET
    threshold: Annotated[float, Meta(description='Default 0.01; 0 is Otsu.', ge=0, le=1)] | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method's settings; missing ones are the original's.")] | UnsetType = UNSET
    engine: Literal['fast'] | UnsetType = UNSET
    z_method: Annotated[str, Meta(description='On a Z-stack: how its 3D length is measured.')] | UnsetType = UNSET


class DetectRequest(RequestType, kw_only=True):
    processed: Annotated[str, Meta(description="The traced image's sha.")]
    raw: Annotated[str, Meta(description="The raw image's sha, for a TIFF pair.")] | None | UnsetType = UNSET
    threshold: Annotated[float, Meta(description='Default 0.01; 0 is Otsu.', ge=0, le=1)] | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method's settings; missing ones are the original's.")] | UnsetType = UNSET
    start: Literal['both', 'brighter', 'dimmer', 'soma', 'fitted', 'fitted2', 'learned'] | UnsetType = UNSET
    exclude: Annotated[list[list[list[int]]], Meta(description='The traces already accepted, each [[x, y], ...].')] | None | UnsetType = UNSET
    engine: Literal['fast'] | UnsetType = UNSET
    z_method: Annotated[str, Meta(description='On a Z-stack: how its 3D length is measured.')] | UnsetType = UNSET


class DetectReply(Reply, kw_only=True):
    candidates: Annotated[list[dict[str, Any]], Meta(description="Each a trace's answer, plus seed, filter and soma_gap_um.")]
    components: int
    merged: int
    known: int
    failed: int
    somata: Annotated[list[list[list[int]]], Meta(description='The soma outlines, when it found any.')] | UnsetType = UNSET


class Assignee(Reply, kw_only=True):
    user_id: int
    name: str
    percent: float
    images: int
    completed: int
    ais: int
    last_at: Annotated[str, Meta(description='When an AIS on their images was last accepted or edited.')] | None


class LiveActivity(Reply, kw_only=True):
    user_id: int
    kind: Literal['auto']
    state: Literal['running', 'paused', 'finished', 'stopped']
    done: int
    total: int
    at: str
    name: str


class BatchRow(Reply, kw_only=True):
    id: int
    name: str
    source: Literal['upload', 'path']
    path: Annotated[str, Meta(description="An Open-path batch's folder.")] | None
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
    adds: Annotated[list[dict[str, Any]], Meta(description='Each time images were added, with added_by_name.')]
    earlier: Annotated[int, Meta(description='Images from before adds were recorded.')]
    randomized: bool
    unnamed: int
    duplicates: int
    ais: int
    auto: int
    files: int
    stored: Annotated[int, Meta(description='Of files, how many the server can show.')]
    assignees: list[Assignee]
    mine: Annotated[Assignee, Meta(description='Your own share, if you have one.')] | None
    activity: Annotated[list[LiveActivity], Meta(description="Auto runs going on in people's browsers.")]
    treatments: Annotated[list[list[Any]], Meta(description='Admins: [[name, images], ...], most images first.')] | UnsetType = UNSET
    untreated: Annotated[int, Meta(description='Admins: included images with no treatment.')] | UnsetType = UNSET


class Folder(Reply, kw_only=True):
    id: int
    name: str
    parent_id: Annotated[int, Meta(description='null at the top.')] | None
    position: int
    created_by: int
    created_at: str
    updated_at: str


class BatchListReply(Reply, kw_only=True):
    batches: list[BatchRow]
    folders: list[Folder]


class BatchCreateRequest(RequestType, kw_only=True):
    name: str
    folder_id: Annotated[int, Meta(description='The folder to put it in; null for the top.')] | None | UnsetType = UNSET


class CziStackHeaderIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    slices: Annotated[int, Meta(description='Its Z planes.', ge=2)]
    phases: Annotated[int, Meta(description='Its ApoTome grid phases; 1 (the default) without.', ge=1)] | UnsetType = UNSET
    z_step_um: Annotated[float, Meta(description="Its Z scaling; null without, when stack's is used.")] | None
    pixel_um: Annotated[float, Meta(description="Its X scaling; null without, when stack's is used.")] | None


class ChosenFileIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    name: str
    rel: Annotated[str, Meta(description='Its path under the folder picked. Default name.')] | UnsetType = UNSET
    sha: Annotated[str, Meta(description='sha-256, hex.')]
    size: int | UnsetType = UNSET
    layout: Annotated[dict[str, Any], Meta(description='Its channels as the browser read them.')] | UnsetType = UNSET
    zstack: Annotated[CziStackHeaderIn, Meta(description='A .czi with more than one slice: what it says of itself.')] | UnsetType = UNSET
    modified: Annotated[str, Meta(description='When it was last changed, ISO.')] | UnsetType = UNSET


class TranslationIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    dir: str
    text: Annotated[str, Meta(description="A __Translation.txt's contents.")]


class StackOptionsIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    plane: Annotated[int, Meta(description='The channel of each slice that is the AIS.', ge=0, le=3)]
    z_step_um: float
    pixel_um: float


class CziStackChoiceIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    apotome: Annotated[Literal['sectioned', 'widefield'], Meta(description='How ApoTome phases become slices. Default sectioned.')] | UnsetType = UNSET


class ChannelRoleIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    role: Literal['ais', 'soma', 'other']
    label: Annotated[str, Meta(description="The channel's name; empty unless role is other.")]


class ChannelChoiceIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    layout: Annotated[dict[str, Any], Meta(description='{kind, names}: a layout as GET .../layouts gives it.')]
    roles: Annotated[list[ChannelRoleIn], Meta(description='One per channel: exactly one ais, at most one soma.')]


class BatchUploadRequest(RequestType, kw_only=True):
    name: str
    files: Annotated[list[ChosenFileIn], Meta(description='1 to 5000.')]
    translations: list[TranslationIn] | UnsetType = UNSET
    randomize: Annotated[bool, Meta(description='Blind the names. Default true.')] | UnsetType = UNSET
    stack: Annotated[StackOptionsIn, Meta(description='Group TIFF slices into Z-stacks.')] | None | UnsetType = UNSET
    czi_stack: Annotated[CziStackChoiceIn, Meta(description='For files with zstack: Z-stack .czi files.')] | None | UnsetType = UNSET
    channels: Annotated[list[ChannelChoiceIn], Meta(description='Channel roles per layout.')] | None | UnsetType = UNSET


class BatchOrderRequest(RequestType, kw_only=True):
    ids: list[int]


class OkReply(Reply, kw_only=True):
    ok: bool


class BatchMoveRequest(RequestType, kw_only=True):
    ids: list[int]
    folder_id: Annotated[int, Meta(description='null for the top.')] | None


class BatchMoveReply(Reply, kw_only=True):
    moved: Annotated[int, Meta(description='How many of ids were there to move.')]


class FolderListReply(Reply, kw_only=True):
    folders: list[Folder]


class FolderCreateRequest(RequestType, kw_only=True):
    name: str
    parent_id: Annotated[int, Meta(description='null: the top.')] | None


class FolderOrderRequest(RequestType, kw_only=True):
    parent_id: Annotated[int, Meta(description='null: the top.')] | None
    ids: list[int]


class FolderRenameRequest(RequestType, kw_only=True):
    folder_id: Annotated[int, PATH, Meta(ge=1)]
    name: str


class FolderMoveRequest(RequestType, kw_only=True):
    folder_id: Annotated[int, PATH, Meta(ge=1)]
    parent_id: Annotated[int, Meta(description='null: the top.')] | None


class FolderDeleteRequest(RequestType, kw_only=True):
    folder_id: Annotated[int, PATH, Meta(ge=1)]


class OkTrashReply(Reply, kw_only=True):
    ok: bool
    trash_id: Annotated[int, Meta(description='Its entry in GET /api/ais/trash.')]


class BatchImportRequest(RequestType, kw_only=True):
    format: Literal['ais-batch-backup']
    version: Literal[1]
    users: Annotated[dict[str, str], Meta(description='user id -> name, in the backup.')] | UnsetType = UNSET
    batch: dict[str, Any]
    results: list[dict[str, Any]]
    measurements: list[dict[str, Any]] | UnsetType = UNSET


class BatchImportMissingRequest(RequestType, kw_only=True):
    shas: Annotated[list[str], Meta(description='sha-256 hex digests, at most 200000.')]


class ImportMissingReply(Reply, kw_only=True):
    missing: Annotated[list[str], Meta(description='Those of shas the server does not have.')]


class BatchBackupRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class BatchGetRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class BatchStatusRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class ImageStatus(Reply, kw_only=True):
    key: str
    cell: str
    dir: str
    files: int
    stored: int
    ais: int
    auto: int
    done: bool
    dup_of: Annotated[str, Meta(description='The key of the image it duplicates.')] | None
    assignee: int | None
    assignee_name: str
    included: bool
    add_id: int | None
    original_key: Annotated[str, Meta(description='Admins, for a blinded image.')] | UnsetType = UNSET


class BatchStatusReply(Reply, kw_only=True):
    id: int
    images: list[ImageStatus]


class BatchChannelsRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class BatchChannel(Reply, kw_only=True):
    name: str
    color: str
    files: Annotated[int, Meta(description='How many files have it.')]


class BatchChannelsReply(Reply, kw_only=True):
    channels: list[BatchChannel]
    czis: Annotated[int, Meta(description='Included .czi files.')]
    unread: Annotated[int, Meta(description='Of those, the ones not stored or not readable.')]


class BatchLayoutsRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    add: Annotated[int, QUERY, Meta(description="Only this add's images.", ge=1)] | UnsetType = UNSET


class ChannelRole(Reply, kw_only=True):
    role: Literal['ais', 'soma', 'other']
    label: Annotated[str, Meta(description="The channel's name; empty unless role is other.")]


class Layout(Reply, kw_only=True):
    layout: Annotated[dict[str, Any], Meta(description='{kind, names}.')]
    colors: list[str] | None
    count: int
    roles: list[ChannelRole]
    results: Annotated[int, Meta(description='Images with this layout that have results.')]


class StackCalibration(Reply, kw_only=True):
    count: int
    z_step_um: float
    pixel_um: float
    mixed: bool
    from_file: Annotated[int, Meta(description='How many are .czi files, calibrated from the file.')]


class PixelSize(Reply, kw_only=True):
    count: int
    pixel_um: Annotated[float, Meta(description="null: Settings', 40x by default.")] | None
    mixed: bool


class LayoutsReply(Reply, kw_only=True):
    layouts: list[Layout]
    images: int
    unread: int
    stacks: StackCalibration | None
    pixel: PixelSize | None


class StackCalibrationBodyIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    z_step_um: float
    pixel_um: float


class BatchLayoutsSetRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    add: Annotated[int, Meta(description="Only this add's images.")] | None | UnsetType = UNSET
    channels: list[ChannelChoiceIn]
    stack: StackCalibrationBodyIn | None | UnsetType = UNSET
    pixel_um: Annotated[float, Meta(description='null: back to the 40x default; left out: unchanged.')] | None | UnsetType = UNSET


class LayoutsSetReply(Reply, kw_only=True):
    batch: Annotated[dict[str, Any], Meta(description='The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.')]
    changed: Annotated[list[str], Meta(description='Keys of the images now traced from other channels or calibration.')]


class BatchFillAreasRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    after: Annotated[int, Meta(description='A result id. Default 0.', ge=0)] | UnsetType = UNSET
    limit: Annotated[int, Meta(description='Default 10.', ge=1, le=50)] | UnsetType = UNSET
    with_soma: Annotated[bool, Meta(description='Only AIS whose soma distance has been measured.')] | UnsetType = UNSET


class FillAreasReply(Reply, kw_only=True):
    filled: int
    failed: Annotated[list[int], Meta(description='Result ids not filled in.')]
    after: Annotated[int, Meta(description='Give it back as after.')]
    remaining: int


class BatchAddRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    files: Annotated[list[ChosenFileIn], Meta(description='1 to 5000.')]
    randomize: Annotated[bool, Meta(description='Blind the names. Default true.')] | UnsetType = UNSET
    add_name: str | UnsetType = UNSET
    translations: list[TranslationIn] | UnsetType = UNSET
    stack: Annotated[StackOptionsIn, Meta(description='Group TIFF slices into Z-stacks.')] | None | UnsetType = UNSET
    czi_stack: Annotated[CziStackChoiceIn, Meta(description='For files with zstack: Z-stack .czi files.')] | None | UnsetType = UNSET
    channels: Annotated[list[ChannelChoiceIn], Meta(description='Channel roles per layout.')] | None | UnsetType = UNSET


class BatchRenameRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    name: str


class BatchArchiveRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    archived: bool


class BatchActivityRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    kind: Literal['auto']
    state: Literal['running', 'paused', 'finished', 'stopped']
    done: Annotated[int, Meta(ge=0)]
    total: Annotated[int, Meta(ge=0, le=5000)]


class Activity(Reply, kw_only=True):
    user_id: int
    kind: Literal['auto']
    state: Literal['running', 'paused', 'finished', 'stopped']
    done: int
    total: int
    at: str


class BatchDoneRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    image: Annotated[str, Meta(description="The image's key.")]
    done: bool


class BatchDoneReply(Reply, kw_only=True):
    skipped: Annotated[list[str], Meta(description='The keys of every image now marked done.')]


class BatchIncludeRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    keys: list[str]
    included: bool


class BatchDeleteRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class ShareIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    user_id: int
    percent: Annotated[float, Meta(description='Above 0; the shares are scaled to sum 100.')]


class BatchAssignRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    shares: list[ShareIn]


class BatchResetRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    scope: Literal['all', 'auto']


class BatchResetReply(Reply, kw_only=True):
    batch: Annotated[dict[str, Any], Meta(description='The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.')]
    deleted: Annotated[int, Meta(description='AIS deleted.')]
    trash_id: Annotated[int, Meta(description='null when nothing went.')] | None


class TrashEntry(Reply, kw_only=True):
    id: int
    kind: Literal['batch', 'folder', 'reset']
    name: str
    deleted_at: str
    deleted_by: int | None
    expires_at: str
    folders: Annotated[int, Meta(description='A folder: the folders it held.')] | UnsetType = UNSET
    batches: Annotated[int, Meta(description='A folder: the batches it held.')] | UnsetType = UNSET
    results: Annotated[int, Meta(description='A batch or reset: the AIS.')] | UnsetType = UNSET
    measurements: Annotated[int, Meta(description='A batch or reset: the recorded lines.')] | UnsetType = UNSET
    images: Annotated[int, Meta(description='A batch.')] | UnsetType = UNSET
    batch_id: Annotated[int, Meta(description='A batch or reset.')] | UnsetType = UNSET
    scope: Annotated[Literal['all', 'auto'], Meta(description='A reset.')] | UnsetType = UNSET
    deleted_by_name: str
    can_restore: Annotated[bool, Meta(description='Whether you may put it back.')]


class TrashListReply(Reply, kw_only=True):
    entries: Annotated[list[TrashEntry], Meta(description='Newest first.')]
    days: Annotated[int, Meta(description='How long an entry is kept.')]


class TrashRestoreRequest(RequestType, kw_only=True):
    trash_id: Annotated[int, PATH, Meta(ge=1)]


class TrashSummary(Reply, kw_only=True):
    id: int
    kind: Literal['batch', 'folder', 'reset']
    name: str
    deleted_at: str
    deleted_by: int | None
    expires_at: str
    folders: Annotated[int, Meta(description='A folder: the folders it held.')] | UnsetType = UNSET
    batches: Annotated[int, Meta(description='A folder: the batches it held.')] | UnsetType = UNSET
    results: Annotated[int, Meta(description='A batch or reset: the AIS.')] | UnsetType = UNSET
    measurements: Annotated[int, Meta(description='A batch or reset: the recorded lines.')] | UnsetType = UNSET
    images: Annotated[int, Meta(description='A batch.')] | UnsetType = UNSET
    batch_id: Annotated[int, Meta(description='A batch or reset.')] | UnsetType = UNSET
    scope: Annotated[Literal['all', 'auto'], Meta(description='A reset.')] | UnsetType = UNSET


class TrashPurgeRequest(RequestType, kw_only=True):
    trash_id: Annotated[int, PATH, Meta(ge=1)]


class BatchTranslationRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class CompareBatchesRequest(RequestType, kw_only=True):
    batch_ids: list[int]
    labels: Any | UnsetType = UNSET
    tests: Annotated[list[str], Meta(description='The stats rows; every one when left out.')] | None | UnsetType = UNSET
    units: Annotated[list[str], Meta(description='The stats rows; every one when left out.')] | None | UnsetType = UNSET
    design: Annotated[Any, Meta(description="The two-way ANOVA's factors.")] | UnsetType = UNSET
    sheets: Annotated[bool, Meta(description="Add comparison.xlsx's sheets. Default false.")] | UnsetType = UNSET
    plots: Annotated[bool, Meta(description='With sheets: keep the SVG plots. Default true.')] | UnsetType = UNSET


class BatchTreatmentsRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]


class Treatment(Reply, kw_only=True):
    key: str
    original: Annotated[str, Meta(description="The image's original name.")]
    folder: str
    treatment: Annotated[str, Meta(description='Saved; empty if none.')]
    guess: str
    guess_written: str
    guess_key: str
    included: bool


class TreatmentsReply(Reply, kw_only=True):
    treatments: list[Treatment]


class BatchTreatmentsSetRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    treatments: Annotated[dict[str, str], Meta(description='Image key -> treatment; "" takes one off.')]


class BatchTranslationLoadRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    text: Annotated[str, Meta(description="A __Translation.txt's contents.")]


class BatchRerandomizeRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    add_id: Annotated[str, PATH, Meta(description="An add's id, or earlier for the images from before adds were recorded.")]


class BatchReportRequest(RequestType, kw_only=True):
    batch: Annotated[str, QUERY, Meta(description='all (default), a batch id, or ids separated by commas')] | UnsetType = UNSET
    everything: Annotated[Literal['0', '1', 'false', 'true'], QUERY, Meta(description='0 or 1: also the images left out')] | UnsetType = UNSET
    unblind: Annotated[Literal['0', '1', 'false', 'true'], QUERY, Meta(description='0 or 1 (admins): original names')] | UnsetType = UNSET
    sheets: Annotated[str, QUERY, Meta(description='sheet names separated by commas: only those')] | UnsetType = UNSET


class ReportBatch(Reply, kw_only=True):
    id: int
    name: str


class ReportSheet(Reply, kw_only=True):
    columns: list[str]
    rows: Annotated[list[dict[str, Any]], Meta(description='One object per row, keyed by column.')]


class BatchReportReply(Reply, kw_only=True):
    batches: list[ReportBatch]
    unblinded: Annotated[bool, Meta(description='Whether blinded images are under their original names.')]
    everything: bool
    sheets: Annotated[dict[str, ReportSheet], Meta(description='By name: summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment and statistics once images have treatments.')]


class AutoListRequest(RequestType, kw_only=True):
    batch: Annotated[int, QUERY, Meta(description='A batch id: only its runs.')] | UnsetType = UNSET


class AutoRunSchemaError(Reply, kw_only=True):
    image: Annotated[str, Meta(description="The image's key; null when the run failed between images.")] | None
    error: str


class AutoRunSchemaChoices(Reply, kw_only=True):
    general: Annotated[dict[str, Any], Meta(description="Settings' general fields, as GET /api/ais/auto/defaults lists them.")]
    settings: Annotated[dict[str, Any], Meta(description="The method's settings.")]
    threshold: float
    engine: Annotated[str, Meta(description='fast, or null for the original port.')] | None


class AutoRunSchema(Reply, kw_only=True):
    api_name: ClassVar[str] = 'AutoRun'
    api_doc: ClassVar[str] = 'An auto run on the server (app/analysis/auto_runner.py). Kept in memory: a restart forgets it.'
    id: str
    batch_id: int
    user_id: Annotated[int, Meta(description='Who started it.')]
    state: Literal['queued', 'running', 'finished', 'stopped', 'failed']
    created_at: DateTime
    started_at: DateTime | None
    finished_at: DateTime | None
    done: Annotated[int, Meta(description='Images worked through.')]
    total: Annotated[int, Meta(description='Images it will work through.')]
    found: Annotated[int, Meta(description='AIS that passed the filters.')]
    hidden: Annotated[int, Meta(description='AIS the filters left out.')]
    saved: Annotated[int, Meta(description='AIS saved to the batch.')]
    marked_done: int
    errors: list[AutoRunSchemaError]
    current: Annotated[str, Meta(description='The image it is on.')] | None
    skip_done: bool
    mark_done: bool
    choices: AutoRunSchemaChoices
    images: Annotated[list[str], Meta(description='The image keys it works through, in order.')]


class AutoListReply(Reply, kw_only=True):
    runs: Annotated[list[AutoRunSchema], Meta(description='Newest first.')]


class AutoDefaultsReply(Reply, kw_only=True):
    general: Annotated[dict[str, Any], Meta(description="Settings' general fields and their defaults.")]
    ranges: Annotated[dict[str, list[float]], Meta(description='The [lowest, highest] each number in general may be.')]
    methods: list[str]
    starts: list[str]
    threshold: float
    settings: Annotated[dict[str, Any], Meta(description="The method's settings and their defaults.")]
    engines: Annotated[list[Any], Meta(description='Each null (the original port) or fast (app/analysis/fast.py).')]
    z_methods: Annotated[list[str], Meta(description='The Z-stack length methods ready to use.')]


class AutoGetRequest(RequestType, kw_only=True):
    run_id: Annotated[str, PATH]


class AutoCancelRequest(RequestType, kw_only=True):
    run_id: Annotated[str, PATH]


class AutoStartRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    general: Annotated[dict[str, Any], Meta(description="Settings' general fields (auto_method, fitted_min_length, ...).")] | None | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method's (pixconv, smooth, ...).")] | None | UnsetType = UNSET
    threshold: Annotated[float, Meta(ge=0, le=1)] | None | UnsetType = UNSET
    engine: Literal['fast'] | UnsetType = UNSET
    skip_done: Annotated[bool, Meta(description="Leave out images with an AIS or a done mark. Default: general's auto_skip_done.")] | None | UnsetType = UNSET
    mark_done: Annotated[bool, Meta(description='Default false.')] | UnsetType = UNSET
    images: Annotated[list[str], Meta(description='Only these image keys.')] | None | UnsetType = UNSET


class AutoRunError(Reply, kw_only=True):
    image: str | None
    error: str


class AutoRunChoices(Reply, kw_only=True):
    general: dict[str, Any]
    settings: dict[str, Any]
    threshold: float
    engine: str | None


class AutoStartReply(Reply, kw_only=True):
    id: str
    batch_id: int
    user_id: int
    state: Literal['queued', 'running', 'finished', 'stopped', 'failed']
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
    current: Annotated[str, Meta(description='The image being worked on.')] | None
    skip_done: bool
    mark_done: bool
    choices: AutoRunChoices
    images: Annotated[list[str], Meta(description='The image keys it goes through, in order.')]


class ResultListRequest(RequestType, kw_only=True):
    batch: Annotated[str, QUERY, Meta(description="A batch id; anything else lists every batch's.")] | UnsetType = UNSET


class AISResultSchema(Reply, kw_only=True):
    api_name: ClassVar[str] = 'AISResult'
    api_doc: ClassVar[str] = "One accepted AIS (app/models/ais.py): the trace's measures, clicks and pixels, numbered n on its image. Lengths are µm; null where the trace had no value."
    id: int
    batch_id: int
    batch_name: str
    image: Annotated[str, Meta(description="The image's key in its batch.")]
    cell: str
    n: Annotated[int, Meta(description='Its number on the image, 1..k.')]
    created_by: Annotated[int, Meta(description='Who accepted it.')]
    accepted_at: DateTime
    client_id: Annotated[str, Meta(description="The browser's own id for it, when it sent one.")] | UnsetType = UNSET
    rev: Annotated[int, Meta(description='Bumped by each change; missing until the first.')] | UnsetType = UNSET
    edited_at: DateTime | UnsetType = UNSET
    edited_by: int | UnsetType = UNSET
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
    width_um: float | None | UnsetType = UNSET
    brightness: float | None | UnsetType = UNSET
    area_blob_um2: Annotated[float, Meta(description='Missing on AIS accepted before area was measured.')] | None | UnsetType = UNSET
    area_width_um2: float | None | UnsetType = UNSET
    soma_um: Annotated[float, Meta(description='Distance from its start to the soma (the Measure tool); null when cleared.')] | None | UnsetType = UNSET
    soma_px: float | None | UnsetType = UNSET
    soma_ais_x: float | None | UnsetType = UNSET
    soma_ais_y: float | None | UnsetType = UNSET
    soma_x: float | None | UnsetType = UNSET
    soma_y: float | None | UnsetType = UNSET
    soma_xy_um: float | UnsetType = UNSET
    soma_dz_um: float | UnsetType = UNSET
    soma_at: DateTime | None | UnsetType = UNSET
    soma_by: int | None | UnsetType = UNSET
    length_str: str
    source: str
    notes: str
    file: str
    sha: str
    smooth: str
    origin: Annotated[str, Meta(description='auto for one auto mode found, empty for a click.')]
    pixels: Annotated[list[list[int]], Meta(description='The trace, as [x, y] pairs.')]
    length_3d_um: float | UnsetType = UNSET
    length_xy_um: float | UnsetType = UNSET
    z_start: float | UnsetType = UNSET
    z_end: float | UnsetType = UNSET
    z_span_um: float | UnsetType = UNSET
    z_step_um: float | UnsetType = UNSET
    z_confidence: float | UnsetType = UNSET
    z_clipped: Annotated[float, Meta(description='0 or 1.')] | UnsetType = UNSET
    volume_voxel_um3: float | UnsetType = UNSET
    volume_tube_um3: float | UnsetType = UNSET
    z_ais_start: Annotated[float, Meta(description='Ends from the slices: the AIS start found on the 3D route, a profile point.')] | UnsetType = UNSET
    z_ais_end: Annotated[float, Meta(description='Ends from the slices: the AIS end found on the 3D route, a profile point.')] | UnsetType = UNSET
    z_method: str | UnsetType = UNSET
    z_path: Annotated[list[Any], Meta(description='The z of each pixel (a number), null outside the AIS. Z-stacks only.')] | UnsetType = UNSET
    auto_method: str | UnsetType = UNSET
    auto_review: str | UnsetType = UNSET
    auto_start: str | UnsetType = UNSET
    auto_min_length: float | UnsetType = UNSET
    auto_min_length_shown: float | UnsetType = UNSET
    auto_min_brightness: float | UnsetType = UNSET
    auto_min_contrast: float | UnsetType = UNSET
    auto_min_width: float | UnsetType = UNSET
    auto_max_soma_gap: float | UnsetType = UNSET
    auto_max_branchiness: float | UnsetType = UNSET
    auto_min_score: float | UnsetType = UNSET


class ResultListReply(Reply, kw_only=True):
    results: Annotated[list[AISResultSchema], Meta(description='Oldest first.')]


class ResultAddRequest(RequestType, kw_only=True):
    batch_id: int
    image: Annotated[str, Meta(description="The image's key in the batch.")]
    row: Annotated[dict[str, Any], Meta(description="The accepted trace's numbers, texts and pixels, as POST /api/ais/trace gives them.")]
    client_id: Annotated[str, Meta(description='Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the AIS already made.')] | UnsetType = UNSET


class ResultImportRequest(RequestType, kw_only=True):
    name: Annotated[str, Meta(description="The new batch's name. Default Imported from browser.")] | UnsetType = UNSET
    rows: Annotated[list[dict[str, Any]], Meta(description='1 to 5000 accepted rows, each with its image (the cell) and optionally its sha.')]


class ResultImportReply(Reply, kw_only=True):
    batch_id: Annotated[int, Meta(description='The new batch they went into.')]


class ResultDeleteRequest(RequestType, kw_only=True):
    result_id: Annotated[int, PATH]
    expect: Annotated[int, Meta(description='The rev you last saw. Answers 409, with the record as it is now, if it has moved on.', ge=0)] | UnsetType = UNSET


class RenumberedItem(Reply, kw_only=True):
    id: int
    n: int


class ResultDeleteReply(Reply, kw_only=True):
    ok: bool
    renumbered: Annotated[list[RenumberedItem], Meta(description="The image's other AIS whose number changed, with their new n.")]


class ResultUpdateRequest(RequestType, kw_only=True):
    result_id: Annotated[int, PATH]
    expect: Annotated[int, Meta(description='The rev you last saw. Answers 409, with the record as it is now, if it has moved on.', ge=0)] | UnsetType = UNSET
    row: Annotated[dict[str, Any], Meta(description="The new trace's numbers, texts and pixels, as POST /api/ais/trace gives them.")]


class SomaBodyIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    soma_um: float
    soma_px: float
    soma_ais_x: float
    soma_ais_y: float
    soma_x: float
    soma_y: float
    soma_xy_um: Annotated[float, Meta(description='Z-stacks: the distance across the image.')] | UnsetType = UNSET
    soma_dz_um: Annotated[float, Meta(description='Z-stacks: the distance in depth.')] | UnsetType = UNSET


class ResultSomaRequest(RequestType, kw_only=True):
    result_id: Annotated[int, PATH]
    expect: Annotated[int, Meta(description='The rev you last saw. Answers 409, with the record as it is now, if it has moved on.', ge=0)] | UnsetType = UNSET
    soma: Annotated[SomaBodyIn, Meta(description='Every number 0 or more; null clears it.')] | None


class MeasureTypesReply(Reply, kw_only=True):
    types: list[str]


class MeasureTypesSetRequest(RequestType, kw_only=True):
    types: Annotated[list[str], Meta(description='1 to 50 names, up to 100 characters each, in order. Repeats are dropped.')]


class MeasureTypesSetReply(Reply, kw_only=True):
    types: Annotated[list[str], Meta(description='The list as saved.')]


class MeasurementListRequest(RequestType, kw_only=True):
    batch: Annotated[str, QUERY, Meta(description="A batch id; anything else lists every batch's.")] | UnsetType = UNSET


class MeasurementSchema(Reply, kw_only=True):
    api_name: ClassVar[str] = 'Measurement'
    api_doc: ClassVar[str] = 'A line the Measure tool recorded on an image: its ends in MATLAB axes, its length, and the pixel size that length was worked out with.'
    id: int
    batch_id: int
    batch_name: str
    image: str
    n: Annotated[int, Meta(description='Its number on the image, 1..k.')]
    created_by: int
    created_at: DateTime
    client_id: str | UnsetType = UNSET
    rev: int | UnsetType = UNSET
    edited_at: DateTime | UnsetType = UNSET
    edited_by: int | UnsetType = UNSET
    a_x: float
    a_y: float
    b_x: float
    b_y: float
    length_px: float
    length_um: float
    pixconv: float
    label: str
    type: Annotated[str, Meta(description="One of the team's measurement types, or empty.")] | UnsetType = UNSET


class MeasurementListReply(Reply, kw_only=True):
    measurements: Annotated[list[MeasurementSchema], Meta(description='Oldest first.')]


class MeasurementBodyIn(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    a_x: float
    a_y: float
    b_x: float
    b_y: float
    length_px: float
    length_um: float
    pixconv: float
    label: str | UnsetType = UNSET
    type: Annotated[str, Meta(description="One of the team's measurement types, or empty.")] | UnsetType = UNSET


class MeasurementAddRequest(RequestType, kw_only=True):
    batch_id: int
    image: Annotated[str, Meta(description="The image's key in the batch.")]
    measurement: Annotated[MeasurementBodyIn, Meta(description='Every number 0 or more.')]
    client_id: Annotated[str, Meta(description='Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the line already made.')] | UnsetType = UNSET


class MeasurementUpdateRequest(RequestType, kw_only=True):
    measurement_id: Annotated[int, PATH]
    expect: Annotated[int, Meta(description='The rev you last saw. Answers 409, with the record as it is now, if it has moved on.', ge=0)] | UnsetType = UNSET
    measurement: MeasurementBodyIn


class MeasurementDeleteRequest(RequestType, kw_only=True):
    measurement_id: Annotated[int, PATH]
    expect: Annotated[int, Meta(description='The rev you last saw. Answers 409, with the record as it is now, if it has moved on.', ge=0)] | UnsetType = UNSET


class MeasurementDeleteReply(Reply, kw_only=True):
    ok: bool
    renumbered: Annotated[list[RenumberedItem], Meta(description="The image's other lines whose number changed, with their new n.")]


class LocalStatusReply(Reply, kw_only=True):
    enabled: Annotated[bool, Meta(description='Open path works for you: an admin with a browser session, on a server that allows it.')]
    platform: Annotated[Literal['mac', 'windows', 'linux'], Meta(description="The server's.")]
    matlab: Annotated[bool, Meta(description='MATLAB can open on this machine and you are sitting at it.')]
    helper_enabled: Annotated[bool, Meta(description='The MATLAB helper is switched on.')]
    helper: Annotated[bool, Meta(description='Your MATLAB helper has polled lately.')]


class BatchPathRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='A folder on this machine.')]
    randomize: Annotated[bool, Meta(description='Blind the names. Default true.')] | UnsetType = UNSET
    stack: Annotated[StackOptionsIn, Meta(description='Group TIFF slices into Z-stacks.')] | None | UnsetType = UNSET
    czi_stack: Annotated[CziStackChoiceIn, Meta(description='For files with zstack: Z-stack .czi files.')] | None | UnsetType = UNSET
    channels: Annotated[list[ChannelChoiceIn], Meta(description='Channel roles per layout.')] | None | UnsetType = UNSET


class BatchAddPathRequest(RequestType, kw_only=True):
    batch_id: Annotated[int, PATH, Meta(ge=1)]
    path: Annotated[str, Meta(description='A folder on this machine.')]
    randomize: Annotated[bool, Meta(description='Blind the names. Default true.')] | UnsetType = UNSET
    stack: Annotated[StackOptionsIn, Meta(description='Group TIFF slices into Z-stacks.')] | None | UnsetType = UNSET
    czi_stack: Annotated[CziStackChoiceIn, Meta(description='For files with zstack: Z-stack .czi files.')] | None | UnsetType = UNSET
    channels: Annotated[list[ChannelChoiceIn], Meta(description='Channel roles per layout.')] | None | UnsetType = UNSET


class LocalListRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='An absolute path on this machine.')]


class LocalListReplyFile(Reply, kw_only=True):
    name: str
    size: Annotated[int, Meta(description='Bytes.')]


class LocalListReply(Reply, kw_only=True):
    path: str
    parent: Annotated[str, Meta(description='null at the top.')] | None
    dirs: list[str]
    files: Annotated[list[LocalListReplyFile], Meta(description='Its TIFFs.')]


class LocalStacksRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='An absolute path on this machine.')]


class LocalStacksReplyStack(Reply, kw_only=True):
    cell: str
    slices: int


class LocalStacksReply(Reply, kw_only=True):
    stacks: list[LocalStacksReplyStack]


class LocalChannelsRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='An absolute path on this machine.')]


class ChannelLayout(Reply, kw_only=True):
    kind: Literal['czi', 'tiff']
    names: list[str]


class ChannelRole2(Reply, kw_only=True):
    role: Literal['ais', 'soma', 'other']
    label: str


class LocalChannelsReplyLayout(Reply, kw_only=True):
    layout: ChannelLayout
    colors: Annotated[list[str], Meta(description='#rrggbb per channel, for a .czi; null for a TIFF.')] | None
    count: Annotated[int, Meta(description='Files with this layout.')]
    roles: list[ChannelRole2]
    stacks: Annotated[int, Meta(description='How many of those files are Z-stack slices.')]


class LocalChannelsReply(Reply, kw_only=True):
    layouts: list[LocalChannelsReplyLayout]


class LocalRevealRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='An absolute path on this machine.')]


class LocalOkReply(Reply, kw_only=True):
    ok: bool


class LocalOpenRequest(RequestType, kw_only=True):
    path: Annotated[str, Meta(description='An absolute path on this machine.')]


class LocalChooseRequest(RequestType, kw_only=True):
    pass


class LocalChooseReply(Reply, kw_only=True):
    path: Annotated[str, Meta(description='null when cancelled.')] | None
    cancelled: bool


class LocalMatlabRequest(RequestType, kw_only=True):
    mode: Annotated[Literal['open', 'run', 'replay'], Meta(description='Default run.')] | UnsetType = UNSET
    processed: Annotated[str, Meta(description="The traced image's file id (its sha-256).")]
    raw: Annotated[str, Meta(description="The profile image's file id, when the cell has both.")] | None | UnsetType = UNSET
    cell: Annotated[str, Meta(description="The cell's name as the browser shows it: a blinded name stays blind.")]
    threshold: Annotated[float, Meta(description='Default 0.01.', ge=0, le=1)] | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method settings (app/analysis/ais_auto.Settings); missing ones are the original's.")] | None | UnsetType = UNSET
    clicks: Annotated[list[list[float]], Meta(description='replay: one or two clicks as [x, y].')] | UnsetType = UNSET


class LocalMatlabReply(Reply, kw_only=True):
    ok: bool
    folder: Annotated[str, Meta(description='Where the image was staged for MATLAB.')]
    matlab: Annotated[str, Meta(description='The MATLAB that was started.')]


class MatlabBundleDownloadRequest(RequestType, kw_only=True):
    mode: Annotated[Literal['open', 'run', 'replay'], Meta(description='Default run.')] | UnsetType = UNSET
    processed: Annotated[str, Meta(description="The traced image's file id (its sha-256).")]
    raw: Annotated[str, Meta(description="The profile image's file id, when the cell has both.")] | None | UnsetType = UNSET
    cell: Annotated[str, Meta(description="The cell's name as the browser shows it: a blinded name stays blind.")]
    threshold: Annotated[float, Meta(description='Default 0.01.', ge=0, le=1)] | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method settings (app/analysis/ais_auto.Settings); missing ones are the original's.")] | None | UnsetType = UNSET
    clicks: Annotated[list[list[float]], Meta(description='replay: one or two clicks as [x, y].')] | UnsetType = UNSET


class SendRequest(RequestType, kw_only=True):
    mode: Annotated[Literal['open', 'run', 'replay'], Meta(description='Default run.')] | UnsetType = UNSET
    processed: Annotated[str, Meta(description="The traced image's file id (its sha-256).")]
    raw: Annotated[str, Meta(description="The profile image's file id, when the cell has both.")] | None | UnsetType = UNSET
    cell: Annotated[str, Meta(description="The cell's name as the browser shows it: a blinded name stays blind.")]
    threshold: Annotated[float, Meta(description='Default 0.01.', ge=0, le=1)] | UnsetType = UNSET
    settings: Annotated[dict[str, Any], Meta(description="The method settings (app/analysis/ais_auto.Settings); missing ones are the original's.")] | None | UnsetType = UNSET
    clicks: Annotated[list[list[float]], Meta(description='replay: one or two clicks as [x, y].')] | UnsetType = UNSET


class SendReply(Reply, kw_only=True):
    ok: bool


class MintKeyRequest(RequestType, kw_only=True):
    pass


class MintKeyReply(Reply, kw_only=True):
    credential: Annotated[str, Meta(description="The helper's key, sent as Authorization: Bearer. Shown only here: treat it like a password.")]


class DownloadRequest(RequestType, kw_only=True):
    platform: Annotated[Literal['darwin-arm64', 'darwin-x86_64', 'darwin-amd64', 'linux-x86_64', 'linux-amd64', 'linux-aarch64', 'linux-arm64', 'windows-amd64'], PATH, Meta(description="`uname -s`-`uname -m`, lowercased, or Go's name for it.")]


class NextJobReply(Reply, kw_only=True):
    id: Annotated[str, Meta(description="The job's id, for its bundle and done routes.")]
    mode: Literal['open', 'run', 'replay']
    cell: Annotated[str, Meta(description="The cell's name, safe as a file name.")]


class JobBundleRequest(RequestType, kw_only=True):
    job_id: Annotated[str, PATH]


class JobDoneRequest(RequestType, kw_only=True):
    job_id: Annotated[str, PATH]
    ok: Annotated[bool, Meta(description='Whether MATLAB started.')]
    message: Annotated[str, Meta(description='Why not, shown to the person. Cut to 500 characters.')] | UnsetType = UNSET


class JobDoneReply(Reply, kw_only=True):
    ok: bool
