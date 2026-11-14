"""Z-stack .czi files (docs/z-stack.md): read by the Library, grouped into
batches, uploaded in pieces, traced through their slices. On small files
written by tests/czidata.py."""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from app.analysis import zstack
from app.analysis.images import ImageError
from app.analysis.service import Library, NotStored
from app.models import ais, users
from tests.czidata import apotome_phases, write_czi_stack
from tests.test_matlab_routes import Harness
from tests.test_service import stack_planes

LAYOUT = {"kind": "czi", "names": ["Alexa Fluor 594", "Alexa Fluor 488"]}
CLICK = {"click": [38.0, 101.0], "threshold": 0.01}


def axon_stack(slices=5, phases=1):
    """test_service's axon rising through the slices, as a 594/488 .czi: the
    axon in 488 (12-bit), 594 dim. With phases, each slice as ApoTome's grid
    images, the axon all in-focus light (the grid's amplitude)."""
    ais_ = np.stack([p[..., 1] for p in stack_planes(slices=slices)]).astype(float) * 16
    other = np.full_like(ais_, 40.0)
    if phases == 1:
        return write_czi_stack({"Alexa Fluor 594": other.astype(np.uint16), "Alexa Fluor 488": ais_.astype(np.uint16)})
    with_grid = {name: np.stack([apotome_phases(v[z], 500 + v[z] * 0.2, phases) for z in range(slices)])
                 for name, v in (("Alexa Fluor 594", other), ("Alexa Fluor 488", ais_))}
    return write_czi_stack(with_grid)


def described(data: bytes, name: str = "Slide7zstackExperiment-27.czi", folder: str = "root") -> dict:
    """The file as the browser lists it: sha, layout and what its header says."""
    import hashlib

    from app.analysis.local import czi_stack_of

    return {"name": name, "rel": f"{folder}/{name}", "sha": hashlib.sha256(data).hexdigest(), "size": len(data),
            "layout": LAYOUT, "zstack": czi_stack_of(data)}


# --- the Library -----------------------------------------------------------------


def stored(tmp_path, data, apotome=None, plane=1):
    known = {}
    lib = Library(tmp_path, stacks=known.get)
    source = lib.add(data)["sha256"]
    manifest = zstack.czi_manifest(source, {"plane": plane, "apotome": apotome, "z_step_um": 0.77,
                                            "pixel_um": 0.2, "count": 5})
    sha = zstack.sha(manifest)
    known[sha] = manifest
    return lib, sha, source


def test_a_czi_stack_is_the_projection_of_its_ais_channel(tmp_path):
    lib, sha, source = stored(tmp_path, axon_stack())
    assert lib.is_stack(sha) and not lib.is_czi(sha) and lib.is_czi(source)
    stack = lib.stack(sha)
    assert stack.shape[0] == 5 and stack.dtype == np.uint16
    assert np.array_equal(lib.array(sha), stack.max(axis=0))
    assert lib.slice_png(sha, 2)[:4] == b"\x89PNG"
    assert [c["name"] for c in lib.channels(source)] == LAYOUT["names"]


def test_a_click_on_a_czi_stack_is_lifted_through_its_slices(tmp_path):
    from app.analysis import ais_auto as aa

    lib, sha, _ = stored(tmp_path, axon_stack())
    answer = lib.trace(sha, None, (38.0, 101.0), None, 0.01, aa.DEFAULT)
    assert answer["ok"], answer.get("error")
    assert answer["z"]["length_3d_um"] > answer["z"]["length_xy_um"] > 0
    assert 1 <= answer["z"]["z_start"] <= 5


def test_apotome_sectioned_and_widefield_are_two_stacks(tmp_path):
    data = axon_stack(phases=5)
    lib, sectioned, _ = stored(tmp_path / "a", data, "sectioned")
    lib2, widefield, _ = stored(tmp_path / "b", data, "widefield")
    assert sectioned != widefield
    # The axon is all grid modulation: sectioned shows it on a dark ground,
    # widefield on the grid's mean.
    s, w = lib.array(sectioned).astype(float), lib2.array(widefield).astype(float)
    assert s.min() < 16 * 5 and w.min() >= 16 * 450


def test_a_czi_stack_with_other_slices_than_recorded_is_refused(tmp_path):
    known = {}
    lib = Library(tmp_path, stacks=known.get)
    source = lib.add(axon_stack())["sha256"]
    manifest = zstack.czi_manifest(source, {"plane": 1, "apotome": None, "z_step_um": 0.77, "pixel_um": 0.2,
                                            "count": 7})
    known[zstack.sha(manifest)] = manifest
    with pytest.raises(ImageError, match="other slices"):
        lib.stack(zstack.sha(manifest))


