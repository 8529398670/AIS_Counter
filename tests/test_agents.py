"""What agents get: auto mode and the reports done by the server, and the
AIS tools on /mcp (app/analysis/auto_params.py, auto_runner.py, report.py,
app/routes/mcp_tools_ais.py).

The ports are checked against the browser's own code: node runs the real
static/js functions on the same input, and the answers must match. Without
node those tests are skipped."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.analysis import auto_params as ap
from app.analysis import report
from app.analysis.images import tiff_bytes
from app.models import ais as batches
from app.models import api_keys, users
from tests.test_fast import scene
from tests.test_matlab_routes import Harness

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="needs node to run the browser's code")
P = ".tif - Processed method 2.5.tif"

# Runs the browser's AisAuto, Ais.rowFor and AisExport on stdin's cases.
DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const snake = (name) => name.replace(/[A-Z]/g, (m) => "_" + m.toLowerCase());
let general = {};
const ctx = { console, Math, JSON, Number, Object, Array, Map, Set, String, Promise,
  Settings: new Proxy({}, { get: (_, name) => () => general[snake(String(name))] }),
  I18n: { get: (key) => key } };
vm.createContext(ctx);
for (const file of input.files) {
  const [path, name] = file;
  vm.runInContext(fs.readFileSync(path, "utf8") + `\n;globalThis.${name} = ${name};`, ctx, { filename: path });
}
const out = input.cases.map((c) => {
  if (c.kind === "auto") {
    general = c.general;
    const params = ctx.AisAuto.filters();
    const run = { mode: c.review, params };
    const entry = { key: "k", files: c.files };
    return { params, rows: c.candidates.map((cand) => ({
      passes: ctx.AisAuto.passes(cand, params),
      row: JSON.parse(JSON.stringify(Object.assign(ctx.Ais.rowFor(entry, cand, "auto"), ctx.AisAuto.autoFields(run, entry)))),
    })) };
  }
  if (c.kind === "click") {
    return JSON.parse(JSON.stringify(ctx.Ais.rowFor({ key: "k", files: c.files }, c.result, "")));
  }
  if (c.kind === "sheets") {
    return ctx.AisExport.sheets(c.items).map((s) => ({ name: s.name, cols: s.cols, rows: s.rows }));
  }
  if (c.kind === "stats") return ctx.AisExport.stats(c.values);
});
process.stdout.write(JSON.stringify(out));
"""


def browser(cases: list[dict]) -> list:
    files = [[str(JS / "ais_export.js"), "AisExport"], [str(JS / "ais.js"), "Ais"], [str(JS / "ais_auto.js"), "AisAuto"]]
    done = subprocess.run([NODE, "-e", DRIVER], input=json.dumps({"files": files, "cases": cases}), capture_output=True,
                          text=True, check=True, timeout=120)
    return json.loads(done.stdout)


def plain(row: dict) -> dict:
    """A row without its empty values: clean_row (app/models/ais.py) stores
    null and missing alike, so JS's null-or-undefined is not compared."""
    return json.loads(json.dumps({k: v for k, v in row.items() if v is not None}))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- a server with MCP on ---------------------------------------------------------------


class Agents(Harness):
    def __init__(self, tmp_path):
        super().__init__(tmp_path, matlab_helper=False)
        self.set(mcp_enabled=True)

    def admin_key(self, who):
        return api_keys.issue_api_key(self.store, who.id, "k", users.ROLE_ADMIN, 3600)[0]

    def rest(self, method, path, key, body=None):
        path, _, query = path.partition("?")
        if query:
            # Harness.call has no query string of its own.
            original = self.app

            async def with_query(scope, receive, send):
                await original(scope | {"query_string": query.encode()} if scope["path"] == path else scope, receive, send)

            self.app = with_query
        try:
            answer = self.get(method, path, key=key, body=body)
        finally:
            if query:
                self.app = original
        try:
            return answer.status, json.loads(answer.data)
        except ValueError:
            return answer.status, answer.data

    def rpc(self, key, method, params=None):
        answer = self.get("POST", "/mcp", key=key, body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        return json.loads(answer.data)

    def tool(self, key, tool_name, **arguments):
        """(isError, structuredContent) of a tools/call."""
        out = self.rpc(key, "tools/call", {"name": tool_name, "arguments": arguments})
        assert "result" in out, out
        return out["result"]["isError"], out["result"].get("structuredContent")

    def names(self, key):
        return [t["name"] for t in self.rpc(key, "tools/list")["result"]["tools"]]


@pytest.fixture
def h(tmp_path):
    return Agents(tmp_path)


def upload(h, key, data: bytes) -> str:
    """POST the bytes to /api/ais/files as upload_instructions says."""
    sent = []

    async def go():
        import asyncio
        payload, delivered = data, False

        async def receive():
            nonlocal delivered
            if delivered:
                await asyncio.Event().wait()
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message):
            sent.append(message)

        headers = [(b"host", b"t"), (b"authorization", f"Bearer {key}".encode()),
                   (b"content-type", b"application/octet-stream"), (b"content-length", str(len(data)).encode())]
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/api/ais/files", "raw_path": b"/api/ais/files", "query_string": b"", "root_path": "",
                 "headers": headers, "client": ("127.0.0.1", 5000), "server": ("t", 80)}
        await h.app(scope, receive, send)

    import asyncio
    asyncio.run(go())
    status = next(m for m in sent if m["type"] == "http.response.start")["status"]
    body = json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))
    assert status == 200, body
    return body["sha256"]


