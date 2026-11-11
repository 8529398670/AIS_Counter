"""Channel roles picked at import (app/analysis/channels.py): which channel is
the AIS, which the soma/dendrite stain, and the views that trace them."""
from __future__ import annotations

import io

import numpy as np
import pytest
import tifffile

from app.analysis import auto_params as ap
from app.analysis import channels, local, zstack
from app.analysis.czi import read_czi
from app.analysis.service import Library
from app.core import db
from app.models import ais
from tests.czidata import write_czi

AIS, SOMA = {"role": "ais", "label": ""}, {"role": "soma", "label": ""}


def other(label):
    return {"role": "other", "label": label}


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


@pytest.fixture
def library(tmp_path, store):
    return Library(tmp_path, None, lambda sha: ais.manifest_for(store, sha))


def planes(names, H=24, W=32):
    rng = np.random.default_rng(len(names))
    return {n: rng.integers(0, 4096, (H, W), dtype=np.uint16) for n in names}


def rgb_tiff(H=24, W=32):
    rng = np.random.default_rng(7)
    arr = rng.integers(0, 65535, (H, W, 3), dtype=np.uint16)
    out = io.BytesIO()
    tifffile.imwrite(out, arr, photometric="rgb")
    return out.getvalue(), arr


def entry(library, rel, data, layout=True):
    out = {"name": rel.split("/")[-1], "rel": rel, "sha": library.add(data)["sha256"], "size": len(data)}
    if layout:
        out["layout"] = local.layout_of(data)[0]
    return out


# --- roles -----------------------------------------------------------------------


@pytest.mark.parametrize("roles", [
    [AIS, AIS], [SOMA, other("x")], [AIS, SOMA, SOMA], [AIS, other("")], [AIS, {"role": "dendrite"}],
    [AIS], [AIS, other("x" * 61)], "ais",
])
def test_roles_that_can_not_be_right_are_refused(roles):
    count = len(roles) if isinstance(roles, list) and roles != [AIS] else 2
    with pytest.raises(channels.ChannelError):
        channels.clean_roles(roles, count)


def test_roles_are_cleaned_and_picked():
    roles = channels.clean_roles([other("  MAP2 "), {"role": "soma", "label": "ignored"}, AIS], 3)
    assert roles == [other("MAP2"), SOMA, AIS]
    assert channels.picks(roles) == (2, 1)


@pytest.mark.parametrize("names", [
    ["Alexa Fluor 488", "AMCA"], ["AMCA", "Alexa Fluor 594"], ["Alexa Fluor 594", "Cy5"], ["Cy5"],
    ["DAPI", "Alexa Fluor 594", "Alexa Fluor 488"],
])
def test_the_default_roles_are_what_a_czi_was_read_with_before(names):
    image = read_czi(write_czi(planes(names)))
    roles = channels.default_roles({"kind": "czi", "names": names})
    ais_at, soma_at = channels.picks(roles)
    assert names[ais_at] == image.ais_name
    assert (names[soma_at] if soma_at is not None else None) == image.soma_name


def test_a_tiffs_planes_are_named_by_colour_or_number():
    data, _ = rgb_tiff()
    assert local.layout_of(data) == ({"kind": "tiff", "names": ["Red", "Green", "Blue"]}, None)
    grey = io.BytesIO()
    tifffile.imwrite(grey, np.zeros((8, 8), np.uint16))
    assert local.layout_of(grey.getvalue())[0]["names"] == ["Channel 1"]


# --- at import ---------------------------------------------------------------------


def test_the_default_choice_keeps_the_files_own_sha(store, library):
    data = write_czi(planes(["Alexa Fluor 488", "AMCA"]))
    f = entry(library, "f/a.czi", data)
    batch = ais.create_batch(store, "b", "upload", [f], 1, channel_roles=[
        {"layout": f["layout"], "roles": [AIS, SOMA]}])
    image = batch["images"][0]
    assert "sha" not in image["channels"]
    assert ais.traced_sha(image, "czi") == f["sha"]
    assert "layout" not in image["files"]["czi"]