def test_a_czi_stack_needs_its_file(tmp_path):
    known = {}
    lib = Library(tmp_path, stacks=known.get)
    manifest = zstack.czi_manifest("a" * 64, {"plane": 1, "apotome": None, "z_step_um": 0.77, "pixel_um": 0.2,
                                              "count": 5})
    known[zstack.sha(manifest)] = manifest
    with pytest.raises(NotStored):
        lib.require(zstack.sha(manifest))


def test_somata_come_from_a_soma_stain_when_the_czi_has_one(tmp_path):
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:120, 0:160]
    body = (np.exp(-((xx - 60) ** 2 + (yy - 60) ** 2) / 300) * 3000).astype(np.uint16)
    amca = np.stack([body * (1.0 if z == 2 else 0.3) for z in range(4)]).astype(np.uint16)
    ais_ = rng.integers(0, 50, (4, 120, 160), dtype=np.uint16)
    data = write_czi_stack({"Alexa Fluor 488": ais_, "AMCA": amca}, pixel_um=0.2)
    known = {}
    lib = Library(tmp_path, stacks=known.get)
    source = lib.add(data)["sha256"]
    manifest = zstack.czi_manifest(source, {"plane": 0, "apotome": None, "z_step_um": 0.77, "pixel_um": 0.2,
                                            "count": 4})
    sha = zstack.sha(manifest)
    known[sha] = manifest
    found = lib.soma(sha)
    assert found is not None
    bodies = found.split or found.whole
    assert bodies.depths and bodies.depths[0] == pytest.approx(3, abs=0.6)   # z numbers from 1


def test_an_upload_that_is_not_an_image_leaves_nothing_behind(tmp_path):
    lib = Library(tmp_path)
    incoming = lib.receive()
    incoming.write(b"ZISRAWFILE" + b"\0" * 100)
    with pytest.raises(ImageError):
        incoming.finish()
    assert not list(lib.files.iterdir())


def test_a_file_already_stored_is_not_written_again(tmp_path):
    lib = Library(tmp_path)
    data = axon_stack()
    first = lib.add(data)
    path = lib.file_path(first["sha256"])
    before = path.stat().st_mtime_ns
    assert lib.add(data) == first and path.stat().st_mtime_ns == before
    assert first["czi"] and first["z"] == {"slices": 5, "phases": 1}
    assert [p.name for p in lib.files.iterdir()] == [path.name]


def test_a_file_copied_in_from_a_path_must_still_be_the_same(tmp_path):
    data = axon_stack()
    where = tmp_path / "elsewhere.czi"
    where.write_bytes(data)
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    lib = Library(tmp_path / "s", resolver=lambda s: str(where) if s == sha else None)
    assert lib.file_path(sha).read_bytes() == data
    lib.file_path(sha).unlink()
    where.write_bytes(data[:-1] + b"x")
    with pytest.raises(NotStored):
        lib.file_path(sha)
    assert not list(lib.files.glob("*.part"))


# --- batches ----------------------------------------------------------------------


def test_a_czi_with_slices_is_one_stack_image():
    data = axon_stack(phases=5)
    images = ais.group(ais.clean_files([described(data)]))
    assert len(images) == 1
    image = images[0]
    file = image["files"]["stack"]
    assert image["cell"] == "Slide7zstackExperiment-27"
    assert [s["sha"] for s in file["slices"]] == [described(data)["sha"]]
    assert "zstack" not in file["slices"][0] and "layout" not in file["slices"][0]
    assert image["z_stack"]["source"] == "czi" and image["z_stack"]["count"] == 5
    assert image["z_stack"]["plane"] == 1                 # Alexa Fluor 488
    assert image["z_stack"]["apotome"] == "sectioned"     # the default
    assert image["z_stack"]["z_step_um"] == pytest.approx(0.77)
    assert file["sha"] == zstack.sha(zstack.manifest_of(file, image["z_stack"]))
    widefield = ais.group(ais.clean_files([described(data)]), czi={"apotome": "widefield"})[0]
    assert widefield["files"]["stack"]["sha"] != file["sha"]


def test_a_czi_without_its_header_stays_an_ordinary_czi():
    f = described(axon_stack())
    del f["zstack"]
    image = ais.group(ais.clean_files([f]))[0]
    assert set(image["files"]) == {"czi"}


