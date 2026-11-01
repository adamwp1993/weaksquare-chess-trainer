"""ARCHITECTURE §3 decision 7 and NFR-6: jobs report progress, can be cancelled, and stop on shutdown."""

from __future__ import annotations

import threading

from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, JobStatus, ProgressFn


class Recorder:
    def __init__(self) -> None:
        self.events: list[JobStatus] = []

    def job_changed(self, status: JobStatus) -> None:
        self.events.append(status)


def test_done_job_reports_progress_and_finishes() -> None:
    rec = Recorder()
    runner = JobRunner(rec)
    runner.PROGRESS_INTERVAL_S = 0

    def work(progress: ProgressFn, token: CancelToken) -> None:
        for i in range(3):
            progress(i / 3, f"step {i}")

    job = runner.submit("demo", work)
    status = runner.wait(job, 5)
    assert status is not None and status.state == "done" and status.progress == 1.0
    assert [e.message for e in rec.events][:3] == ["step 0", "step 1", "step 2"]


def test_cancel_stops_a_running_job() -> None:
    started = threading.Event()
    runner = JobRunner()

    def work(progress: ProgressFn, token: CancelToken) -> None:
        started.set()
        while True:
            token.raise_if_cancelled()
            threading.Event().wait(0.01)

    job = runner.submit("loop", work)
    started.wait(5)
    assert runner.cancel(job)
    status = runner.wait(job, 5)
    assert status is not None and status.state == "cancelled"
    assert not runner.cancel(job)  # already finished


def test_failures_keep_code_and_hide_internals() -> None:
    runner = JobRunner()

    def fails(progress: ProgressFn, token: CancelToken) -> None:
        raise JobFailed("download_failed", "The download failed.")

    def crashes(progress: ProgressFn, token: CancelToken) -> None:
        raise RuntimeError(r"C:\secret\path exploded")

    a = runner.wait(runner.submit("a", fails), 5)
    b = runner.wait(runner.submit("b", crashes), 5)
    assert a is not None and (a.state, a.error_code, a.message) == ("failed", "download_failed", "The download failed.")
    assert b is not None and b.state == "failed" and b.error_code == "internal"
    assert "secret" not in b.message


def test_cancel_all_stops_everything() -> None:
    runner = JobRunner()
    started = threading.Barrier(3)

    def work(progress: ProgressFn, token: CancelToken) -> None:
        started.wait(5)
        while not token.cancelled:
            threading.Event().wait(0.01)
        token.raise_if_cancelled()

    jobs = [runner.submit("w", work) for _ in range(2)]
    started.wait(5)
    runner.cancel_all(timeout=5)
    assert all((s := runner.status(j)) is not None and s.state == "cancelled" for j in jobs)
    assert runner.active() == []
