"""The full ais_auto port against every MATLAB golden click.

Golden sets come from scripts/parity.sh and need the local example-data/, so
this skips cleanly on a machine without them.
"""
from __future__ import annotations

import pytest

from tests import parity

JOBS = [job for name in parity.golden_sets() for job in parity.load_jobs(name)]


@pytest.mark.skipif(not JOBS, reason="no MATLAB golden data; run scripts/parity.sh")
@pytest.mark.parametrize("job", JOBS, ids=[j["id"] for j in JOBS])
def test_matches_matlab(job):
    stage, detail = parity.compare(job)
    assert stage == "ok", f"{stage}: {detail}"