# Classic with its filters off: the scenes' lines are thin and short.
LOOSE = {"auto_method": "classic", "auto_start": "both", "auto_min_length": 0, "auto_min_brightness": 0,
         "auto_min_width": 0, "auto_max_soma_gap": 0}


def scene_batch(h, key, n=2, randomize=False, seed=3):
    """A batch of n processed-only TIFFs made through the tools, uploaded."""
    images = [tiff_bytes(scene(s)) for s in range(seed, seed + n)]
    files = [{"name": f"c{i}{P}", "rel": f"f/c{i}{P}", "sha": hashlib.sha256(data).hexdigest(), "size": len(data)}
             for i, data in enumerate(images)]
    error, out = h.tool(key, "create_batch_from_files", name="scenes", files=files, randomize=randomize)
    assert not error, out
    assert {m["sha"] for m in out["missing"]} == {f["sha"] for f in files}
    assert out["upload"]["url"].endswith("/api/ais/files")
    for data in images:
        upload(h, key, data)
    return out["batch"]["id"], images


# --- auto mode: the port against the browser's code ----------------------------------------


GENERALS = [
    ap.DEFAULTS,
    ap.DEFAULTS | {"auto_method": "fitted2"},
    ap.DEFAULTS | {"auto_method": "learned", "learned_min_score": 10, "min_length": 2},
    ap.DEFAULTS | {"auto_method": "classic", "auto_start": "both"},
    ap.DEFAULTS | {"auto_method": "classic", "auto_start": "soma", "min_length": 9, "auto_min_brightness": 0},
]

# Hand-made candidates for the edges: null and missing values the filters read.
EDGES = [
    {"measures": {"length_um": 20}, "shape": {"brightness": None, "width_um": 3}, "soma_gap_um": None,
     "filter": {"length_um": 20, "brightness": 0.9, "contrast": 0.5, "branchiness": 1.0, "score": 0.5}},
    {"measures": {"length_um": None}, "shape": {}, "soma_gap_um": 50,
     "filter": {"length_um": None, "brightness": 0.1, "branchiness": 3}},
    {"measures": {}, "filter": {"score": None}},
    {"measures": {"length_um": 4.9}, "shape": {"brightness": 0.31, "width_um": 2.39}, "soma_gap_um": 9.99,
     "filter": {"length_um": 12.99, "brightness": 0.549, "contrast": 0.3, "branchiness": 1.021, "score": 0.25}},
]