def test_without_roles_nothing_changes(store, library):
    data = write_czi(planes(["Alexa Fluor 594", "AMCA"]))
    batch = ais.create_batch(store, "b", "upload", [entry(library, "f/a.czi", data)], 1)
    assert "channels" not in batch["images"][0]
    assert "layout" not in batch["images"][0]["files"]["czi"]


def test_a_czi_with_its_ais_in_another_channel_is_traced_from_that_channel(store, library):
    names = ["Alexa Fluor 488", "Alexa Fluor 594", "AMCA"]
    data = write_czi(planes(names))
    f = entry(library, "f/a.czi", data)
    batch = ais.create_batch(store, "b", "upload", [f], 1, channel_roles=[
        {"layout": f["layout"], "roles": [other("MAP2"), AIS, SOMA]}])
    image = batch["images"][0]
    view = ais.traced_sha(image, "czi")
    assert view != f["sha"] and view == image["channels"]["sha"]
    want = read_czi(data)
    assert np.array_equal(library.array(view), want.as_tiff("Alexa Fluor 594"))
    assert np.array_equal(library.array(f["sha"]), want.as_tiff("Alexa Fluor 488"))
    assert library.is_czi(view)
    assert [c["name"] for c in library.channels(view)] == names
    assert library.file_path(view) == library.file_path(f["sha"])
    assert library.preview(view) != library.preview(f["sha"])


def test_a_colour_tiff_is_traced_from_the_chosen_plane(store, library):
    data, arr = rgb_tiff()
    f = entry(library, "f/a.tif", data)
    batch = ais.create_batch(store, "b", "upload", [f], 1, channel_roles=[
        {"layout": f["layout"], "roles": [other("MAP2"), AIS, other("DAPI")]}])
    image = batch["images"][0]
    view = ais.traced_sha(image, "raw")
    assert np.array_equal(library.array(view), arr[:, :, 1])
    assert np.array_equal(library.array(f["sha"]), arr[:, :, 0])
    processed, raw = library.matlab_pair(view, None)
    assert np.array_equal(tifffile.imread(io.BytesIO(processed)), arr[:, :, 1])


def test_the_chosen_soma_channel_gives_the_somata(store, library):
    names = ["Alexa Fluor 594", "Cy5"]
    data = write_czi(planes(names))
    f = entry(library, "f/a.czi", data)
    assert library.soma(f["sha"]) is None
    batch = ais.create_batch(store, "b", "upload", [f], 1, channel_roles=[
        {"layout": f["layout"], "roles": [AIS, SOMA]}])
    assert library.soma(ais.traced_sha(batch["images"][0], "czi")) is not None


def test_a_tiff_with_a_soma_channel_may_start_from_somata(store, library):
    data, _ = rgb_tiff()
    f = entry(library, "f/a.tif", data)
    batch = ais.create_batch(store, "b", "upload", [f], 1, channel_roles=[
        {"layout": f["layout"], "roles": [SOMA, AIS, other("x")]}])
    image = batch["images"][0]
    assert ap.has_soma(image)
    assert ap.start_for("raw only", "soma", ap.has_soma(image)) == "soma"
    assert ap.start_for("raw only", "soma") == "soma"           # any channel may show somata
    assert ap.start_for("stack", "soma") == "both"              # a Z-stack never has any
    assert not ap.has_soma({"files": {"stack": {"slices": []}}})
    assert library.soma(ais.traced_sha(image, "raw")) is not None


def test_mixed_layouts_each_get_their_own_roles(store, library):
    a = entry(library, "f/a.czi", write_czi(planes(["Alexa Fluor 488", "Alexa Fluor 594", "AMCA"])))
    b = entry(library, "f/b.czi", write_czi(planes(["Alexa Fluor 594", "AMCA"])))
    batch = ais.create_batch(store, "b", "upload", [a, b], 1, channel_roles=[
        {"layout": a["layout"], "roles": [other("x"), AIS, SOMA]},
        {"layout": b["layout"], "roles": [SOMA, AIS]},
    ])
    by_cell = {im["cell"]: im["channels"] for im in batch["images"]}
    assert channels.picks(by_cell["a"]["roles"]) == (1, 2)
    assert channels.picks(by_cell["b"]["roles"]) == (1, 0)
    assert "sha" in by_cell["a"] and "sha" in by_cell["b"]


