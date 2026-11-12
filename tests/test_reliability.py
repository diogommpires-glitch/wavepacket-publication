"""Persistence and resource regressions at the CLI/API/worker boundaries."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wavepacket.api import RunSupervisor, create_app
from wavepacket.cli import app
from wavepacket.config import SimulationConfig, config_fingerprint
from wavepacket.runner import (
    compare_runs,
    estimate_resources,
    read_frame,
    read_observables,
    read_record,
    run_simulation,
    timestamp,
    write_json,
)
from wavepacket.storage import RunBusy, StoragePaths, acquire_lock, process_identity


def small_config():
    return SimulationConfig.model_validate(
        {
            "grid": {"bounds": [[-12, 12]], "points": [64]},
            "state": {"center": [-2], "momentum": [1], "sigma": [1]},
            "solver": {"dt": 0.01, "duration": 0.04},
            "sampling": {"snapshots": 3},
        }
    )


def publish_terminal_record(root, run_id, terminal_status, ready, finish):
    lease = acquire_lock(root, ".writer.lock")
    try:
        record = {
            "id": run_id,
            "status": "finalizing",
            "created_at": timestamp(),
            "config": small_config().model_dump(mode="json"),
            "owner": process_identity(),
            "scientific_status": terminal_status,
            "report_status": "pending",
        }
        write_json(root / run_id / "record.json", record)
        ready.set()
        assert finish.wait(timeout=10)
        record.update(status=terminal_status, report_status="completed", finished_at=timestamp())
        write_json(root / run_id / "record.json", record)
    finally:
        lease.release()


@pytest.mark.parametrize("recovery_branch", ["recorded_owner", "owned_process"])
@pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
def test_terminal_record_wins_when_worker_exits_after_supervisor_snapshot(
    tmp_path, monkeypatch, recovery_branch, terminal_status
):
    context = mp.get_context("spawn")
    ready, finish = context.Event(), context.Event()
    run_id = "a" * 32
    worker = context.Process(
        target=publish_terminal_record,
        args=(tmp_path, run_id, terminal_status, ready, finish),
    )
    worker.start()
    supervisor = None
    original_is_alive = worker.is_alive
    committed = []
    try:
        assert ready.wait(timeout=10)
        supervisor = RunSupervisor(tmp_path)
        supervisor.open()
        path = supervisor.folder(run_id) / "record.json"

        def commit_and_exit():
            if not committed:
                finish.set()
                worker.join(timeout=5)
                assert not original_is_alive()
                assert worker.exitcode == 0
                committed.append(path.read_bytes())

        if recovery_branch == "recorded_owner":
            original_read = Path.read_text

            def read_then_exit(source, *args, **kwargs):
                content = original_read(source, *args, **kwargs)
                if source == path and not committed:
                    commit_and_exit()
                return content

            monkeypatch.setattr(Path, "read_text", read_then_exit)
        else:
            supervisor.process, supervisor.active_id = worker, run_id

            def exit_then_check():
                commit_and_exit()
                return original_is_alive()

            monkeypatch.setattr(worker, "is_alive", exit_then_check)
        supervisor.refresh()
        assert committed and path.read_bytes() == committed[0]
        assert supervisor.get(run_id)["status"] == terminal_status
        if recovery_branch == "owned_process":
            assert supervisor.active_id is None and supervisor.process is None
    finally:
        finish.set()
        worker.join(timeout=5)
        if original_is_alive():
            worker.kill()
            worker.join(timeout=5)
        if supervisor is not None:
            supervisor.close()


@contextmanager
def windows_reader_without_delete_sharing(path, *, allow_readers=True):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, int(allow_readers), None, 3, 128, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readers can deny atomic replacement")
def test_canonical_record_replacement_waits_for_a_temporary_windows_reader(tmp_path):
    path = tmp_path / "record.json"
    previous = {"status": "finalizing", "summary": {"complete": False}}
    completed = {"status": "completed", "summary": {"complete": True}}
    write_json(path, previous)
    original_bytes = path.read_bytes()
    errors = []

    def publish():
        try:
            write_json(path, completed)
        except OSError as error:
            errors.append(error)

    writer = threading.Thread(target=publish)
    try:
        with windows_reader_without_delete_sharing(path):
            writer.start()
            deadline = time.monotonic() + 1
            while not path.with_suffix(".json.tmp").exists() and writer.is_alive():
                assert time.monotonic() < deadline
                time.sleep(0.005)
            time.sleep(0.05)
            assert writer.is_alive(), (
                f"Canonical write failed during temporary read sharing: {errors}"
            )
            assert path.read_bytes() == original_bytes
    finally:
        if writer.ident is not None:
            writer.join(timeout=3)
    assert not writer.is_alive() and not errors
    assert json.loads(path.read_bytes()) == completed
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readers can deny atomic replacement")
def test_persistent_windows_record_denial_still_raises_and_preserves_canonical_bytes(tmp_path):
    path = tmp_path / "record.json"
    write_json(path, {"status": "finalizing"})
    original_bytes = path.read_bytes()
    with windows_reader_without_delete_sharing(path):
        with pytest.raises(PermissionError) as denied:
            write_json(path, {"status": "completed"})
        assert denied.value.winerror in (5, 32, 33)
        assert path.read_bytes() == original_bytes


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readers can temporarily deny reads")
def test_admitted_run_survives_a_temporary_windows_record_read_denial(tmp_path):
    supervisor = RunSupervisor(tmp_path)
    results, errors = [], []
    reader = None
    try:
        record = supervisor.start(
            SimulationConfig.model_validate(
                {"solver": {"duration": 500, "dt": 0.005}, "sampling": {"snapshots": 2}}
            )
        )
        path = supervisor.folder(record["id"]) / "record.json"

        def read():
            try:
                results.append(supervisor.get(record["id"]))
            except Exception as error:
                errors.append(error)

        reader = threading.Thread(target=read)
        with windows_reader_without_delete_sharing(path, allow_readers=False):
            reader.start()
            time.sleep(0.05)
            assert reader.is_alive(), (
                f"Admitted run disappeared during temporary read denial: {errors}"
            )
        reader.join(timeout=3)
        assert not reader.is_alive() and not errors
        assert results[0]["id"] == record["id"] and results[0]["status"] == "running"
        assert record["id"] not in supervisor.storage_warnings
    finally:
        if reader is not None and reader.ident is not None:
            reader.join(timeout=3)
        supervisor.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readers can deny canonical reads")
def test_persistent_windows_record_read_denial_still_raises(tmp_path):
    run = run_simulation(small_config(), tmp_path)
    path = tmp_path / run["id"] / "record.json"
    original_bytes = path.read_bytes()
    with windows_reader_without_delete_sharing(path, allow_readers=False):
        with pytest.raises(PermissionError) as denied:
            read_record(path.parent)
        assert denied.value.errno == 13
    assert path.read_bytes() == original_bytes


def test_canonical_record_disk_failure_is_not_retried_or_hidden(tmp_path, monkeypatch):
    import errno

    path = tmp_path / "record.json"
    write_json(path, {"status": "finalizing"})
    original_bytes = path.read_bytes()
    attempts = 0

    def disk_full(source, destination):
        nonlocal attempts
        attempts += 1
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "replace", disk_full)
    with pytest.raises(OSError, match="No space left"):
        write_json(path, {"status": "completed"})
    assert attempts == 1 and path.read_bytes() == original_bytes


def test_finalization_failure_cannot_be_compared_as_success(tmp_path, monkeypatch):
    from wavepacket import reporting

    def disk_failure(folder):
        raise OSError("report disk write failed")

    monkeypatch.setattr(reporting, "report_run", disk_failure)
    with pytest.raises(OSError, match="report disk"):
        run_simulation(small_config(), tmp_path)
    folder = next(path.parent for path in tmp_path.glob("*/record.json"))
    record = json.loads((folder / "record.json").read_text())
    summary = json.loads((folder / "summary.json").read_text())
    assert record["status"] == summary["status"] == "failed"
    assert record["scientific_status"] == "completed"
    assert record["report_status"] == "failed"
    assert (folder / "state.h5").is_file()
    assert compare_runs([folder])["all_completed"] is False


def test_writer_lease_covers_admission_and_finalization(tmp_path):
    seen = []

    def check_lease(record):
        assert (
            json.loads((tmp_path / record["id"] / "record.json").read_text())["status"] == "running"
        )
        with pytest.raises(RunBusy):
            acquire_lock(tmp_path, ".writer.lock")
        seen.append("admitted")

    def progress(update):
        if update["status"] == "finalizing":
            with pytest.raises(RunBusy):
                acquire_lock(tmp_path, ".writer.lock")
            seen.append("finalizing")

    run_simulation(small_config(), tmp_path, admitted=check_lease, progress=progress)
    assert seen == ["admitted", "finalizing"]
    acquire_lock(tmp_path, ".writer.lock").release()


def test_preview_write_failure_keeps_science_success_and_records_reason(tmp_path, monkeypatch):
    from wavepacket.api import _publish_preview

    original = Path.replace

    def deny_preview_replace(path, target):
        if Path(target).name == "preview.json":
            raise PermissionError("preview file is temporarily open")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", deny_preview_replace)
    run_id = "c" * 32
    preview = tmp_path / run_id / "preview.json"
    record = run_simulation(
        small_config(),
        tmp_path,
        run_id=run_id,
        progress=lambda update: _publish_preview(preview, update),
    )
    assert record["status"] == "completed" and record["report_status"] == "completed"
    assert any(
        "Live preview publication failed (PermissionError" in warning
        for warning in record["warnings"]
    )
    assert not preview.exists() and not preview.with_suffix(".json.tmp").exists()
    assert compare_runs([preview.parent])["all_completed"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows read sharing controls atomic replace")
def test_windows_read_contention_drops_preview_without_invalidating_run(tmp_path):
    from wavepacket.api import _publish_preview

    run_id = "d" * 32
    path = tmp_path / run_id / "preview.json"
    reader_open = False
    first_frame = None

    def progress(update):
        nonlocal reader_open, first_frame
        if "frame" in update and not reader_open:
            assert _publish_preview(path, update) is None
            first_frame = path.read_bytes()
            readers.enter_context(windows_reader_without_delete_sharing(path))
            reader_open = True
        return _publish_preview(path, update)

    with ExitStack() as readers:
        record = run_simulation(small_config(), tmp_path, run_id=run_id, progress=progress)
        assert record["status"] == "completed"
        assert any("PermissionError" in warning for warning in record["warnings"])
        assert path.read_bytes() == first_frame
        assert not path.with_suffix(".json.tmp").exists()


def test_foreign_live_record_is_read_without_takeover_and_refreshes(tmp_path):
    run_id = "a" * 32
    record = {
        "id": run_id,
        "status": "running",
        "created_at": timestamp(),
        "owner": process_identity(),
        "config": small_config().model_dump(mode="json"),
    }
    path = tmp_path / run_id / "record.json"
    write_json(path, record)
    before = path.read_bytes()
    supervisor = RunSupervisor(tmp_path)
    supervisor.open()
    try:
        assert path.read_bytes() == before
        assert supervisor.get(run_id)["status"] == "running"
        other = RunSupervisor(tmp_path / ".")
        with pytest.raises(RunBusy):
            other.open()
        record["status"] = "completed"
        write_json(path, record)
        assert supervisor.get(run_id)["status"] == "completed"
    finally:
        supervisor.close()


def test_cli_named_record_can_recover_a_dead_owner_without_api_identifier_rules(tmp_path):
    record = run_simulation(small_config(), tmp_path, run_id="reviewrun")
    record["owner"]["create_time"] -= 1000
    record.update(status="running", scientific_status="running", report_status="pending")
    write_json(tmp_path / "reviewrun" / "record.json", record)
    supervisor = RunSupervisor(tmp_path)
    try:
        supervisor.open()
        assert supervisor.records["reviewrun"]["status"] == "failed"
        assert read_record(tmp_path / "reviewrun")["scientific_status"] == "incomplete"
    finally:
        supervisor.close()


def test_corrupt_record_is_reported_without_hiding_valid_history(tmp_path):
    run_id = "e" * 32
    write_json(
        tmp_path / run_id / "record.json",
        {
            "id": run_id,
            "status": "completed",
            "created_at": timestamp(),
            "config": small_config().model_dump(mode="json"),
        },
    )
    write_json(tmp_path / ("f" * 32) / "record.json", {"status": "invented"})
    supervisor = RunSupervisor(tmp_path)
    assert set(supervisor.records) == {run_id}
    assert "f" * 32 in supervisor.storage_warnings
    write_json(tmp_path / run_id / "record.json", [])
    supervisor.refresh()
    assert not supervisor.records
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        unavailable = client.get(f"/api/runs/{run_id}")
        assert unavailable.status_code == 503
        assert "Run record unavailable" in unavailable.json()["detail"]
        assert client.get(f"/api/runs/{'0' * 32}").status_code == 404


def test_estimates_include_diagnostic_rows_and_enforce_working_memory(tmp_path):
    data = small_config().model_dump(mode="json")
    data.update(
        solver={"duration": 1, "dt": 0.001},
        sampling={"snapshots": 2, "observable_every": 1},
        budget={"max_output_bytes": 1024},
    )
    data["grid"]["points"] = [16]
    config = SimulationConfig.model_validate(data)
    estimate = estimate_resources(config)
    assert estimate["observations"] == 1001
    assert estimate["estimated_diagnostics_bytes"] > 4_000_000
    with pytest.raises(ValueError, match="max_output_bytes"):
        run_simulation(config, tmp_path)
    data["budget"] = {"max_working_bytes": 1048576}
    with pytest.raises(ValueError, match="max_working_bytes"):
        run_simulation(SimulationConfig.model_validate(data), tmp_path)
    assert not list(tmp_path.glob("*/record.json"))


def test_bounded_csv_read_preserves_nulls_and_endpoints(tmp_path):
    (tmp_path / "observables.csv").write_text(
        "time,norm,energy\n" + "".join(f"{index},1,\n" for index in range(5001)), encoding="utf-8"
    )
    rows = read_observables(tmp_path, max_points=2000)
    assert len(rows) == 2000
    assert rows[0] == {"time": 0, "norm": 1, "energy": None}
    assert rows[-1]["time"] == 5000


def test_saved_frame_identity_and_density_scale_are_frozen(tmp_path):
    config = small_config()
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    frames = [read_frame(folder, index) for index in range(3)]
    assert {frame["run_id"] for frame in frames} == {record["id"]}
    assert {frame["config_sha256"] for frame in frames} == {config_fingerprint(config)}
    assert {frame["density_scale_max"] for frame in frames} == {
        record["summary"]["max_saved_density"]
    }
    assert all(frame["validity"]["conditional_status"] == "resolved" for frame in frames)


def test_absorbed_state_persists_null_conditional_values_and_raw_probability(tmp_path):
    config = SimulationConfig.model_validate(
        {
            "grid": {"bounds": [[-10, 10]], "points": [64]},
            "state": {"center": [8], "sigma": [0.7], "momentum": [2]},
            "solver": {"dt": 0.01, "duration": 3},
            "boundary": {"kind": "cap", "width": 9.9, "strength": 10000},
            "sampling": {"snapshots": 3, "observable_every": 20},
        }
    )
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    frame = read_frame(folder, 2)
    rows = read_observables(folder)
    assert frame["validity"]["conditional_status"] == "below_reporting_floor"
    assert frame["observables"]["energy"] is None and rows[-1]["energy"] is None
    assert frame["observables"]["norm"] > 0
    assert frame["observables"]["absorbed_probability"] > 0.99
    assert record["summary"]["final"]["energy"] is None


def test_explicit_storage_resolver_units_and_finalizing_api(tmp_path):
    paths = StoragePaths.resolve(tmp_path)
    record = {
        "id": "b" * 32,
        "status": "finalizing",
        "created_at": timestamp(),
        "owner": process_identity(),
        "config": small_config().model_dump(mode="json"),
    }
    write_json(paths.runs / record["id"] / "record.json", record)
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/storage").json()["runs"] == str(paths.runs)
        result = client.post("/api/config/resolve", json={"grid": {"points": [64]}})
        assert result.status_code == 200
        assert result.json()["state"]["center"] == list(SimulationConfig().state.center)
        assert result.json()["budget"]["max_working_bytes"] == 536870912
        assert client.post("/api/config/resolve", json={"solver": {"dt": -1}}).status_code == 422
        for scale in ("1e-300", "1e300", "nan", "inf"):
            assert client.get(f"/api/units?length_nm={scale}").status_code == 422
        assert client.post(f"/api/runs/{record['id']}/cancel").status_code == 409
        assert client.get(f"/api/runs/{record['id']}/artifacts/state.h5").status_code == 409


def test_busy_worker_admission_returns_409_without_damaging_owner(tmp_path):
    lease = acquire_lock(tmp_path, ".writer.lock")
    try:
        with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
            response = client.post("/api/runs", json=small_config().model_dump(mode="json"))
            assert response.status_code == 409, response.text
            assert not list(tmp_path.glob("*/state.h5*"))
    finally:
        lease.release()


def test_crashed_owned_worker_is_incomplete_and_releases_the_os_lease(tmp_path):
    application = create_app(tmp_path)
    config = small_config().model_dump(mode="json")
    config["solver"] = {"duration": 1000, "dt": 0.005}
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.post("/api/runs", json=config)
        assert response.status_code == 202
        run_id = response.json()["id"]
        worker = application.state.supervisor.process
        worker.kill()
        worker.join(timeout=5)
        assert not worker.is_alive()
        lease = acquire_lock(tmp_path, ".writer.lock")
        try:
            deferred = client.get(f"/api/runs/{run_id}").json()
            assert deferred["status"] in ("queued", "running", "finalizing")
            assert f"{run_id}:recovery" in application.state.supervisor.storage_warnings
        finally:
            lease.release()
        record = client.get(f"/api/runs/{run_id}").json()
        assert record["status"] == "failed" and record["scientific_status"] == "incomplete"
        assert application.state.supervisor.active_id is None
        acquire_lock(tmp_path, ".writer.lock").release()
        second = client.post("/api/runs", json=small_config().model_dump(mode="json"))
        assert second.status_code == 202, second.text
        deadline = time.monotonic() + 120
        while True:
            final = client.get(f"/api/runs/{second.json()['id']}").json()
            if final["status"] not in ("queued", "running", "finalizing"):
                break
            assert time.monotonic() < deadline, final
            time.sleep(0.1)
        assert final["status"] == "completed", final


def test_validation_defaults_full_and_matches_source_hashes_not_mtime(tmp_path):
    import wavepacket.validation as module

    sources = (
        "config.py",
        "model.py",
        "operators.py",
        "propagators.py",
        "observables.py",
        "experiments.py",
        "validation.py",
        "units.py",
    )
    hashes = {
        name: hashlib.sha256(Path(module.__file__).with_name(name).read_bytes()).hexdigest()
        for name in sources
    }
    paths = StoragePaths.resolve(tmp_path)
    write_json(paths.evidence / "quick" / "validation.json", {"suite": "quick", "status": "passed"})
    report = {"suite": "full", "status": "passed", "provenance": {"source_sha256": hashes}}
    path = paths.evidence / "full" / "validation.json"
    write_json(path, report)
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        result = client.get("/api/validation").json()
        assert result["suite"] == "full" and result["freshness"]["source_match"] is True
        assert client.get("/api/validation?suite=quick").json()["suite"] == "quick"
        report["provenance"]["source_sha256"]["config.py"] = "0" * 64
        write_json(path, report)
        assert client.get("/api/validation").json()["freshness"]["source_match"] is False
        assert client.get("/api/validation?suite=invalid").status_code == 422


def test_cli_storage_flags_report_legacy_conflicts_and_reject_before_worker(tmp_path):
    config = small_config().model_dump(mode="json")
    config["budget"]["max_working_bytes"] = 1048576
    path = tmp_path / "config.json"
    write_json(path, config)
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(path), "--data-dir", str(tmp_path)])
    assert result.exit_code == 1 and "max_working_bytes" in result.output
    conflict = runner.invoke(
        app, ["run", str(path), "--data-dir", str(tmp_path), "--output", str(tmp_path)]
    )
    assert conflict.exit_code == 2 and "legacy" in conflict.output
    assert not (tmp_path / "runs").exists()
