"""A Z-stack through the real routes: added, uploaded, clicked, accepted, and
what someone who isn't an admin gets to see of a blinded one."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.analysis import zlength, zstack
from app.models import ais, users
from tests.test_matlab_routes import Harness
from tests.test_service import _tiff_bytes, stack_planes, synthetic

ROOT = Path(__file__).resolve().parents[1]
STACK = {"plane": 1, "z_step_um": 0.5, "pixel_um": 0.2}
CLICK = {"click": [38.0, 101.0], "threshold": 0.01}


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def manifest(h, folder="Slide7_27", cell="IP-04"):
    """Each slice stored, as the browser's upload does, and listed for an add."""
    out = []
    for z, plane in enumerate(stack_planes(), 1):
        data = _tiff_bytes(plane)
        name = f"{cell}_z{z:02}c1+2.tif"
        out.append({"name": name, "rel": f"root/{folder}/{name}", "sha": h.library.add(data)["sha256"], "size": len(data)})
    return out


def post(h, path, who, **body):
    return h.get("POST", path, session=who, body=body)


def added(h, who, **extra):
    response = post(h, "/api/ais/batches/upload", who, name="z", files=manifest(h), stack=STACK, **extra)
    assert response.status == 200, response.data
    return json.loads(response.data)


def test_a_stack_goes_from_add_to_an_accepted_row(h):
    ann = h.user()
    batch = added(h, ann, randomize=False)
    image = batch["images"][0]
    file = image["files"]["stack"]
    assert image["z_stack"] == {"count": 5} | STACK and file["stored"] is True
    assert all(part["stored"] for part in file["slices"])

    traced = post(h, "/api/ais/trace", ann, processed=file["sha"], **CLICK)
    assert traced.status == 200, traced.data
    answer = json.loads(traced.data)
    assert answer["ok"] and answer["z"]["length_3d_um"] > 0

    row = {"length_um": answer["measures"]["length_um"], "pixels": answer["pixels"]} | answer["z"]
    accepted = post(h, "/api/ais/results", ann, batch_id=batch["id"], image=image["key"], row=row)
    assert accepted.status == 200, accepted.data
    saved = ais.list_results(h.store, batch["id"])[0]
    assert saved["length_3d_um"] == answer["z"]["length_3d_um"]
    assert saved["z_path"] == answer["z"]["z_path"]


def test_a_stack_is_not_stored_until_every_slice_is(h):
    ann = h.user()
    files = manifest(h)
    (h.library.files / f"{files[2]['sha']}.tif").unlink()
    batch = json.loads(post(h, "/api/ais/batches/upload", ann, name="z", files=files, stack=STACK, randomize=False).data)
    file = batch["images"][0]["files"]["stack"]
    assert file["stored"] is False
    assert [part["stored"] for part in file["slices"]] == [True, True, False, True, True]
    status = json.loads(h.get("GET", f"/api/ais/batches/{batch['id']}/status", session=ann).data)
    assert (status["images"][0]["files"], status["images"][0]["stored"]) == (5, 4)
    assert h.get("GET", f"/api/ais/files/{file['sha']}/thumb.png", session=ann).status == 404


def test_the_slices_can_be_viewed_one_by_one(h):
    ann = h.user()
    sha = added(h, ann, randomize=False)["images"][0]["files"]["stack"]["sha"]
    shown = h.get("GET", f"/api/ais/files/{sha}/slice/2.png", session=ann)
    assert shown.status == 200 and shown.data[:4] == b"\x89PNG"
    assert h.get("GET", f"/api/ais/files/{sha}/slice/99.png", session=ann).status == 422
    assert h.get("GET", f"/api/ais/files/{sha}/slice/x.png", session=ann).status == 404


def test_the_stacks_file_can_not_be_downloaded_as_if_it_were_one(h):
    ann = h.user()
    sha = added(h, ann, randomize=False)["images"][0]["files"]["stack"]["sha"]
    assert h.get("GET", f"/api/ais/files/{sha}/file", session=ann).status == 404


