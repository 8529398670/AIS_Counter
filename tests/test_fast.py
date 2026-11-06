"""Settings' Method "ais_auto.m (fast)" (app/analysis/fast.py) must answer byte
for byte as the original does, on synthetic images and, where they are here,
on real ones."""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import ndimage as ndi

from app.analysis import ais_auto as aa
from app.analysis import detect as auto
from app.analysis import fast, preprocess
from app.analysis import soma as somata
from app.analysis.czi import read_czi
from app.analysis.images import tiff_bytes
from app.analysis.mlcompat import MatlabError
from app.analysis.service import run_click
from tests.test_matlab_routes import Harness

ROOT = Path(__file__).resolve().parents[1]
STARTS = ("both", "brighter", "dimmer", "fitted", "fitted2", "learned")


def same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def scene(seed: int = 3, H: int = 260, W: int = 340) -> np.ndarray:
    """Winding bright lines of different brightness, some running off the
    image's edges, one faint web that joins up only at a low threshold, a
    bright spot so most components re-threshold, and noise."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W))
    for k in range(14):
        p = rng.uniform((0, 0), (H, W))
        d = rng.normal(size=2)
        amp = rng.uniform(800, 9000)
        for _ in range(int(rng.uniform(40, 170))):
            d = d / np.linalg.norm(d) + rng.normal(0, .12, 2)
            p = p + d / np.linalg.norm(d)
            r, c = int(p[0]), int(p[1])
            if 0 <= r < H and 0 <= c < W:
                img[r, c] += amp
    img[H // 2, ::3] += 500
    img[::3, W // 3] += 500
    img = ndi.gaussian_filter(img, 1.3) * 6
    img[20:26, W - 30:W - 24] += 60000
    img += rng.normal(0, 25, img.shape)
    return np.clip(img, 0, 65535).astype(np.uint16)


def rod(H: int = 120, W: int = 160, row: int = 60, start: int = 0) -> np.ndarray:
    """A straight bright line reaching the image's left edge from start."""
    img = np.zeros((H, W))
    img[row - 2:row + 3, start:W - 40] = 8000
    img[10:14, W - 14:W - 10] = 60000
    return ndi.gaussian_filter(img, 1).astype(np.uint16)


@pytest.mark.parametrize("seed", [3, 4, 5])
@pytest.mark.parametrize("start", STARTS)
def test_detect_answers_as_the_original(seed, start):
    pic = scene(seed)
    prep = aa.PreparedImage.from_array(pic)
    assert same(auto.detect(prep, pic, 0.01, aa.DEFAULT, start), fast.detect(prep, pic, 0.01, aa.DEFAULT, start))


@pytest.mark.parametrize("start", ["both", "learned"])
def test_detect_with_otsu_and_with_accepted_traces(start):
    pic = scene(6)
    prep = aa.PreparedImage.from_array(pic)
    assert same(auto.detect(prep, pic, 0, aa.DEFAULT, start), fast.detect(prep, pic, 0, aa.DEFAULT, start))
    first = auto.detect(prep, pic, 0.01, aa.DEFAULT, start)["candidates"]
    exclude = [c["pixels"] for c in first[:2]]
    assert same(auto.detect(prep, pic, 0.01, aa.DEFAULT, start, exclude),
                fast.detect(prep, pic, 0.01, aa.DEFAULT, start, exclude))


@pytest.mark.parametrize("changed", [{"strel": 1}, {"strel": 4}, {"strel": 5}, {"min_pixels": 0}, {"min_pixels": 400},
                                     {"max_path": 40, "max_passes": 1}])
def test_detect_with_other_settings(changed):
    pic = scene(7)
    settings = aa.Settings.from_dict(changed)
    prep = aa.PreparedImage.from_array(pic, settings)
    assert same(auto.detect(prep, pic, 0.01, settings, "both"), fast.detect(prep, pic, 0.01, settings, "both"))


@pytest.mark.parametrize("pad", [0, 1, 3])
def test_a_window_that_has_to_grow_changes_nothing(monkeypatch, pad):
    pic = scene(8)
    prep = aa.PreparedImage.from_array(pic)
    monkeypatch.setattr(fast, "START_PAD", pad)
    stats: dict = {}
    assert same(auto.detect(prep, pic, 0.01, aa.DEFAULT, "both"), fast.detect(prep, pic, 0.01, aa.DEFAULT, "both", stats=stats))
    assert stats["windows"]


def clicks(pic: np.ndarray, n: int = 120):
    rng = np.random.default_rng(1)
    H, W = pic.shape
    bright = np.argsort(pic, axis=None)[-3000:]
    for i in range(n):
        if i % 2:
            k = int(rng.choice(bright))
            x, y = k % W + 1.0, k // W + 1.0
        else:
            x, y = float(rng.uniform(.6, W + .4)), float(rng.uniform(.6, H + .4))
        yield (x, y), ((min(x + 9, W), min(y + 5, H)) if i % 5 == 0 else None)


def test_clicks_answer_as_the_original_outline_and_all():
    pic = scene(9)
    prep = aa.PreparedImage.from_array(pic)
    for click, click2 in clicks(pic):
        assert same(run_click(prep, pic, click, click2, 0.01), fast.run_click(prep, pic, click, click2, 0.01))


