"""Loopback API with explicit storage and OS-backed run ownership."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import h5py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import SimulationConfig
from .contracts import (
    ACTIVE_STATUSES,
    Frame,
    Measurements,
    PresetRecord,
    RunRecord,
    UnitScalesRecord,
    ValidationReport,
)
from .runner import (
    ARTIFACTS,
    MAX_PREVIEW_BYTES,
    enforce_resources,
    estimate_resources,
    json_safe,
    read_frame,
    read_observables,
    read_record,
    run_simulation,
    timestamp,
    write_json,
)
from .storage import RunBusy, StoragePaths, acquire_lock, owner_alive
from .units import electron_scales


def _publish_preview(path: Path, update: dict) -> str | None:
    if "frame" not in update:
        return None
    encoded = json.dumps(update["frame"], allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_PREVIEW_BYTES:
        raise ValueError(f"Preview exceeds its {MAX_PREVIEW_BYTES}-byte disposable allocation")
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_bytes(encoded)
        temporary.replace(path)
    except OSError as error:
        warning = f"Live preview publication failed ({type(error).__name__}: {error}); scientific output continues."
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_error:
            warning += f" Preview temporary-file cleanup failed: {cleanup_error}"
        return warning
    return None


def _worker(config: dict, root: str, run_id: str, event, admission) -> None:
    accepted = False

    def acknowledge(record):
        nonlocal accepted
        admission.send({"status": "admitted", "run_id": record["id"]})
        accepted = True
        admission.close()

    def notify(update):
        return _publish_preview(Path(root) / run_id / "preview.json", update)

    try:
        run_simulation(
            config,
            root,
            run_id=run_id,
            progress=notify,
            cancelled=event.is_set,
            admitted=acknowledge,
        )
    except RunBusy as exc:
        if not accepted:
            admission.send({"status": "busy", "error": str(exc)})
    except Exception as exc:
        if not accepted:
            admission.send({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        admission.close()


class RunSupervisor:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.context = mp.get_context("spawn")
        self.process: Any = None
        self.event: Any = None
        self.active_id: str | None = None
        self.previews: dict[str, dict] = {}
        self.records: dict[str, dict] = {}
        self.storage_warnings: dict[str, str] = {}
        self.lock = threading.RLock()
        self.server_lease: Any = None
        self.refresh()

    def open(self):
        if self.server_lease is None:
            self.server_lease = acquire_lock(self.root, ".server.lock")
        self.refresh()

    def folder(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise HTTPException(404, "Unknown run")
        return self.root / run_id

    def _recover_exited_worker(self, folder: Path, error: str) -> dict:
        warning_key = f"{folder.name}:recovery"
        try:
            lease = acquire_lock(self.root, ".writer.lock")
        except RunBusy:
            record = read_record(folder)
            if record["status"] in ACTIVE_STATUSES:
                self.storage_warnings[warning_key] = (
                    "Worker recovery deferred while a writer owns the output root."
                )
            else:
                self.storage_warnings.pop(warning_key, None)
            return record
        try:
            # The worker can commit its terminal record between a snapshot and
            # a liveness check. Recovery must use a fresh snapshot under the lease.
            record = read_record(folder)
            if record["status"] in ACTIVE_STATUSES and owner_alive(record.get("owner")) is False:
                record.update(status="failed", error=error, finished_at=timestamp())
                if record.get("scientific_status", "running") in ("pending", "running"):
                    record["scientific_status"] = "incomplete"
                if record.get("report_status") != "completed":
                    record["report_status"] = "incomplete"
                write_json(folder / "record.json", record)
            self.storage_warnings.pop(warning_key, None)
            return record
        finally:
            lease.release()

    def refresh(self) -> None:
        with self.lock:
            if self.active_id:
                warning_key = f"{self.active_id}:preview"
                try:
                    with (self.folder(self.active_id) / "preview.json").open("rb") as source:
                        content = source.read(MAX_PREVIEW_BYTES + 1)
                    if len(content) > MAX_PREVIEW_BYTES:
                        raise ValueError("Disposable preview exceeds its bounded allocation")
                    frame = json_safe(Frame.model_validate_json(content).model_dump(mode="json"))
                    if frame["run_id"] != self.active_id:
                        raise ValueError("Disposable preview belongs to a different run")
                    self.previews[self.active_id] = frame
                    self.storage_warnings.pop(warning_key, None)
                except FileNotFoundError:
                    pass  # A newly admitted worker need not have published its first preview yet.
                except (OSError, ValueError) as error:
                    self.storage_warnings[warning_key] = f"Live preview unavailable: {error}"
            disk_ids = set()
            for path in self.root.glob("*/record.json"):
                try:
                    record = read_record(path.parent)
                    alive = owner_alive(record.get("owner"))
                    if (
                        record["status"] in ACTIVE_STATUSES
                        and alive is False
                        and self.server_lease is not None
                    ):
                        record = self._recover_exited_worker(
                            path.parent,
                            "Recorded worker is no longer alive; output is incomplete.",
                        )
                        alive = owner_alive(record.get("owner"))
                except (OSError, ValueError, KeyError) as exc:
                    self.storage_warnings[path.parent.name] = str(exc)
                    self.records.pop(path.parent.name, None)
                    continue
                disk_ids.add(record["id"])
                self.storage_warnings.pop(path.parent.name, None)
                if record["status"] in ACTIVE_STATUSES and alive is None:
                    record["owner_status"] = "unknown; no automatic takeover"
                self.records[record["id"]] = record
            for run_id in set(self.records) - disk_ids:
                if run_id != self.active_id:
                    del self.records[run_id]
            if self.process is not None and not self.process.is_alive():
                self.process.join(timeout=0)
                owned_id = self.active_id
                self.active_id, self.process = None, None
                self.event = None
                if owned_id:
                    try:
                        owned_record = self._recover_exited_worker(
                            self.folder(owned_id),
                            "Owned worker exited before canonical completion.",
                        )
                    except (OSError, ValueError, KeyError) as exc:
                        self.storage_warnings[owned_id] = (
                            f"Owned worker exited with an unavailable canonical record; output is incomplete: {exc}"
                        )
                        self.records.pop(owned_id, None)
                        return
                    self.storage_warnings.pop(owned_id, None)
                    self.records[owned_id] = owned_record
            for record in self.records.values():
                frame = self.previews.get(record["id"])
                if record["status"] != "running" or frame is None:
                    continue
                warning_key = f"{record['id']}:preview_progress"
                step, total_steps = frame["step"], frame["total_steps"]
                if frame["run_id"] == record["id"] and total_steps > 0 and 0 <= step <= total_steps:
                    record["progress"] = step / total_steps
                    self.storage_warnings.pop(warning_key, None)
                else:
                    self.storage_warnings[warning_key] = (
                        "Live preview has invalid progress metadata; canonical progress retained."
                    )

    def _startup_failed(self, record: dict, error: str):
        if self.event is not None:
            self.event.set()
        if self.process is not None and self.process.is_alive():
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=3)
        path = self.folder(record["id"]) / "record.json"
        if path.exists():
            stored = read_record(path.parent)
            if stored["status"] == "failed":
                record = stored
        record.update(status="failed", error=error, finished_at=timestamp())
        write_json(path, record)
        self.records[record["id"]] = record
        self.active_id, self.process = None, None
        self.event = None

    def start(self, config: SimulationConfig) -> dict:
        with self.lock:
            self.open()
            ndim = len(config.grid.points)
            if any(n > (32768 if ndim == 1 else 512) for n in config.grid.points):
                raise ValueError(
                    "Interactive grid limit is 32768 in 1D or 512 per axis in 2D; use the CLI for larger studies"
                )
            resources = enforce_resources(config)
            if (
                resources["steps"] > 200000
                or resources["snapshots"] > 128
                or resources["estimated_total_output_bytes"] > 1073741824
            ):
                raise ValueError(
                    "Interactive run exceeds steps, snapshots or the total 1 GiB output allocation"
                )
            if self.active_id:
                raise RunBusy(f"A numerical run is already active: {self.active_id}")
            run_id = uuid.uuid4().hex
            record = {
                "schema_version": 2,
                "id": run_id,
                "status": "queued",
                "progress": 0.0,
                "config": config.model_dump(mode="json"),
                "created_at": timestamp(),
                "resources": resources,
                "warnings": [],
                "scientific_status": "pending",
                "report_status": "pending",
            }
            self.records[run_id] = record
            self.previews.clear()
            self.active_id = run_id
            receive = send = None
            try:
                self.event = self.context.Event()
                receive, send = self.context.Pipe(duplex=False)
                self.process = self.context.Process(
                    target=_worker,
                    args=(
                        record["config"],
                        str(self.root),
                        run_id,
                        self.event,
                        send,
                    ),
                    daemon=True,
                )
                self.process.start()
                send.close()
                if not receive.poll(15):
                    raise TimeoutError("Worker admission timed out before durable ownership")
                result = receive.recv()
                if result["status"] == "busy":
                    self._startup_failed(record, result["error"])
                    raise RunBusy(result["error"])
                if result["status"] != "admitted":
                    raise RuntimeError(result["error"])
                if result.get("run_id") != run_id:
                    raise RuntimeError("Worker admission identity does not match the requested run")
                self.records[run_id] = read_record(self.folder(run_id))
                return self.records[run_id]
            except RunBusy:
                raise
            except (OSError, EOFError, RuntimeError, TimeoutError) as exc:
                self._startup_failed(record, f"Worker startup failed: {exc}")
                raise
            finally:
                if receive is not None:
                    receive.close()
                if send is not None:
                    send.close()

    def get(self, run_id: str) -> dict:
        self.folder(run_id)
        self.refresh()
        if run_id not in self.records:
            if run_id in self.storage_warnings:
                raise HTTPException(503, f"Run record unavailable: {self.storage_warnings[run_id]}")
            raise HTTPException(404, "Unknown run")
        return self.records[run_id]

    def close(self):
        if self.process is not None:
            if self.event is not None:
                self.event.set()
            self.process.join(timeout=8)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=3)
            self.refresh()
        if self.server_lease is not None:
            self.server_lease.release()
            self.server_lease = None


# The v1 Python name has existing callers; wire contracts use RunRecord instead.
RunManager = RunSupervisor


def create_app(
    runs_root: Path | None = None, *, data_dir: Path | None = None, evidence_dir: Path | None = None
) -> FastAPI:
    paths = StoragePaths.resolve(data_dir, runs_root=runs_root, evidence_dir=evidence_dir)
    supervisor = RunSupervisor(paths.runs)

    @asynccontextmanager
    async def lifespan(app):
        supervisor.open()
        try:
            yield
        finally:
            supervisor.close()

    app = FastAPI(title="Wavepacket", version=__version__, lifespan=lifespan)
    app.state.manager = supervisor
    app.state.supervisor = supervisor
    app.state.storage = paths
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"], www_redirect=False
    )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "application": "Wavepacket",
            "version": __version__,
            "storage_warnings": supervisor.storage_warnings,
        }

    @app.get("/api/storage")
    def storage():
        return {
            "data_dir": str(paths.data_dir),
            "runs": str(paths.runs),
            "evidence": str(paths.evidence),
        }

    @app.get("/api/presets", response_model=list[PresetRecord])
    def presets():
        from .experiments import list_experiments

        result = list_experiments()
        for item in result:
            item.setdefault("name", item.get("title", item["id"]))
            item.setdefault("question", item.get("scientific_question", ""))
            item["config"] = SimulationConfig.model_validate(item["config"]).model_dump(mode="json")
        report = validation_report("full")
        for item in result:
            evidence = item.get("evidence_record")
            if not evidence:
                continue
            evidence["report_sha256"] = report.get("freshness", {}).get("report_sha256")
            if report.get("freshness", {}).get("source_match") is False:
                evidence["status"] = "stale"
                continue
            if report.get("freshness", {}).get("source_match") is not True:
                continue
            case: dict = next(
                (
                    case
                    for case in report.get("cases", [])
                    if case["id"] == "preset-boundary-sensitivity"
                ),
                {},
            )
            matched = next(
                (
                    entry
                    for entry in case.get("metrics", {}).get("presets", [])
                    if entry.get("configuration_sha256") == evidence["configuration_sha256"]
                ),
                None,
            )
            if matched is not None:
                evidence.update(
                    status="checked" if matched["passed"] else "failed",
                    measured_conditions=matched["conditions"],
                    reference_configuration_sha256=matched["reference_configuration_sha256"],
                    metrics={
                        key: value
                        for key, value in matched.items()
                        if key
                        not in (
                            "id",
                            "configuration_sha256",
                            "reference_configuration_sha256",
                            "conditions",
                        )
                    },
                )
        return result

    @app.get("/api/config-schema")
    def schema():
        return SimulationConfig.model_json_schema()

    @app.post("/api/config/resolve", response_model=SimulationConfig)
    def resolve(config: SimulationConfig):
        try:
            enforce_resources(config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return config

    @app.get("/api/units", response_model=UnitScalesRecord)
    def units(length_nm: float = Query(1.0, gt=0)):
        try:
            values: dict[str, Any] = electron_scales(length_nm).as_dict()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        values.update(
            mass="electron",
            note="Display conversions only; numerical core uses hbar=m=1.",
        )
        return values

    @app.post("/api/preflight")
    def preflight(config: SimulationConfig):
        return estimate_resources(config)

    @app.post("/api/runs", status_code=202, response_model=RunRecord)
    def start(config: SimulationConfig):
        try:
            return supervisor.start(config)
        except RunBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/runs", response_model=list[RunRecord])
    def runs():
        supervisor.refresh()
        return sorted(supervisor.records.values(), key=lambda r: r["created_at"], reverse=True)[
            :100
        ]

    @app.get("/api/runs/{run_id}", response_model=RunRecord)
    def run(run_id: str):
        return supervisor.get(run_id)

    @app.post("/api/runs/{run_id}/cancel", response_model=RunRecord)
    def cancel(run_id: str):
        with supervisor.lock:
            record = supervisor.get(run_id)
            if record["status"] == "finalizing":
                raise HTTPException(
                    409,
                    "Run is already finalizing; its scientific files are closing and cannot be cancelled",
                )
            if supervisor.active_id == run_id and supervisor.event is not None:
                supervisor.event.set()
            elif record["status"] in ACTIVE_STATUSES:
                raise HTTPException(
                    409,
                    "This live run belongs to another process and cannot be cancelled by this supervisor",
                )
            return record

    @app.get("/api/runs/{run_id}/preview", response_model=Frame)
    def preview(run_id: str):
        supervisor.get(run_id)
        if run_id not in supervisor.previews:
            raise HTTPException(404, "Preview unavailable; use saved frames for completed runs")
        return supervisor.previews[run_id]

    def closed_record(run_id: str):
        record = supervisor.get(run_id)
        if record["status"] in ACTIVE_STATUSES:
            raise HTTPException(409, "Scientific artifacts are not finalized")
        return record

    @app.get("/api/runs/{run_id}/frames")
    def frames(run_id: str):
        record = supervisor.get(run_id)
        if record["status"] in ACTIVE_STATUSES:
            return []
        path = supervisor.folder(run_id) / "state.h5"
        if not path.is_file():
            return []
        with h5py.File(path) as store:
            return [{"index": i, "time": float(t)} for i, t in enumerate(store["time"][:])]

    @app.get("/api/runs/{run_id}/frames/{index}", response_model=Frame)
    def frame(run_id: str, index: int):
        closed_record(run_id)
        try:
            return read_frame(supervisor.folder(run_id), index)
        except (IndexError, FileNotFoundError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/runs/{run_id}/observables", response_model=list[Measurements])
    def observables(run_id: str, max_points: int = Query(2000, ge=2, le=2000)):
        record = supervisor.get(run_id)
        if record["status"] in ACTIVE_STATUSES:
            latest = supervisor.previews.get(run_id)
            return [latest["observables"]] if latest else []
        return read_observables(supervisor.folder(run_id), max_points=max_points)

    @app.get("/api/runs/{run_id}/screen")
    def screen(run_id: str):
        record = supervisor.get(run_id)
        if record["status"] in ACTIVE_STATUSES:
            result = supervisor.previews.get(run_id, {}).get("screen")
        else:
            path = supervisor.folder(run_id) / "state.h5"
            if not path.is_file():
                raise HTTPException(404, "No closed scientific data available")
            with h5py.File(path) as store:
                last = len(store["time"]) - 1
            result = (
                read_frame(supervisor.folder(run_id), last).get("screen") if last >= 0 else None
            )
        if result is None:
            raise HTTPException(404, "No screen profile; enable sampling.screen_x for a 2D run")
        return result

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    def artifact(run_id: str, name: str):
        record = supervisor.get(run_id)
        if name not in ARTIFACTS:
            raise HTTPException(404, "Unknown artifact")
        if record["status"] in ACTIVE_STATUSES and name not in (
            "config.json",
            "manifest.json",
            "record.json",
        ):
            raise HTTPException(409, "Artifact is still being finalized")
        if record["status"] == "failed" and name == "report.html":
            raise HTTPException(
                409, "Run finalization failed; inspect canonical record and raw data"
            )
        path = supervisor.folder(run_id) / name
        if not path.is_file():
            raise HTTPException(404, "Artifact unavailable")
        return FileResponse(path, filename=f"{run_id[:8]}-{name}")

    def validation_report(suite: str):
        snapshot = paths.evidence_snapshot(suite)
        if snapshot is None:
            return {
                "status": "not_run",
                "suite": suite,
                "note": f"Run wavepacket validate --suite {suite} --data-dir {paths.data_dir}",
            }
        path, content = snapshot
        try:
            report = ValidationReport.model_validate_json(content).model_dump(
                mode="json", exclude_unset=True
            )
            provenance = report.get("provenance", {})
            if not isinstance(provenance, dict):
                raise ValueError("provenance must be an object")
            hashes = provenance.get("source_sha256", {})
            if not isinstance(hashes, dict) or any(
                not isinstance(name, str) or not isinstance(value, str)
                for name, value in hashes.items()
            ):
                raise ValueError("source_sha256 must map filenames to hash strings")
            changed = provenance.get("sources_changed_during_run", [])
            if not isinstance(changed, list) or any(not isinstance(name, str) for name in changed):
                raise ValueError("sources_changed_during_run must be a list of filenames")
            for case in report.get("cases", []):
                if case["id"] != "preset-boundary-sensitivity":
                    continue
                entries = case.get("metrics", {}).get("presets", [])
                if not isinstance(entries, list) or any(
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("configuration_sha256"), str)
                    or not isinstance(entry.get("reference_configuration_sha256"), str)
                    or not isinstance(entry.get("conditions"), dict)
                    or not isinstance(entry.get("passed"), bool)
                    for entry in entries
                ):
                    raise ValueError("preset boundary results have an invalid shape")
        except (OSError, ValueError) as error:
            return {
                "status": "invalid",
                "suite": suite,
                "note": f"Saved evidence is invalid: {error}",
            }
        required = {
            "config.py",
            "model.py",
            "operators.py",
            "propagators.py",
            "observables.py",
            "experiments.py",
            "validation.py",
            "units.py",
        }
        mismatches = sorted(required - hashes.keys()) + [
            name
            for name, digest in hashes.items()
            if Path(name).name != name
            or not (Path(__file__).parent / name).is_file()
            or hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest
        ]
        report["freshness"] = {
            "source_match": not mismatches and not changed if hashes else None,
            "mismatched_sources": mismatches,
            "report_sha256": hashlib.sha256(content).hexdigest(),
            "evidence_path": str(path),
        }
        return report

    @app.get("/api/validation", response_model=ValidationReport)
    def validation(suite: str = Query("full", pattern="^(full|quick)$")):
        return validation_report(suite)

    web = Path(__file__).parent / "web"
    if (web / "index.html").exists():
        app.mount("/", StaticFiles(directory=web, html=True), name="laboratory")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def build_hint():
            return "<h1>Wavepacket</h1><p>Build frontend assets; API docs: <a href='/docs'>/docs</a>.</p>"

    return app
