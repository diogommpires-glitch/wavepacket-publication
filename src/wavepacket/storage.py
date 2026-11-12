"""Explicit artifact roots and OS-backed process ownership."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

import psutil
from filelock import FileLock, Timeout


class RunBusy(RuntimeError):
    """A live process owns this artifact destination."""


@dataclass(frozen=True)
class StoragePaths:
    data_dir: Path
    runs: Path
    evidence: Path

    @classmethod
    def resolve(
        cls,
        data_dir: str | Path | None = None,
        *,
        runs_root: Path | None = None,
        evidence_dir: Path | None = None,
    ) -> StoragePaths:
        base = Path(data_dir or Path.cwd()).expanduser().resolve()
        return cls(
            base,
            Path(runs_root).expanduser().resolve() if runs_root is not None else base / "runs",
            Path(evidence_dir).expanduser().resolve()
            if evidence_dir is not None
            else base / "results" / "validation",
        )

    def evidence_snapshot(self, suite: str) -> tuple[Path, bytes] | None:
        for path in (self.evidence / suite / "validation.json", self.evidence / "validation.json"):
            try:
                content = path.read_bytes()
                report = json.loads(content)
            except (OSError, ValueError):
                continue
            if isinstance(report, dict) and report.get("suite") == suite:
                return path, content
        return None


def process_identity() -> dict:
    process = psutil.Process()
    return {
        "pid": os.getpid(),
        "create_time": process.create_time(),
        "hostname": socket.gethostname(),
    }


def owner_alive(owner: dict | None) -> bool | None:
    if not owner or owner.get("hostname") != socket.gethostname():
        return None
    try:
        process = psutil.Process(int(owner["pid"]))
        return (
            abs(process.create_time() - float(owner["create_time"])) < 0.01 and process.is_running()
        )
    except (psutil.NoSuchProcess, KeyError, TypeError, ValueError, OverflowError):
        return False
    except psutil.AccessDenied:
        return None


def acquire_lock(root: Path, name: str) -> FileLock:
    root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(root / name, timeout=0, thread_local=False)
    try:
        lock.acquire()
    except Timeout as exc:
        raise RunBusy(
            f"Another process owns {root} ({name}); use its running lab or a different output root"
        ) from exc
    return lock