def test_a_click_outside_or_on_nothing_fails_alike():
    pic = np.zeros((60, 80), np.uint16)
    prep = aa.PreparedImage.from_array(pic)
    assert same(run_click(prep, pic, (5.0, 5.0), None, 0.01), fast.run_click(prep, pic, (5.0, 5.0), None, 0.01))
    pic = scene(9)
    prep = aa.PreparedImage.from_array(pic)
    assert same(run_click(prep, pic, (-9.0, 5.0), None, 0.01), fast.run_click(prep, pic, (-9.0, 5.0), None, 0.01))


def test_a_skeleton_on_the_image_edge_fails_alike():
    pic = rod()
    prep = aa.PreparedImage.from_array(pic)
    original = run_click(prep, pic, (20.0, 60.0), None, 0.01)
    assert same(original, fast.run_click(prep, pic, (20.0, 60.0), None, 0.01))
    with pytest.raises(MatlabError, match="touches the image border"):
        aa.trace(prep, (20.0, 60.0))
    with pytest.raises(MatlabError, match="touches the image border"):
        fast.trace(prep, (20.0, 60.0))


def test_blobs_cut_by_each_edge_answer_alike():
    base = rod(start=30)
    for pic in (base, base[::-1].copy(), base.T.copy(), np.roll(base, 56, axis=0), np.roll(base, -56, axis=0)):
        prep = aa.PreparedImage.from_array(pic)
        assert same(auto.detect(prep, pic, 0.01, aa.DEFAULT, "both"), fast.detect(prep, pic, 0.01, aa.DEFAULT, "both"))


def test_a_click_a_window_cannot_settle_goes_through_the_whole_image():
    """Beside a component but on nothing at the new threshold: its nearest
    component there is the whole image's business."""
    pic = np.zeros((90, 120))
    pic[30:50, 30:34] = 2000     # dim, so the threshold rises above... the clicked one's peak
    pic[60:64, 60:100] = 9000
    pic[5:9, 100:104] = 60000
    pic = ndi.gaussian_filter(pic, 1).astype(np.uint16)
    prep = aa.PreparedImage.from_array(pic)
    cache: dict = {}
    for click, click2 in (((45.0, 40.0), None), ((44.0, 40.0), (70.0, 20.0)), ((32.0, 40.0), (90.0, 80.0))):
        assert same(run_click(prep, pic, click, click2, 0.01), fast.run_click(prep, pic, click, click2, 0.01, cache=cache))
    assert cache["stats"].get("whole")


def test_it_keeps_no_whole_image_per_re_threshold():
    pic = scene(3)
    prep = aa.PreparedImage.from_array(pic)
    cache: dict = {}
    for click, click2 in clicks(pic, 40):
        fast.run_click(prep, pic, click, click2, 0.01, cache=cache)
    assert sum(1 for k in cache if isinstance(k, tuple) and k[0] == "L") == 1


@pytest.mark.skipif(not (ROOT / "example-data" / "002-czi").exists(), reason="needs example-data/002-czi")
@pytest.mark.parametrize("start", ("soma", "fitted", "fitted2", "learned"))
def test_real_images_answer_as_the_original(start):
    path = sorted(glob.glob(str(ROOT / "example-data" / "002-czi" / "*.czi")))[0]
    image = read_czi(Path(path).read_bytes())
    raw = np.ascontiguousarray(image.as_tiff(image.ais_name))
    prep = aa.PreparedImage.from_array(preprocess.processed(raw))
    soma = somata.find(image.channel(image.soma_name), image.pixel_um or aa.DEFAULT.pixconv)
    assert same(auto.detect(prep, raw, 0.01, aa.DEFAULT, start, soma=soma),
                fast.detect(prep, raw, 0.01, aa.DEFAULT, start, soma=soma))


# --- the routes -----------------------------------------------------------------


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def posted(h, ada, path, body):
    answer = h.get("POST", path, session=ada, body=body)
    return answer.status, json.loads(answer.data)


def test_routes_take_the_engine_and_answer_alike(h):
    ada = h.user()
    sha = h.library.add(tiff_bytes(scene(3)))["sha256"]
    click = {"processed": sha, "click": [120.0, 120.0]}
    find = {"processed": sha, "start": "both"}
    assert posted(h, ada, "/api/ais/trace", click) == posted(h, ada, "/api/ais/trace", click | {"engine": "fast"})
    plain, quick = posted(h, ada, "/api/ais/detect", find), posted(h, ada, "/api/ais/detect", find | {"engine": "fast"})
    assert plain[0] == 200 and plain == quick


def test_no_engine_is_the_original_and_a_wrong_one_is_refused(h, monkeypatch):
    ada = h.user()
    sha = h.library.add(tiff_bytes(scene(3)))["sha256"]
    body = {"processed": sha, "start": "both"}
    for path, extra in (("/api/ais/detect", {}), ("/api/ais/trace", {"click": [120.0, 120.0]})):
        assert posted(h, ada, path, body | extra | {"engine": "turbo"})[0] == 400
    monkeypatch.setattr(fast, "detect", lambda *a, **k: pytest.fail("the original was asked for"))
    monkeypatch.setattr(fast, "run_click", lambda *a, **k: pytest.fail("the original was asked for"))
    assert posted(h, ada, "/api/ais/detect", body)[0] == 200
    assert posted(h, ada, "/api/ais/trace", body | {"click": [120.0, 120.0]})[0] == 200