def test_a_method_not_built_yet_is_refused_by_name(h):
    ann = h.user()
    sha = added(h, ann, randomize=False)["images"][0]["files"]["stack"]["sha"]
    refused = post(h, "/api/ais/trace", ann, processed=sha, z_method="volume_trace", **CLICK)
    assert refused.status == 400 and b"Full 3D tracing is not built yet" in refused.data
    assert post(h, "/api/ais/detect", ann, processed=sha, z_method="nope").status == 400


def test_an_ordinary_image_answers_as_it_always_did(h):
    ann = h.user()
    sha = h.library.add(_tiff_bytes(synthetic()[0]))["sha256"]
    answer = json.loads(post(h, "/api/ais/trace", ann, processed=sha, **CLICK).data)
    assert answer["ok"] and "z" not in answer


def test_someone_who_is_not_an_admin_sees_no_name_of_a_blinded_stack(h):
    ann = h.user()
    admin = h.user("Boss", role=users.ROLE_ADMIN)
    batch = post(h, "/api/ais/batches", ann, name="z").data
    batch_id = json.loads(batch)["id"]
    response = post(h, f"/api/ais/batches/{batch_id}/upload", ann, files=manifest(h), stack=STACK, add_name="Slide7_27")
    assert response.status == 200, response.data
    for path in (f"/api/ais/batches/{batch_id}", "/api/ais/batches", f"/api/ais/batches/{batch_id}/status"):
        text = h.get("GET", path, session=ann).data.decode()
        assert "Slide7" not in text and "IP-04" not in text, path

    as_admin = json.loads(h.get("GET", f"/api/ais/batches/{batch_id}", session=admin).data)
    image = as_admin["images"][0]
    assert image["original_dir"] == "Slide7_27" and image["original_cell"] == "IP-04"
    assert as_admin["adds"][0]["original_name"] == "Slide7_27"
    assert image["files"]["stack"]["slices"][0]["name"].startswith("IP-04_z01")


def test_a_blinded_stacks_slices_keep_what_an_upload_needs(h):
    ann = h.user()
    file = added(h, ann)["images"][0]["files"]["stack"]
    assert set(file["slices"][0]) == {"z", "sha", "size", "stored"}
    assert "original" not in file


def test_a_backup_lists_the_slices_it_holds_not_the_stack(h):
    admin = h.user("Boss", role=users.ROLE_ADMIN)
    batch = added(h, admin)
    backup = json.loads(h.get("GET", f"/api/ais/batches/{batch['id']}/backup", session=admin).data)
    file = batch["images"][0]["files"]["stack"]
    assert sorted(backup["stored"]) == sorted(part["sha"] for part in file["slices"])


def test_a_manifest_larger_than_the_default_limit_is_taken(h):
    ann = h.user()
    files = manifest(h)
    filler = [{"name": f"x{i}.tif", "rel": f"root/{'y' * 200}/x{i}.tif", "sha": f"{i:064x}", "size": 1} for i in range(4900)]
    assert len(json.dumps(files + filler)) > h.cfg.body_limit_bytes
    assert post(h, "/api/ais/batches/upload", ann, name="z", files=files + filler, stack=STACK).status == 200


def test_the_settings_list_follows_the_methods():
    text = (ROOT / "static" / "js" / "settings.js").read_text()
    language = yaml.safe_load((ROOT / "config" / "language.yaml").read_text())["settings"]
    for method in zlength.METHODS:
        assert f'{{ id: "{method.id}" , ready: {str(method.ready).lower()} }}' in text
        assert language[f"z_method_{method.id}"] == method.label


def test_the_page_finds_slices_as_the_server_does():
    pattern = zstack.SLICE_RE.pattern.replace("\\Z", "$")
    assert f"stackRe: /{pattern}/i," in (ROOT / "static" / "js" / "ais.js").read_text()


