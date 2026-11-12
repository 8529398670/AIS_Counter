"""The Measure tool's first guess (app/analysis/pairing.py): the AIS's
thicker end as its start, and the soma in front of it over a nearer one
beside or behind it."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from app.analysis import pairing
from app.analysis.pairing import SomaShape
from app.analysis.soma import Bodies
from tests.test_matlab_routes import Harness
from tests.test_service import _tiff_bytes

PX = 0.2   # um per pixel
SMALL = SomaShape(min_um=1)   # the hand-made discs here are small somata
ROW = 100  # the AIS runs along this 1-based y


def tapered(x0=50, x1=200, wide=4.0, narrow=1.5, shape=(200, 300)) -> np.ndarray:
    """A bright horizontal AIS from x0 to x1 (1-based), its Gaussian width
    going from wide (px sigma) at x0 to narrow at x1, on a dim background."""
    H, W = shape
    yy, xx = np.mgrid[1:H + 1, 1:W + 1].astype(np.float64)
    frac = np.clip((xx - x0) / (x1 - x0), 0, 1)
    sigma = wide + (narrow - wide) * frac
    inside = (xx >= x0) & (xx <= x1)
    return (100 + 1000 * inside * np.exp(-((yy - ROW) ** 2) / (2 * sigma ** 2))).astype(np.uint16)


def trace(x0=50, x1=200) -> list[list[int]]:
    return [[x, ROW] for x in range(x0, x1 + 1)]


def circle(cx: float, cy: float, r: float) -> list[list[int]]:
    """A soma outline: the 1-based [x, y] pixels of a circle."""
    out = {(int(round(cx + r * math.cos(t))), int(round(cy + r * math.sin(t)))) for t in np.linspace(0, 2 * math.pi, 720)}
    return [list(p) for p in sorted(out)]


def test_the_wide_end_measures_wider():
    first, last = pairing.end_widths(pairing.smoothed(tapered()), trace(), PX)
    assert first > 1.3 * last
    # FWHM of a Gaussian is 2.355 sigma: about 1.8 um at the wide end
    assert 1.2 < first < 2.4


def test_the_thicker_end_is_the_start_whichever_way_the_trace_runs():
    smooth = pairing.smoothed(tapered())
    forward, backward = pairing.pair_image(smooth, None, [trace(), trace()[::-1]], PX)["pairs"]
    assert (forward["end"], forward["by"]) == ("first", "width")
    assert (backward["end"], backward["by"]) == ("last", "width")
    assert forward["a"] == backward["a"] == [50, ROW]
    assert forward["b"] is None and not forward["confident"]   # no somata, nothing to be sure of


def test_the_soma_in_front_beats_a_nearer_one_beside():
    ahead = circle(160, 100, 20)        # nearest point (140, 100): 8 um straight ahead
    beside = circle(100, 55, 20)        # nearest point (100, 75): 5 um, at 90 degrees
    best = pairing.best_soma([beside, ahead], [100, 100], np.array([1.0, 0.0]), PX)
    assert best["soma"] == 1 and best["b"] == [140, 100]
    assert best["gap_um"] == pytest.approx(8.0) and best["angle_deg"] == pytest.approx(0.0, abs=1)
    # with no direction, the nearest wins, as the hint did before
    assert pairing.best_soma([beside, ahead], [100, 100], None, PX)["soma"] == 0


def test_the_soma_in_front_beats_a_nearer_one_behind():
    ahead = circle(145, 100, 20)        # 5 um ahead
    behind = circle(60, 100, 20)        # 4 um behind
    assert pairing.best_soma([behind, ahead], [100, 100], np.array([1.0, 0.0]), PX)["soma"] == 1


def test_a_soma_touching_the_start_counts_whatever_its_angle():
    touching = circle(100, 96, 1)       # under 1 um off, but "behind"
    far = circle(200, 100, 10)
    assert pairing.best_soma([far, touching], [100, 100], np.array([-1.0, 0.0]), PX)["soma"] == 1


def test_outward_points_out_of_the_end():
    assert pairing.outward(trace(), "first", PX).tolist() == [-1.0, 0.0]
    assert pairing.outward(trace(), "last", PX).tolist() == [1.0, 0.0]
    assert pairing.outward([[5, 5]], "first", PX) is None


def discs(*circles, shape=(200, 300)) -> Bodies:
    """Bodies by hand: a filled disc per (cx, cy, r), 1-based, hotspot at its
    centre, at full size (step 1)."""
    H, W = shape
    yy, xx = np.mgrid[1:H + 1, 1:W + 1]
    labels = np.zeros(shape, np.int32)
    for k, (cx, cy, r) in enumerate(circles, 1):
        labels[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = k
    return Bodies(labels, [[float(cx), float(cy)] for cx, cy, _ in circles], 1)


def test_a_clear_width_winner_facing_its_soma_is_confident():
    smooth = pairing.smoothed(tapered())
    out = pairing.pair_image(smooth, discs((20, ROW, 15), (250, 30, 15)), [trace()], PX, SMALL)
    p = out["pairs"][0]
    assert (p["end"], p["by"], p["body"]) == ("first", "width", 0)
    assert p["b"] == pytest.approx([35, ROW], abs=1.5)     # the disc's edge facing the AIS
    assert p["gap_um"] == pytest.approx(3.0, abs=0.3)
    assert p["confident"]
    assert p["other"]["end"] == "last" and p["other"]["b"] is not None
    assert out["bodies"][0]["ais"] == 0 and out["bodies"][1]["ais"] is None
    json.dumps(out)   # JSON-safe


def test_ends_alike_fall_back_to_the_soma_in_front():
    smooth = pairing.smoothed(tapered(wide=2.0, narrow=2.0))
    p = pairing.pair_image(smooth, discs((230, ROW, 15)), [trace()], PX, SMALL)["pairs"][0]
    assert (p["end"], p["by"]) == ("last", "soma")
    assert p["b"] == pytest.approx([215, ROW], abs=1.5)
    assert not p["confident"]


def test_a_dot_is_left_on_its_one_pixel():
    p = pairing.pair_image(pairing.smoothed(tapered()), discs((20, ROW, 15)), [[[60, ROW]]], PX, SMALL)["pairs"][0]
    assert p["end"] == "first" and p["a"] == [60, ROW] and p["widths"] == [None, None]


def oval(a=40, b=15, deg=30, centre=(100, 100), shape=(200, 200)):
    """Bodies holding one elliptical piece, its hotspot off-centre."""
    H, W = shape
    yy, xx = np.mgrid[1:H + 1, 1:W + 1].astype(np.float64)
    th = math.radians(deg)
    u = (xx - centre[0]) * math.cos(th) + (yy - centre[1]) * math.sin(th)
    v = -(xx - centre[0]) * math.sin(th) + (yy - centre[1]) * math.cos(th)
    labels = ((u / a) ** 2 + (v / b) ** 2 <= 1).astype(np.int32)
    return Bodies(labels, [[centre[0] + 20 * math.cos(th), centre[1] + 20 * math.sin(th)]], 1), labels


def inside(labels, e, n=180):
    """e lies in the piece, give or take its border pixel."""
    t = np.linspace(0, 2 * math.pi, n)
    th = math.radians(e["angle_deg"])
    a, b = e["a"] - 1, e["b"] - 1
    ex = e["cx"] + a * np.cos(t) * math.cos(th) - b * np.sin(t) * math.sin(th)
    ey = e["cy"] + a * np.cos(t) * math.sin(th) + b * np.sin(t) * math.cos(th)
    return bool(labels[np.round(ey).astype(int) - 1, np.round(ex).astype(int) - 1].all())


def test_the_ellipse_is_the_largest_inside_its_piece():
    bodies, labels = oval()
    e = pairing.fit_ellipse(bodies, 0, SomaShape(min_um=0, max_um=200, roundness=0.2), PX)
    assert inside(labels, e)
    assert e["angle_deg"] % 180 == pytest.approx(30, abs=4)
    assert e["cx"] == pytest.approx(100, abs=2) and e["cy"] == pytest.approx(100, abs=2)   # not the hotspot
    assert e["a"] * e["b"] > 0.85 * 40 * 15                                            # most of the piece


def test_a_round_soma_is_a_circle_and_the_size_limits_hold():
    bodies, labels = oval()
    circle = pairing.fit_ellipse(bodies, 0, SomaShape(min_um=0, max_um=200, roundness=1), PX)
    assert circle["a"] == pytest.approx(circle["b"]) and circle["a"] == pytest.approx(15, abs=1.5)
    assert inside(labels, circle)
    capped = pairing.fit_ellipse(bodies, 0, SomaShape(min_um=0, max_um=10, roundness=0.2), PX)
    assert 2 * capped["a"] * PX <= 10 + 1e-9
    assert pairing.fit_ellipse(bodies, 0, SomaShape(min_um=20, max_um=40, roundness=0.2), PX) is None   # 16 um long


def test_b_is_where_the_line_from_the_hotspot_meets_the_ellipse():
    e = {"cx": 100.0, "cy": 100.0, "a": 10.0, "b": 10.0, "angle_deg": 0.0}
    b, gap = pairing.ray_hit(e, [130, 100], PX)
    assert b == [110.0, 100.0] and gap == pytest.approx(20 * PX)
    b, gap = pairing.ray_hit(e, [100, 70], PX)
    assert b == pytest.approx([100.0, 90.0]) and gap == pytest.approx(20 * PX)
    assert pairing.ray_hit(e, [105, 100], PX)[1] == 0   # starts inside the soma
    long = {"cx": 0.0, "cy": 0.0, "a": 20.0, "b": 5.0, "angle_deg": 90.0}
    assert pairing.ray_hit(long, [0, 50], PX)[0] == pytest.approx([0.0, 20.0])


def test_a_soma_knows_its_most_prominent_ais():
    H, W = 300, 300
    img = np.full((H, W), 100.0)
    img[149:152, 175:260] = 1200     # bright AIS to the right of the soma
    img[175:260, 149:152] = 400      # dim AIS below it
    smooth = pairing.smoothed(img)
    right = [[x, 151] for x in range(176, 260)]
    below = [[151, y] for y in range(176, 260)]
    out = pairing.pair_image(smooth, discs((151, 151, 18), shape=(H, W)), [below, right], PX, SMALL)
    assert out["bodies"][0]["ais"] == 1
    assert [p["body"] for p in out["pairs"]] == [0, 0]


# --- the route ---------------------------------------------------------------

@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_the_route_guesses_each_trace(h):
    who = h.user()
    sha = h.library.add(_tiff_bytes(tapered()))["sha256"]
    body = {"pixel_um": PX, "traces": [{"id": "id:1", "pixels": trace()}, {"id": "id:2", "pixels": trace()[::-1]}]}
    response = h.get("POST", f"/api/ais/files/{sha}/pair", session=who, body=body)
    assert response.status == 200, response.data
    out = json.loads(response.data)
    assert [(p["id"], p["end"]) for p in out["pairs"]] == [("id:1", "first"), ("id:2", "last")]
    assert all(p["b"] is None for p in out["pairs"]) and out["bodies"] == []   # a plain TIFF has no soma channel
    response = h.get("POST", f"/api/ais/files/{sha}/pair", session=who, body={"pixel_um": PX, "traces": [], "split": False})
    assert response.status == 200 and json.loads(response.data) == {"pairs": [], "bodies": []}


def test_the_route_refuses_bad_bodies_and_unknown_files(h):
    who = h.user()
    sha = h.library.add(_tiff_bytes(tapered()))["sha256"]
    path = f"/api/ais/files/{sha}/pair"
    assert h.get("POST", path, session=who, body={"pixel_um": 0, "traces": []}).status == 400
    assert h.get("POST", path, session=who, body={"pixel_um": PX, "traces": [{"pixels": [[0, 1]]}]}).status == 400
    assert h.get("POST", path, session=who, body={"pixel_um": PX, "traces": [{"pixels": []}]}).status == 400
    assert h.get("POST", path, session=who, body={"pixel_um": PX, "traces": [], "split": "yes"}).status == 400
    missing = "0" * 64
    assert h.get("POST", f"/api/ais/files/{missing}/pair", session=who,
                 body={"pixel_um": PX, "traces": [{"pixels": trace()}]}).status == 404
