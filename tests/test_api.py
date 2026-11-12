from __future__ import annotations

import inspect
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wavepacket.api import create_app
from wavepacket.config import SimulationConfig

WORKER_TIMEOUT_SECONDS = 60
ADMISSION_TIMEOUT_SECONDS = 30


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8765", "localhost", "localhost:8765"])
def test_loopback_hosts_can_read_storage_and_resolve_configuration(tmp_path, host):
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        response = client.get("/api/storage", headers={"Host": host})
        assert response.status_code == 200
        assert response.json()["data_dir"] == str(tmp_path.resolve())
        response = client.post("/api/config/resolve", json={}, headers={"Host": host})
        assert response.status_code == 200
        SimulationConfig.model_validate(response.json())


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("rebind.attacker.invalid:8765", "http://rebind.attacker.invalid:8765"),
        ("127.0.0.1.attacker.invalid:8765", "http://127.0.0.1:5173"),
        ("www.localhost:8765", "http://localhost:5173"),
    ],
)
@pytest.mark.parametrize(("method", "path"), [("GET", "/api/storage"), ("POST", "/api/runs")])
def test_untrusted_hosts_cannot_read_data_or_start_runs(tmp_path, host, origin, method, path):
    config = {"grid": {"points": [64]}, "solver": {"duration": 0.01, "dt": 0.01}}
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        response = client.request(
            method,
            path,
            headers={"Host": host, "Origin": origin},
            json=config,
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert not list((tmp_path / "runs").glob("*/record.json"))


def test_openapi_contract_is_independent_of_built_browser_assets(tmp_path):
    import wavepacket

    package = tmp_path / "source" / "wavepacket"
    shutil.copytree(
        Path(wavepacket.__file__).parent,
        package,
        ignore=shutil.ignore_patterns("web", "__pycache__"),
    )
    code = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from wavepacket.api import create_app
root = Path(sys.argv[1])
before = create_app(data_dir=root/'before').openapi()
web = root/'wavepacket/web'
web.mkdir()
(web/'index.html').write_text('<html>built browser</html>')
after = create_app(data_dir=root/'after').openapi()
assert after['info']['title'] == 'Wavepacket'
assert before == after, 'Building browser assets changed the scientific API contract'
assert '/' not in after['paths'], 'The browser build hint is not a scientific API route'
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(package.parent)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_presets_and_electron_unit_scaling(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["application"] == "Wavepacket"
        presets = client.get("/api/presets").json()
        assert len(presets) == 16
        for preset in presets:
            SimulationConfig.model_validate(preset["config"])
        a = client.get("/api/units?length_nm=1").json()
        b = client.get("/api/units?length_nm=2").json()
        assert abs(b["time_fs"] / a["time_fs"] - 4) < 1e-12
        assert abs(b["energy_ev"] / a["energy_ev"] - 0.25) < 1e-12
        assert client.get("/api/units?length_nm=-1").status_code == 422
        assert "properties" in client.get("/api/config-schema").json()


def test_worker_run_replay_download_and_restart_history(tmp_path):
    config = SimulationConfig.model_validate(
        {
            "grid": {"bounds": [[-12, 12]], "points": [64]},
            "state": {"center": [-2], "momentum": [1], "sigma": [1]},
            "solver": {"dt": 0.01, "duration": 0.1},
            "sampling": {"snapshots": 4},
        }
    )
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.post("/api/runs", json=config.model_dump(mode="json"))
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
        while True:
            record = client.get(f"/api/runs/{run_id}").json()
            if record["status"] not in ("queued", "running", "finalizing"):
                break
            assert time.monotonic() < deadline, f"Timed out waiting for run {run_id}: {record}"
            time.sleep(0.1)
        assert record["status"] == "completed", record
        assert len(client.get(f"/api/runs/{run_id}/frames").json()) == 4
        frame = client.get(f"/api/runs/{run_id}/frames/3").json()
        assert abs(frame["observables"]["norm"] - 1) < 1e-11
        assert client.get(f"/api/runs/{run_id}/artifacts/state.h5").status_code == 200
        assert client.get(f"/api/runs/{run_id}/artifacts/secret.txt").status_code == 404
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/runs").json()[0]["id"] == run_id
        assert client.get(f"/api/runs/{run_id}/frames/0").status_code == 200


def test_busy_cancel_invalid_method_and_resource_cap(tmp_path):
    config = SimulationConfig.model_validate(
        {"solver": {"duration": 500, "dt": 0.005}, "sampling": {"snapshots": 4}}
    ).model_dump(mode="json")
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        first = client.post("/api/runs", json=config)
        assert first.status_code == 202
        assert client.post("/api/runs", json=config).status_code == 409
        run_id = first.json()["id"]
        client.post(f"/api/runs/{run_id}/cancel")
        deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
        while True:
            result = client.get(f"/api/runs/{run_id}").json()
            if result["status"] not in ("queued", "running", "finalizing"):
                break
            assert time.monotonic() < deadline, f"Timed out waiting for run {run_id}: {result}"
            time.sleep(0.1)
        assert result["status"] == "cancelled", result
        config["solver"]["method"] = "yoshida4"
        config["boundary"]["kind"] = "cap"
        assert client.post("/api/runs", json=config).status_code == 422
        config["boundary"]["kind"] = "periodic"
        config["grid"]["points"] = [65536]
        assert client.post("/api/runs", json=config).status_code == 422


def test_cancel_cannot_signal_a_newly_admitted_run(tmp_path):
    application = create_app(data_dir=tmp_path)
    supervisor = application.state.supervisor
    cancel = next(
        route.endpoint
        for route in application.routes
        if getattr(route, "path", None) == "/api/runs/{run_id}/cancel"
    )
    lines, first_line = inspect.getsourcelines(cancel)
    signal_line = first_line + next(
        index for index, line in enumerate(lines) if line.strip() == "supervisor.event.set()"
    )
    paused, resume, admitted = threading.Event(), threading.Event(), threading.Event()
    errors, result = [], {}
    cancel_thread = admission_thread = None

    def pause_before_signal(frame, event, argument):
        if event == "line" and frame.f_code is cancel.__code__ and frame.f_lineno == signal_line:
            paused.set()
            assert resume.wait(timeout=WORKER_TIMEOUT_SECONDS + ADMISSION_TIMEOUT_SECONDS + 15)
        return pause_before_signal

    def cancel_first(run_id):
        sys.settrace(pause_before_signal)
        try:
            result["cancel_response"] = cancel(run_id)
        except Exception as error:
            errors.append(error)
        finally:
            sys.settrace(None)

    def admit_second():
        try:
            result["second"] = supervisor.start(
                SimulationConfig.model_validate(
                    {"grid": {"points": [64]}, "solver": {"duration": 0.02, "dt": 0.01}}
                )
            )
            result["second_event"], result["second_worker"] = supervisor.event, supervisor.process
        except Exception as error:
            errors.append(error)
        finally:
            admitted.set()

    try:
        first = supervisor.start(
            SimulationConfig.model_validate(
                {"solver": {"duration": 500, "dt": 0.005}, "sampling": {"snapshots": 2}}
            )
        )
        first_event, first_worker = supervisor.event, supervisor.process
        cancel_thread = threading.Thread(target=cancel_first, args=(first["id"],))
        cancel_thread.start()
        assert paused.wait(timeout=10)
        first_event.set()
        first_worker.join(timeout=WORKER_TIMEOUT_SECONDS)
        assert not first_worker.is_alive(), "First worker did not finish after cancellation"

        # Exercise the dangerous order if admission is independent of cancellation;
        # a serialized implementation must finish cancellation before admitting B.
        can_admit_before_signal = supervisor.lock.acquire(blocking=False)
        if can_admit_before_signal:
            supervisor.lock.release()
        admission_thread = threading.Thread(target=admit_second)
        admission_thread.start()
        if can_admit_before_signal:
            assert admitted.wait(timeout=ADMISSION_TIMEOUT_SECONDS)
        resume.set()
        cancel_thread.join(timeout=10)
        admission_thread.join(timeout=ADMISSION_TIMEOUT_SECONDS)
        assert not cancel_thread.is_alive() and not admission_thread.is_alive() and not errors
        assert result["cancel_response"]["id"] == first["id"]
        assert not result["second_event"].is_set()
        result["second_worker"].join(timeout=WORKER_TIMEOUT_SECONDS)
        assert not result["second_worker"].is_alive(), "Second worker did not finish"
        assert supervisor.get(result["second"]["id"])["status"] == "completed"
    finally:
        resume.set()
        for thread in (cancel_thread, admission_thread):
            if thread is not None:
                thread.join(timeout=10)
        supervisor.close()


def test_config_resolver_and_run_admission_share_working_memory_limit(tmp_path):
    config = {
        "grid": {"bounds": [[-10, 10], [-10, 10]], "points": [128, 128]},
        "state": {"center": [0, 0], "momentum": [1, 0], "sigma": [1, 1]},
        "budget": {"max_working_bytes": 1_048_576},
    }
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        for endpoint in ("/api/config/resolve", "/api/runs"):
            result = client.post(endpoint, json=config)
            assert result.status_code == 422, result.text
            assert "working memory" in result.json()["detail"].lower()
