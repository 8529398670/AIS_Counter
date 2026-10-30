from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def probe():
    """MATLAB's primitive dump from tests/matlab/probe_primitives.m."""
    f = GOLDEN / "probe_primitives.mat"
    if not f.exists():
        pytest.skip("run scripts/parity.sh to generate MATLAB golden data")
    import scipy.io as sio
    return sio.loadmat(str(f))