def test_picking_the_other_channel_is_another_stack():
    f = described(axon_stack())
    roles = [{"role": "ais", "label": ""}, {"role": "other", "label": "488"}]
    image = ais.group(ais.clean_files([f]), choices=[{"layout": LAYOUT, "roles": roles}])[0]
    assert image["z_stack"]["plane"] == 0
    assert image["files"]["stack"]["sha"] != ais.group(ais.clean_files([f]))[0]["files"]["stack"]["sha"]


def test_a_czi_that_does_not_say_its_z_step_takes_the_one_entered():
    data = write_czi_stack({"Alexa Fluor 488": np.zeros((3, 8, 8), np.uint16)}, z_um=None)
    f = described(data) | {"layout": {"kind": "czi", "names": ["Alexa Fluor 488"]}}
    with pytest.raises(ais.BatchError, match="z step"):
        ais.group(ais.clean_files([f]))
    image = ais.group(ais.clean_files([f]), stack={"plane": 0, "z_step_um": 0.5, "pixel_um": 0.3})[0]
    assert image["z_stack"]["z_step_um"] == 0.5 and image["z_stack"]["pixel_um"] == pytest.approx(0.10238)


def test_a_czi_stack_needs_its_channels():
    f = described(axon_stack())
    del f["layout"]
    with pytest.raises(ais.BatchError, match="needs its channels"):
        ais.clean_files([f])


# --- routes -----------------------------------------------------------------------


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def post(h, path, who, **body):
    return h.get("POST", path, session=who, body=body)


def upload(h, who, data):
    return h.get("POST", "/api/ais/files", session=who, raw=data,
                 extra=[(b"content-type", b"application/octet-stream"), (b"x-csrf-token", who.csrf.encode())])


def test_a_czi_stack_goes_from_upload_to_an_accepted_row(h):
    ann = h.user()
    data = axon_stack(phases=5)
    uploaded = upload(h, ann, data)
    assert uploaded.status == 200, uploaded.data
    assert json.loads(uploaded.data)["z"] == {"slices": 5, "phases": 5}
    made = post(h, "/api/ais/batches/upload", ann, name="z", files=[described(data)], randomize=False,
                czi_stack={"apotome": "sectioned"})
    assert made.status == 200, made.data
    batch = json.loads(made.data)
    image = batch["images"][0]
    file = image["files"]["stack"]
    assert file["stored"] is True and image["z_stack"]["apotome"] == "sectioned"
    traced = post(h, "/api/ais/trace", ann, processed=file["sha"], **CLICK)
    assert traced.status == 200, traced.data
    answer = json.loads(traced.data)
    assert answer["ok"] and answer["z"]["length_3d_um"] > 0
    row = {"length_um": answer["measures"]["length_um"], "pixels": answer["pixels"]} | answer["z"]
    accepted = post(h, "/api/ais/results", ann, batch_id=batch["id"], image=image["key"], row=row)
    assert accepted.status == 200, accepted.data
    shown = json.loads(h.get("GET", f"/api/ais/batches/{batch['id']}/layouts", session=ann).data)
    assert shown["stacks"]["from_file"] == 1


def test_the_czi_itself_downloads_for_exports(h):
    ann = h.user()
    data = axon_stack()
    sha = json.loads(upload(h, ann, data).data)["sha256"]
    got = h.get("GET", f"/api/ais/files/{sha}/file", session=ann)
    assert got.status == 200 and got.data == data


def test_an_upload_over_the_limit_is_refused_and_leaves_no_temp(tmp_path, monkeypatch):
    import tests.test_matlab_routes as harness

    real = harness.real_holder
    monkeypatch.setattr(harness, "real_holder", lambda *a, **kw: real(*a, **kw | {"upload_limit_bytes": 4096}))
    h = Harness(tmp_path)
    ann = h.user()
    assert upload(h, ann, axon_stack()).status == 413
    assert not list(h.library.files.glob("*.part"))


def test_a_base64_upload_stays_capped(h):
    ann = h.user()
    from app.routes import ais as routes

    big = h.get("POST", "/api/ais/files", session=ann, raw=b"{}",
                extra=[(b"content-type", b"application/json"),
                       (b"content-length", str(routes.JSON_LIMIT_BYTES + 1).encode())])
    assert big.status == 413


def test_a_blinded_czi_stack_shows_no_name_to_a_user(h):
    ann = h.user()
    admin = h.user("Boss", role=users.ROLE_ADMIN)
    data = axon_stack()
    upload(h, ann, data)
    batch = json.loads(post(h, "/api/ais/batches/upload", admin, name="z", files=[described(data)]).data)
    seen = json.loads(h.get("GET", f"/api/ais/batches/{batch['id']}", session=ann).data)
    text = json.dumps(seen)
    assert "Slide7zstackExperiment" not in text
