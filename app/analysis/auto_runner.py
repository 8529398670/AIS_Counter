"""Auto mode over a whole batch, run by the server for whoever asks (an agent
through /mcp, or a script with an API key), where the browser's runs it in
the page (static/js/ais_auto.js saveAll, review "all").

The same steps, image after image: the included images (less the complete
ones, unless asked), detect on each with the image's saved AIS excluded, the
filters, and every kept candidate saved as the row the browser would save
(app/analysis/auto_params.py). Progress goes to the batch's live activity,
so everyone's Batches screen shows the run as it shows a browser's.

One worker thread, runs in the order asked, one run per batch at a time:
detect is heavy, and two runs on one batch would each save what the other
found. Runs live in memory: a restart ends them (what they saved stays),
and the last FINISHED_KEPT finished ones can still be asked about.
"""
from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from app.analysis import ais_auto as aa
from app.analysis import auto_params as ap
from app.analysis.images import ImageError
from app.analysis.service import Library
from app.core.db import Store
from app.models import ais as batches
from app.models import to_iso, utc_now

FINISHED_KEPT = 50
ERRORS_KEPT = 100
STATES = ("queued", "running", "finished", "stopped", "failed")


class RunError(ValueError):
    """A run that cannot start, worded for whoever asked."""


def plan(general: dict[str, Any] | None = None, settings: dict[str, Any] | None = None,
         threshold: Any = None, engine: Any = None) -> dict[str, Any]:
    """The checked choices of a run: what the browser freezes at its start
    (AisAuto.start: threshold, settings, engine, then filters())."""
    g = ap.general(general)
    s = ap.method_settings(settings)
    t = ap.THRESHOLD if threshold is None else threshold
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not 0 <= t <= 1:
        raise ap.ParamError("threshold must be between 0 and 1")
    if engine not in (None, "fast"):
        raise ap.ParamError("engine must be fast, or left out")
    return {"general": g, "settings": s, "threshold": float(t), "engine": engine, "filters": ap.filters(g)}