@needs_node
def test_filters_and_saved_rows_are_the_browsers(h):
    """Real candidates (the detect route on a scene, each start) and the
    edges, through every method's filters: same params, same verdicts, same
    rows as static/js/ais_auto.js and ais.js."""
    ada = h.user()
    image = h.library.add(tiff_bytes(scene(3)))["sha256"]
    files = {"processed": {"name": "c" + P, "rel": "f/c" + P, "sha": image, "path": ""}}
    found = {}
    for start in ("both", "fitted", "fitted2", "learned"):
        status, out = h.rest("POST", "/api/ais/detect", h.key(ada), {"processed": image, "start": start})
        assert status == 200, out
        found[start] = [c | {"source": "processed only"} for c in out["candidates"] if c.get("ok")]
    assert all(found.values())
    cases, expected = [], []
    for g in GENERALS:
        p = ap.filters(g)
        candidates = found.get(p["start"], found["both"])[:12] + [
            e | {"clicks": [[1, 2], [3, 4]], "pixels": [[1, 2]], "settings": ap.METHOD_SETTINGS,
                 "threshold": 0.01, "threshold_initial": 0.02, "notes": [], "source": "processed only"} for e in EDGES]
        cases.append({"kind": "auto", "general": g, "review": "all", "files": files, "candidates": candidates})
        expected.append({"params": p, "rows": [{"passes": ap.passes(c, p), "row": plain(ap.auto_row(files, c, p))}
                                               for c in candidates]})
    got = browser(cases)
    for mine, theirs in zip(expected, got):
        assert mine["params"] == theirs["params"]
        assert [r["passes"] for r in mine["rows"]] == [r["passes"] for r in theirs["rows"]]
        assert [r["row"] for r in mine["rows"]] == [plain(r["row"]) for r in theirs["rows"]]
    # Some kept, some not: the check means something.
    verdicts = [r["passes"] for case in expected for r in case["rows"]]
    assert any(verdicts) and not all(verdicts)


@needs_node
def test_a_click_row_and_a_blinded_file_are_the_browsers():
    result = {"measures": {"length_um": 12.5, "length_str": "12.5", "start_um": 1, "end_um": 13.5, "mid_um": 7,
                           "max_um": 6, "arc_um": 12.9}, "clicks": [[10, 11]], "pixels": [[1, 2], [2, 3]],
              "settings": ap.METHOD_SETTINGS, "threshold": 0.01, "threshold_initial": 0.01, "notes": ["a", "b"],
              "shape": {"width_um": 2.5, "brightness": 0.4}, "source": "czi",
              "z": {"length_3d_um": 13, "z_method": "trace_lift"}}
    blinded = {"czi": {"name": "1-2-3.czi", "rel": "f/1-2-3.czi", "sha": "s", "path": "/x/orig.czi",
                       "original": {"name": "orig.czi"}}}
    plain_files = {"stack": {"name": "s", "rel": "f/s", "sha": "z", "path": "/a/s"},
                   "processed": {"name": "p", "rel": "f/p", "sha": "p"}}
    mine = [plain(ap.row_for(blinded, result, "", "czi")), plain(ap.row_for(plain_files, result, "", "czi"))]
    assert mine[0]["file"] == "f/1-2-3.czi" and mine[1]["file"] == "/a/s"
    assert [plain(r) for r in browser([{"kind": "click", "files": blinded, "result": result},
                                       {"kind": "click", "files": plain_files, "result": result}])] == mine


# --- the report: the port against the browser's code --------------------------------------


def _items():
    batch = {"id": 7, "name": "B", "created_by_name": "Ada", "created_at": "2026-01-02T03:04:05Z", "archived_at": None,
             "completed": 3, "duplicates": 1,
             "assignees": [{"name": "Ada", "images": 3, "completed": 2, "percent": 66.5, "ais": 4, "last_at": None}]}
    images = [{"key": "a", "files": 1, "stored": 1, "ais": 2, "auto": 2, "done": False, "dup_of": None, "assignee_name": "Ada"},
              {"key": "b", "files": 2, "stored": 1, "ais": 0, "auto": 0, "done": False, "dup_of": None},
              {"key": "c", "files": 1, "stored": 1, "ais": 1, "auto": 0, "done": True, "dup_of": None},
              {"key": "d", "files": 1, "stored": 1, "ais": 0, "auto": 0, "done": False, "dup_of": 0}]
    rows = [{"batch_name": "B", "batch_id": 7, "image": "a", "n": 1, "length_um": 10.12345, "origin": "auto",
             "auto_method": "fitted", "pixels": [[1, 1]]},
            {"batch_name": "B", "batch_id": 7, "image": "a", "n": 2, "length_um": 14.5, "origin": "auto"},
            {"batch_name": "B", "batch_id": 7, "image": "c", "n": 1, "length_um": 30.0005, "z_method": "trace_lift"}]
    lines = [{"batch_name": "B", "batch_id": 7, "image": "a", "n": 1, "type": "Soma distance", "length_um": 3.3333},
             {"batch_name": "B", "batch_id": 7, "image": "a", "n": 2, "type": "", "length_um": 1},
             {"batch_name": "B", "batch_id": 7, "image": "a", "n": 3, "type": "Soma distance", "length_um": 5.5}]
    return [{"batch": batch, "images": images, "rows": rows, "measurements": lines}]