def test_a_stacks_ais_channel_is_its_plane(store):
    layout = {"kind": "tiff", "names": ["Red", "Green", "Blue"]}
    slices = [{"name": f"c_z{z}c1+2.tif", "rel": f"f/c_z{z}c1+2.tif", "sha": f"{z:064x}", "size": 1, "layout": layout}
              for z in (1, 2)]
    options = {"plane": 0, "z_step_um": 0.5, "pixel_um": 0.2}
    batch = ais.create_batch(store, "b", "upload", slices, 1, stack=options, channel_roles=[
        {"layout": layout, "roles": [other("x"), other("y"), AIS]}])
    image = batch["images"][0]
    assert image["z_stack"]["plane"] == 2
    assert image["files"]["stack"]["sha"] == zstack.sha(zstack.manifest(image["files"]["stack"]["slices"],
                                                                       options | {"plane": 2}))
    assert ais.manifest_for(store, image["files"]["stack"]["sha"])["plane"] == 2


# --- later ----------------------------------------------------------------------------


def test_roles_changed_later_give_a_new_sha_and_undo_done(store, library):
    data = write_czi(planes(["Alexa Fluor 488", "Alexa Fluor 594", "AMCA"]))
    f = entry(library, "f/a.czi", data, layout=False)
    batch = ais.create_batch(store, "b", "upload", [f], 1)
    key = batch["images"][0]["key"]
    ais.set_done(store, batch["id"], key, True)
    layouts = {key: ("czi", library.layout(f["sha"]))}
    record, changed = ais.set_channels(store, batch["id"], None, [
        {"layout": layouts[key][1], "roles": [other("x"), AIS, SOMA]}], layouts)
    image = record["images"][0]
    assert changed == [key] and key not in record["skipped"]
    view = ais.traced_sha(image, "czi")
    assert np.array_equal(library.array(view), read_czi(data).as_tiff("Alexa Fluor 594"))
    # Back to the guess: the file's own sha again.
    record, changed = ais.set_channels(store, batch["id"], None, [
        {"layout": layouts[key][1], "roles": [AIS, other("x"), SOMA]}], {})
    assert changed == [key] and ais.traced_sha(record["images"][0], "czi") == f["sha"]


def test_the_layouts_of_a_folder_are_counted(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.czi").write_bytes(write_czi(planes(["Alexa Fluor 488", "AMCA"])))
    (folder / "b.czi").write_bytes(write_czi(planes(["Alexa Fluor 488", "AMCA"])))
    (folder / "c.tif").write_bytes(rgb_tiff()[0])
    found = local.layouts_under(str(folder))
    assert [(o["layout"]["names"], o["count"]) for o in found] == [
        (["Alexa Fluor 488", "AMCA"], 2), (["Red", "Green", "Blue"], 1)]
    assert found[0]["roles"] == [AIS, SOMA] and len(found[0]["colors"]) == 2
    assert found[1]["roles"] == [AIS, other("Green"), other("Blue")]
    _, hashed = local.hashed_files(str(folder))
    assert all("layout" in f for f in hashed)


def test_the_channels_dialog_lists_a_batchs_layouts_with_their_results(store, library):
    from app.routes.ais import _batch_layouts

    a = entry(library, "f/a.czi", write_czi(planes(["Alexa Fluor 488", "AMCA"])), layout=False)
    b = entry(library, "f/b.tif", rgb_tiff()[0], layout=False)
    batch = ais.create_batch(store, "b", "upload", [a, b], 1)
    ais.add_result(store, batch["id"], "a", {"length_um": 20.0, "file": "a.czi"}, 1)
    out = _batch_layouts(library, store, ais.get_batch(store, batch["id"]), None)
    assert out["images"] == 2 and out["unread"] == 0
    assert [(o["layout"]["names"], o["count"], o["results"]) for o in out["layouts"]] == [
        (["Alexa Fluor 488", "AMCA"], 1, 1), (["Red", "Green", "Blue"], 1, 0)]
    assert out["layouts"][0]["colors"]