class AutoRuns:
    def __init__(self, library: Library, store: Store, activity: batches.Activity,
                 clock: Callable[[], str] | None = None) -> None:
        self.library = library
        self.store = store
        self.activity = activity
        self._clock = clock or (lambda: to_iso(utc_now()))
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._queue: list[str] = []
        self._thread: threading.Thread | None = None

    # --- asking ----------------------------------------------------------------

    def start(self, batch_id: int, user_id: int, choices: dict[str, Any], *, skip_done: bool | None = None,
              mark_done: bool = False, images: list[str] | None = None) -> dict[str, Any]:
        batch = batches.get_batch(self.store, batch_id)
        if batch is None:
            raise RunError("no such batch")
        keys = {im["key"] for im in batch["images"]}
        if images is not None:
            if not isinstance(images, list) or not all(isinstance(k, str) for k in images):
                raise RunError("images must be a list of image keys")
            unknown = [k for k in images if k not in keys]
            if unknown:
                raise RunError(f"no such image in this batch: {unknown[0]}")
        skip = choices["general"]["auto_skip_done"] if skip_done is None else skip_done
        queue = self._queue_for(batch, skip, images)
        run_id = secrets.token_hex(6)
        run = {"id": run_id, "batch_id": batch_id, "user_id": user_id, "state": "queued",
               "created_at": self._clock(), "started_at": None, "finished_at": None,
               "queue": queue, "done": 0, "total": len(queue), "found": 0, "hidden": 0, "saved": 0,
               "marked_done": 0, "errors": [], "current": None, "skip_done": skip, "mark_done": mark_done,
               "choices": choices, "_stop": False}
        with self._lock:
            if any(r["batch_id"] == batch_id and r["state"] in ("queued", "running") for r in self._runs.values()):
                raise RunError("an auto run is already going on this batch")
            self._runs[run_id] = run
            self._queue.append(run_id)
            self._trim()
            self._ensure_thread()
            self._wake.notify()
        return self.view(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            return self.view(run) if run else None

    def list(self, batch_id: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [self.view(r) for r in reversed(self._runs.values()) if batch_id in (None, r["batch_id"])]

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        """Stop after the image being worked on; one still queued never starts."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run["_stop"] = True
            if run["state"] == "queued":
                self._queue.remove(run_id)
                self._end(run, "stopped")
            return self.view(run)

    @staticmethod
    def view(run: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in run.items() if not k.startswith("_") and k not in ("queue", "choices")}
        out["choices"] = {"general": run["choices"]["general"], "settings": run["choices"]["settings"],
                          "threshold": run["choices"]["threshold"], "engine": run["choices"]["engine"]}
        out["images"] = list(run["queue"])
        return out

    # --- the queue -----------------------------------------------------------------

    def _queue_for(self, batch: dict[str, Any], skip: bool, only: list[str] | None) -> list[str]:
        """AisAuto.start: the included images in list order, less the complete
        ones (an accepted AIS or a done mark, Ais.isComplete) when skip; only
        narrows it to those keys."""
        excluded = batches.excluded_keys(batch)
        with_ais = {r["image"] for r in batches.list_results(self.store, batch["id"])}
        done = set(batch["skipped"])
        return [im["key"] for im in batch["images"]
                if im["key"] not in excluded and (only is None or im["key"] in only)
                and not (skip and (im["key"] in with_ais or im["key"] in done))]

    def _trim(self) -> None:
        finished = [rid for rid, r in self._runs.items() if r["state"] not in ("queued", "running")]
        for rid in finished[:max(0, len(finished) - FINISHED_KEPT)]:
            del self._runs[rid]

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="auto-runs", daemon=True)
            self._thread.start()

    def _end(self, run: dict[str, Any], state: str) -> None:
        run["state"] = state
        run["current"] = None
        run["finished_at"] = self._clock()

    def _work(self) -> None:
        while True:
            with self._lock:
                while not self._queue:
                    self._wake.wait()
                run = self._runs[self._queue.pop(0)]
                run["state"] = "running"
                run["started_at"] = self._clock()
            try:
                self._run(run)
            except Exception as exc:  # noqa: BLE001 -- a run must not take the worker down with it
                print(f"[auto] run {run['id']}: {exc!r}", flush=True)
                with self._lock:
                    run["errors"].append({"image": run["current"], "error": "internal error"})
                    self._end(run, "failed")
            self._report(run)

    # --- one run ---------------------------------------------------------------------

    def _report(self, run: dict[str, Any]) -> None:
        state = {"queued": "running", "running": "running", "finished": "finished"}.get(run["state"], "stopped")
        try:
            self.activity.report(run["batch_id"], run["user_id"],
                                 {"kind": "auto", "state": state, "done": run["done"], "total": run["total"]})
        except batches.BatchError:
            pass

    def _run(self, run: dict[str, Any]) -> None:
        choices = run["choices"]
        p = choices["filters"]
        settings = aa.Settings.from_dict(choices["settings"])
        detect = self.library.detect_fast if choices["engine"] == "fast" else self.library.detect
        for index, key in enumerate(run["queue"]):
            if run["_stop"]:
                with self._lock:
                    self._end(run, "stopped")
                return
            with self._lock:
                run["current"] = key
            self._report(run)
            batch = batches.get_batch(self.store, run["batch_id"])
            image = next((im for im in batch["images"] if im["key"] == key), None) if batch else None
            if batch is None:
                with self._lock:
                    run["errors"].append({"image": key, "error": "the batch is gone"})
                    self._end(run, "failed")
                return
            try:
                if image is None:
                    raise ImageError("the image is no longer in this batch")
                saved, kept, hidden = self._one(run, index, image, p, settings, detect)
            except (ImageError, batches.BatchError) as exc:
                with self._lock:
                    if len(run["errors"]) < ERRORS_KEPT:
                        run["errors"].append({"image": key, "error": str(exc)})
            else:
                with self._lock:
                    run["found"] += kept
                    run["hidden"] += hidden
                    run["saved"] += saved
            with self._lock:
                run["done"] += 1
        with self._lock:
            self._end(run, "finished")

    def _one(self, run: dict[str, Any], index: int, image: dict[str, Any], p: dict[str, Any],
             settings: Any, detect: Callable[..., dict[str, Any]]) -> tuple[int, int, int]:
        """AisAuto.find then saveAll's step for one image: (saved, kept, hidden)."""
        files = image["files"]
        kind = ap.kind(files)
        processed = files[ap.traced(files)]["sha"]
        raw = files["raw"]["sha"] if kind == "pair" else None
        rows = [r for r in batches.list_results(self.store, run["batch_id"]) if r["image"] == image["key"]]
        z_method = run["choices"]["general"]["z_method"] if files.get("stack") else None
        out = detect(processed, raw, run["choices"]["threshold"], settings, ap.start_for(kind, p["start"]),
                     [r["pixels"] for r in rows if r.get("pixels")], z_method)
        candidates = out.get("candidates", [])
        kept = [c for c in candidates if ap.passes(c, p)]
        saved = 0
        for n, c in enumerate(kept):
            row = ap.auto_row(files, c, p)
            batches.add_result(self.store, run["batch_id"], image["key"], row, run["user_id"],
                               f"auto-{run['id']}-{index}-{n}")
            saved += 1
        if run["mark_done"]:
            batches.set_done(self.store, run["batch_id"], image["key"], True)
            with self._lock:
                run["marked_done"] += 1
        return saved, len(kept), len(candidates) - len(kept)