@needs_node
def test_report_sheets_are_the_browsers():
    mine = report.sheets(_items())
    theirs = {s["name"]: s for s in browser([{"kind": "sheets", "items": _items()}])[0]}
    order = [("summary", "report.sheet_summary"), ("images", "report.sheet_images"),
             ("assignees", "report.sheet_assignees"), ("ais", "report.sheet_ais"),
             ("measurements", "report.sheet_measurements"), ("measurement_types", "report.sheet_types")]
    # The columns the browser's sheets have, with what the JSON writes
    # differently (dates as ISO, states and "(no type)" as keys).
    as_iso = {"created", "archived", "last_activity"}
    for key, name in order:
        sheet = theirs[name]
        rows = [dict(zip(mine[key]["columns"], [r[c] for c in mine[key]["columns"]])) for r in mine[key]["rows"]]
        assert len(rows) == len(sheet["rows"]), key
        for row, other in zip(rows, sheet["rows"]):
            values = list(row.values())
            for i, (a, b) in enumerate(zip(values, other)):
                column = mine[key]["columns"][i]
                if column in as_iso:
                    continue
                if column == "state":
                    assert b == "batches.state_" + a
                elif key == "measurement_types" and column == "type" and a is None:
                    assert b == "ais.measure_type_none"
                else:
                    assert a == b, (key, column)
        if key in ("ais", "measurements"):
            assert mine[key]["columns"] == sheet["cols"]
    assert mine["summary"]["rows"][0]["created"] == "2026-01-02T03:04:05Z"
    assert [r["state"] for r in mine["images"]["rows"]] == ["auto", "not_uploaded", "done", "duplicate"]


@needs_node
def test_stats_round_as_the_browser():
    cases = [[], [1], [1, 2], [0.0005, 0.0015, 2.5, None, "x", 7], [10.12345, 14.5, 30.0005], [-1.0005, -2.5]]
    assert [report.stats(v) for v in cases] == browser([{"kind": "stats", "values": v} for v in cases])


# --- the tools ------------------------------------------------------------------------------


def test_admin_tools_are_hidden_from_a_user_key(h):
    ada, root = h.user(), h.user("Root", role=users.ROLE_ADMIN)
    mine, admins = h.names(h.key(ada)), h.names(h.admin_key(root))
    for name in ("create_batch_from_files", "start_auto_run", "export_report", "save_result", "delete_result",
                 "detect_image", "upload_instructions"):
        assert name in mine and name in admins
    for name in ("compare_batches", "set_treatments", "get_translation", "reset_batch_auto", "assign_batch"):
        assert name not in mine and name in admins
    # Nothing that deletes a batch or a folder, or resets one whole.
    assert not {"delete_batch", "delete_folder", "reset_batch"} & set(admins)
    error, _ = h.tool(h.key(ada), "list_batches")
    assert not error
    out = h.rpc(h.key(ada), "tools/call", {"name": "compare_batches", "arguments": {"batch_ids": [1]}})
    assert out["error"]["code"] == -32602


def test_a_route_refusal_reads_as_the_route_says(h):
    key = h.key(h.user())
    assert h.tool(key, "get_batch", batch_id=999) == (True, {"error": "no such batch"})
    assert h.tool(key, "rename_batch", batch_id=999, name="x") == (True, {"error": "no such batch"})
    out = h.rpc(key, "tools/call", {"name": "get_batch", "arguments": {"batch_id": "1"}})
    assert out["error"]["code"] == -32602
    out = h.rpc(key, "tools/call", {"name": "get_batch", "arguments": {"batch_id": 1, "extra": 1}})
    assert out["error"]["code"] == -32602


