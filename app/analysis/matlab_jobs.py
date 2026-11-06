"""Runs on their way to someone's MATLAB helper (helper/, app/routes/ais_matlab.py).

The browser's request owns its job: it adds it, waits, and removes it however
the wait ends. So nothing outlives the answer the person was given, and a
helper that connects a minute later cannot open MATLAB for a run the browser
already reported as failed.

In memory on purpose, like the rate limiter: there is one uvicorn process, and
a run nobody picked up within seconds is not worth keeping across a restart.
Everything here runs on the event loop -- handlers call it directly, never
through run() -- which is why there is no lock.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from app.analysis.matlab import Run

# The helper polls every 3 s, so a few missed polls mean it has gone.
SEEN_SECONDS = 10


@dataclass
class Job:
    id: str
    user_id: int
    run: Run
    claimed: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    ok: bool = False
    message: str = ""


class Jobs:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._seen: dict[int, float] = {}
        self._jobs: dict[int, Job] = {}   # one per user: a second click must not open a second MATLAB

    def see(self, user_id: int) -> None:
        self._seen[user_id] = self.clock()

    def live(self, user_id: int) -> bool:
        seen = self._seen.get(user_id)
        return seen is not None and self.clock() - seen <= SEEN_SECONDS

    def add(self, user_id: int, run: Run) -> Job | None:
        """A new job, or None while this user already has one."""
        if user_id in self._jobs:
            return None
        job = Job(secrets.token_urlsafe(12), user_id, run)
        self._jobs[user_id] = job
        return job

    def claim(self, user_id: int) -> Job | None:
        """The user's job if no helper has taken it yet. With two helpers on
        one account it goes to whichever polls first."""
        job = self._jobs.get(user_id)
        if job is None or job.claimed.is_set():
            return None
        job.claimed.set()
        return job

    def get(self, user_id: int, job_id: str) -> Job | None:
        """A claimed job of this user's. Anything else is no such job, so an id
        says nothing to anyone else."""
        job = self._jobs.get(user_id)
        return job if job is not None and job.id == job_id and job.claimed.is_set() else None

    def finish(self, job: Job, ok: bool, message: str) -> None:
        job.ok, job.message = ok, message
        job.done.set()

    def remove(self, job: Job) -> None:
        if self._jobs.get(job.user_id) is job:
            del self._jobs[job.user_id]
