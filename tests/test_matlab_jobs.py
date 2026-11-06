"""The queue between a browser and its MATLAB helper (app/analysis/matlab_jobs.py)."""
from __future__ import annotations

from app.analysis.matlab import Run
from app.analysis.ais_auto import Settings
from app.analysis.matlab_jobs import SEEN_SECONDS, Jobs

RUN = Run("replay", "p" * 64, None, "c", 0.01, [(1.0, 2.0)], Settings())


def test_a_helper_is_live_only_while_it_keeps_polling():
    now = [100.0]
    jobs = Jobs(clock=lambda: now[0])
    assert not jobs.live(1)
    jobs.see(1)
    assert jobs.live(1) and not jobs.live(2)
    now[0] += SEEN_SECONDS + 1
    assert not jobs.live(1)


def test_a_job_is_claimed_once_and_only_by_its_owner():
    jobs = Jobs()
    job = jobs.add(1, RUN)
    assert jobs.claim(2) is None
    assert jobs.claim(1) is job and job.claimed.is_set()
    assert jobs.claim(1) is None


def test_one_pending_job_per_user():
    jobs = Jobs()
    job = jobs.add(1, RUN)
    assert jobs.add(1, RUN) is None and jobs.add(2, RUN) is not None
    jobs.remove(job)
    assert jobs.add(1, RUN) is not None


def test_get_needs_the_owner_the_id_and_a_claim():
    jobs = Jobs()
    job = jobs.add(1, RUN)
    assert jobs.get(1, job.id) is None   # not claimed yet
    jobs.claim(1)
    assert jobs.get(1, job.id) is job
    assert jobs.get(2, job.id) is None and jobs.get(1, "other") is None


def test_a_removed_job_cannot_be_picked_up_late():
    jobs = Jobs()
    job = jobs.add(1, RUN)
    jobs.remove(job)
    assert jobs.claim(1) is None and jobs.get(1, job.id) is None
    jobs.remove(job)   # twice is harmless
