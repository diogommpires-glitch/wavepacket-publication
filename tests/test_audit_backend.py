"""Independent regressions for malformed persisted data and owned worker cleanup."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wavepacket.api import create_app
from wavepacket.config import SimulationConfig
from wavepacket.runner import write_json
from wavepacket.storage import acquire_lock, process_identity


@pytest.mark.parametrize(
    "report",
    [
        [],
        None,
        {"suite": "full", "status": "passed", "provenance": []},
        {"suite": "full", "status": "passed", "provenance": {"source_sha256": []}},
        {"suite": "full", "status": "passed", "cases": [{}]},
    ],
)
def test_malformed_evidence_does_not_break_experiment_catalogue(tmp_path, report):
    path = tmp_path / "results/validation/full/validation.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")
    with TestClient(
        create_app(data_dir=tmp_path), base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/presets")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 16
        assert all(item["evidence_record"]["status"] != "checked" for item in response.json())
        validation = client.get("/api/validation")
        assert validation.status_code in (200, 422, 503), validation.text
        if validation.status_code == 200:
            assert validation.json()["status"] != "passed"


def test_corrupt_owned_record_does_not_prevent_worker_cleanup_and_next_admission(tmp_path):
    application = create_app(data_dir=tmp_path)
    long_config = SimulationConfig.model_validate(
        {"solver": {"duration": 1000, "dt": 0.005}, "sampling": {"snapshots": 2}}
    )
    with TestClient(
        application, base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.post("/api/runs", json=long_config.model_dump(mode="json"))
        assert response.status_code == 202, response.text
        admitted = response.json()
        path = tmp_path / "runs" / admitted["id"] / "record.json"
        worker = application.state.supervisor.process
        worker.kill()
        worker.join(timeout=5)
        assert not worker.is_alive()
        path.write_text("[]", encoding="utf-8")
        try:
            history = client.get("/api/runs")
            assert history.status_code == 200, history.text
            assert application.state.supervisor.active_id is None
            assert all(
                record["id"] != admitted["id"] or record["status"] == "failed"
                for record in history.json()
            )
            acquire_lock(tmp_path / "runs", ".writer.lock").release()
            config = SimulationConfig.model_validate(
                {"grid": {"points": [64]}, "solver": {"duration": 0.01, "dt": 0.01}}
            )
            second = client.post("/api/runs", json=config.model_dump(mode="json"))
            assert second.status_code == 202, second.text
        finally:
            # A failing regression must still let its real API lifespan close.
            if application.state.supervisor.active_id == admitted["id"]:
                admitted.update(status="failed", scientific_status="incomplete")
                write_json(path, admitted)


def test_evidence_hash_belongs_to_same_snapshot_during_atomic_replacement(tmp_path):
    import wavepacket.validation as validation

    names = (
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
        name: hashlib.sha256(Path(validation.__file__).with_name(name).read_bytes()).hexdigest()
        for name in names
    }
    reports = {
        marker: json.dumps(
            {
                "suite": "full",
                "status": "passed",
                "cases": [],
                "marker": marker,
                "provenance": {"source_sha256": hashes},
            },
            sort_keys=True,
        ).encode()
        for marker in ("A", "B")
    }
    expected = {marker: hashlib.sha256(data).hexdigest() for marker, data in reports.items()}
    path = tmp_path / "results/validation/full/validation.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(reports["A"])
    stop = threading.Event()

    def replace_evidence():
        index = 0
        while not stop.is_set():
            temporary = path.with_suffix(".replacement")
            temporary.write_bytes(reports["AB"[index % 2]])
            try:
                temporary.replace(path)
            except PermissionError:
                # Windows can deny replacement during a reader's open handle.
                continue
            index += 1

    writer = threading.Thread(target=replace_evidence)
    writer.start()
    try:
        with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
            snapshots = 0
            for _ in range(200):
                response = client.get("/api/validation")
                assert response.status_code == 200, response.text
                report = response.json()
                if report["status"] == "not_run":
                    continue
                assert report["freshness"]["report_sha256"] == expected[report["marker"]]
                snapshots += 1
            assert snapshots > 0
    finally:
        stop.set()
        writer.join(timeout=5)
        assert not writer.is_alive()


def test_invalid_owner_timestamp_cannot_prevent_application_startup(tmp_path):
    run_id = "c" * 32
    owner = process_identity()
    owner["create_time"] = 10**1000
    write_json(
        tmp_path / "runs" / run_id / "record.json",
        {
            "id": run_id,
            "status": "running",
            "created_at": "2026-10-28T00:00:00+00:00",
            "config": SimulationConfig().model_dump(mode="json"),
            "owner": owner,
        },
    )
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        record = client.get(f"/api/runs/{run_id}").json()
        assert record["status"] == "failed"
