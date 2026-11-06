"""What the image must carry. A miss here only shows up at runtime, in Docker."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_image_gets_the_original_ais_auto():
    ignore = (ROOT / "docker" / "Dockerfile.dockerignore").read_text().splitlines()
    # The exception only works after the rule it excepts.
    assert ignore.index("!original-code/ais_auto.m") > ignore.index("original-code/")
    assert "COPY original-code/ais_auto.m ./original-code/" in (ROOT / "docker" / "Dockerfile").read_text()


def test_the_image_builds_the_helper_where_the_route_looks():
    from app.routes import ais_matlab
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text()
    assert ais_matlab.DIST == ROOT / "helper" / "dist"
    assert "COPY --from=helper /helper/dist ./helper/dist" in dockerfile
    assert "RUN sh build.sh" in dockerfile
    # The stage runs under alpine's sh: a bash script would not start.
    assert (ROOT / "helper" / "build.sh").read_text().startswith("#!/bin/sh")


def test_the_helper_launches_what_the_zip_does():
    from app.analysis import matlab_bundle
    assert f'launchLine = "{matlab_bundle.LAUNCH}"' in (ROOT / "helper" / "matlab.go").read_text()