def test_create_upload_auto_run_and_export_through_the_tools(h):
    ada = h.user()
    key = h.key(ada)
    batch_id, images = scene_batch(h, key)
    error, out = h.tool(key, "upload_instructions", batch_id=batch_id)
    assert not error and out["missing"] == []
    assert h.tool(key, "files_stored", shas=[hashlib.sha256(images[0]).hexdigest(), "f" * 64])[1]["stored"] == \
        {hashlib.sha256(images[0]).hexdigest(): True, "f" * 64: False}

    error, run = h.tool(key, "start_auto_run", batch_id=batch_id, general=LOOSE)
    assert not error, run
    assert run["total"] == 2
    # A second run on the same batch waits for none: it is refused.
    assert h.tool(key, "start_auto_run", batch_id=batch_id)[0]
    for _ in range(600):
        state = h.tool(key, "get_auto_run", run_id=run["id"])[1]
        if state["state"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert state["state"] == "finished" and state["done"] == 2 and not state["errors"], state
    assert state["saved"] > 0

    # What it saved is what the browser would have: rowFor + autoFields.
    rows = h.tool(key, "list_results", batch_id=batch_id, include_pixels=True)[1]["results"]
    assert len(rows) == state["saved"]
    assert all(r["origin"] == "auto" and r["auto_method"] == "classic" and r["auto_review"] == "all" for r in rows)
    assert all(r["auto_start"] == "both" and r["pixels"] for r in rows)
    assert "pixels" not in h.tool(key, "list_results", batch_id=batch_id)[1]["results"][0]

    # Run again, skipping done images: nothing left.
    error, again = h.tool(key, "start_auto_run", batch_id=batch_id)
    assert not error and again["total"] == 0

    error, out = h.tool(key, "export_report", batch=str(batch_id))
    assert not error, out
    summary = out["sheets"]["summary"]["rows"][0]
    assert summary["batch_id"] == batch_id and summary["ais"] == len(rows) and summary["completed"] == 2
    assert len(out["sheets"]["ais"]["rows"]) == len(rows)
    assert "auto_method" in out["sheets"]["ais"]["columns"]
    assert {r["state"] for r in out["sheets"]["images"]["rows"]} == {"auto"}
    # The same JSON over REST.
    status, same = h.rest("GET", f"/api/ais/report?batch={batch_id}&sheets=summary", key)
    assert status == 200 and list(same["sheets"]) == ["summary"] and same["sheets"]["summary"] == out["sheets"]["summary"]


def test_review_one_image_and_save_what_you_choose(h):
    ada = h.user()
    key = h.key(ada)
    batch_id, _ = scene_batch(h, key, n=1)
    image = h.tool(key, "batch_status", batch_id=batch_id)[1]["images"][0]["key"]
    error, out = h.tool(key, "detect_image", batch_id=batch_id, image=image, general=LOOSE)
    assert not error, out
    assert out["candidates"] and all(c["passes"] for c in out["candidates"])
    chosen = out["candidates"][0]
    assert chosen["row"]["auto_review"] == "each" and "pixels" not in chosen["candidate"]
    error, saved = h.tool(key, "save_result", batch_id=batch_id, image=image, row=chosen["row"], client_id="pick-0001")
    assert not error, saved
    assert h.tool(key, "save_result", batch_id=batch_id, image=image, row=chosen["row"], client_id="pick-0001")[1]["id"] == saved["id"]
    # It is now left out of the next search.
    again = h.tool(key, "detect_image", batch_id=batch_id, image=image, general=LOOSE)[1]
    assert again["found"] < out["found"]

    error, traced = h.tool(key, "trace_click", batch_id=batch_id, image=image,
                           click=[chosen["row"]["click_x"], chosen["row"]["click_y"]])
    assert not error, traced
    assert traced["result"]["ok"] and traced["row"]["origin"] == "" and traced["row"]["source"] == "processed only"

    error, view = h.tool(key, "get_image", sha=saved["sha"])
    assert not error and view["bytes"] > 0

    # Deletes: the row, then nothing.
    assert not h.tool(key, "delete_result", result_id=saved["id"])[0]
    assert h.tool(key, "delete_result", result_id=saved["id"]) == (True, {"error": "no such result"})


def test_someone_elses_row_and_run_are_not_yours_to_change(h):
    ada, bob = h.user(), h.user("Bob")
    batch_id, _ = scene_batch(h, h.key(ada), n=1)
    image = h.tool(h.key(ada), "batch_status", batch_id=batch_id)[1]["images"][0]["key"]
    row = {"length_um": 1.5, "length_str": "1.5", "click_x": 3, "click_y": 4, "pixels": [[1, 2], [2, 3]]}
    saved = h.tool(h.key(ada), "save_result", batch_id=batch_id, image=image, row=row)[1]
    error, out = h.tool(h.key(bob), "delete_result", result_id=saved["id"])
    assert error and "only whoever accepted it" in out["error"]
    run = h.tool(h.key(ada), "start_auto_run", batch_id=batch_id, skip_done=False)[1]
    error, out = h.tool(h.key(bob), "cancel_auto_run", run_id=run["id"])
    assert error and "only whoever started the run" in out["error"]


def test_a_blinded_user_never_sees_original_names(h):
    ada, root = h.user(), h.user("Root", role=users.ROLE_ADMIN)
    batch_id, _ = scene_batch(h, h.key(ada), n=2, randomize=True)
    text = json.dumps([h.tool(h.key(ada), name, **args)[1] for name, args in (
        ("get_batch", {"batch_id": batch_id}), ("batch_status", {"batch_id": batch_id}),
        ("list_batches", {}), ("export_report", {"batch": "all", "unblind": True}))])
    # A blinded file keeps its role's suffix (" - Processed method 2.5"), not its name.
    assert "c0" + P not in text and "c1" + P not in text and '"c0"' not in text and '"c1"' not in text
    assert "original" not in text
    blind = h.tool(h.key(ada), "export_report", batch="all", unblind=True)[1]
    assert not blind["unblinded"] and "original_names" not in blind["sheets"]
    admin = h.tool(h.admin_key(root), "export_report", batch="all", unblind=True)[1]
    assert admin["unblinded"] and {r["image"] for r in admin["sheets"]["images"]["rows"]} == {"c0", "c1"}


def test_compare_as_json_for_admins(h):
    ada, root = h.user(), h.user("Root", role=users.ROLE_ADMIN)
    key = h.admin_key(root)
    one, _ = scene_batch(h, h.key(ada), n=2)
    two, _ = scene_batch(h, h.key(ada), n=2, seed=10)
    for batch_id in (one, two):
        status = h.tool(key, "batch_status", batch_id=batch_id)[1]["images"]
        h.tool(key, "set_treatments", batch_id=batch_id, treatments={status[0]["key"]: "Control", status[1]["key"]: "Drug"})
        row = {"length_um": 20.0, "length_str": "20", "click_x": 3, "click_y": 4, "pixels": [[1, 2], [2, 3]]}
        for im, length in zip(status, (20.0, 30.0)):
            h.tool(key, "save_result", batch_id=batch_id, image=im["key"], row=row | {"length_um": length})
    error, out = h.tool(key, "compare_batches", batch_ids=[one, two])
    assert not error, out
    assert "plots" not in out
    assert {r["treatment"] for r in out["sheets"]["culture_means"]["rows"]} == {"Control", "Drug"}
    assert out["sheets"]["statistics"]["rows"] and "stars" in out["sheets"]["statistics"]["columns"]
    assert "plots" in h.tool(key, "compare_batches", batch_ids=[one, two], plots=True)[1]
    # The Batches screen's call is unchanged: no sheets, the plots.
    status, raw = h.rest("POST", "/api/ais/compare", key, {"batch_ids": [one, two]})
    assert status == 200 and "sheets" not in raw and "plots" in raw
    # The report has the treatment sheets for an admin.
    sheets = h.tool(key, "export_report", batch=f"{one},{two}")[1]["sheets"]
    assert "by_treatment" in sheets and "original_names" in sheets


def test_reset_auto_deletes_only_auto_rows(h):
    ada, root = h.user(), h.user("Root", role=users.ROLE_ADMIN)
    batch_id, _ = scene_batch(h, h.key(ada), n=1)
    image = h.tool(h.key(ada), "batch_status", batch_id=batch_id)[1]["images"][0]["key"]
    row = {"length_um": 1.5, "length_str": "1.5", "click_x": 3, "click_y": 4, "pixels": [[1, 2], [2, 3]]}
    h.tool(h.key(ada), "save_result", batch_id=batch_id, image=image, row=row)
    h.tool(h.key(ada), "save_result", batch_id=batch_id, image=image, row=row | {"origin": "auto"})
    error, out = h.tool(h.admin_key(root), "reset_batch_auto", batch_id=batch_id)
    assert not error and out["deleted"] == 1
    assert [r["origin"] for r in batches.list_results(h.store, batch_id)] == [""]