def test_the_channels_dialog_shows_and_corrects_a_stack_s_calibration(h):
    ann = h.user()
    batch = added(h, ann, randomize=False)
    path = f"/api/ais/batches/{batch['id']}/layouts"
    shown = json.loads(h.get("GET", path, session=ann).data)
    assert shown["stacks"] == {"count": 1, "z_step_um": STACK["z_step_um"], "pixel_um": STACK["pixel_um"], "mixed": False}
    saved = post(h, path, ann, channels=[], stack={"z_step_um": 0.25, "pixel_um": 0.2})
    assert saved.status == 200, saved.data
    out = json.loads(saved.data)
    image = out["batch"]["images"][0]
    assert out["changed"] == [image["key"]] and image["z_stack"]["z_step_um"] == 0.25
    # A trace on the corrected stack is measured with the new step.
    traced = json.loads(post(h, "/api/ais/trace", ann, processed=image["files"]["stack"]["sha"], **CLICK).data)
    assert traced["ok"] and traced["z"]["z_step_um"] == 0.25
    assert post(h, path, ann, channels=[], stack={"z_step_um": -1, "pixel_um": 0.2}).status == 400


def _saved_without_area(h, who, batch, image, answer, **change):
    """answer saved as a row from before area and volume were measured, its
    clicks, threshold and settings kept as the browser keeps them."""
    m = answer["measures"]
    row = {"length_um": m["length_um"], "pixels": answer["pixels"], "click_x": answer["clicks"][0][0],
           "click_y": answer["clicks"][0][1], "click2_x": answer["clicks"][-1][0], "click2_y": answer["clicks"][-1][1],
           "threshold_initial": answer["threshold_initial"], "threshold": answer["threshold"]}
    row |= {k: answer["settings"][k] for k in ("smooth", "pixconv", "f", "kernel", "sigma", "strel", "min_pixels",
                                                 "max_path", "max_passes", "spline_p", "window_um")}
    row |= {k: v for k, v in answer["z"].items() if not k.startswith("volume")} | change
    response = post(h, "/api/ais/results", who, batch_id=batch["id"], image=image["key"], row=row)
    assert response.status == 200, response.data
    return json.loads(response.data)


def test_ais_saved_before_areas_get_them_filled_in(h):
    ann = h.user()
    batch = added(h, ann, randomize=False)
    image = batch["images"][0]
    answer = json.loads(post(h, "/api/ais/trace", ann, processed=image["files"]["stack"]["sha"], **CLICK).data)
    good = _saved_without_area(h, ann, batch, image, answer)
    moved = _saved_without_area(h, ann, batch, image, answer, pixels=answer["pixels"][1:], z_path=answer["z"]["z_path"][1:])
    path = f"/api/ais/batches/{batch['id']}/fill-areas"
    out = json.loads(post(h, path, ann, limit=1).data)
    assert (out["filled"], out["failed"], out["after"], out["remaining"]) == (1, [], good["id"], 1)
    out = json.loads(post(h, path, ann, after=out["after"]).data)
    assert (out["filled"], out["failed"], out["remaining"]) == (0, [moved["id"]], 0)   # traced again, it isn't the same
    rows = {r["id"]: r for r in ais.list_results(h.store, batch["id"])}
    filled = rows[good["id"]]
    assert filled["area_blob_um2"] == answer["shape"]["area_blob_um2"]
    assert filled["area_width_um2"] == answer["shape"]["area_width_um2"]
    assert filled["volume_voxel_um3"] == answer["z"]["volume_voxel_um3"] and filled["volume_tube_um3"] > 0
    assert filled["length_um"] == good["length_um"] and "edited_at" not in filled   # nothing else changed
    assert rows[moved["id"]]["area_blob_um2"] is None
    assert post(h, path, ann, limit=0).status == 400
