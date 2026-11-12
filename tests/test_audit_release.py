"""Release failure paths must settle processes they started before deleting data."""

import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from scripts import check_browser
from wavepacket.api import create_app
from wavepacket.config import SimulationConfig, config_fingerprint
from wavepacket.studies import (
    THREAD_VARIABLES,
    accuracy_cost_protocol,
    target_attainment,
    tunnelling_protocol,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import verify_release  # noqa: E402


def test_release_wheel_probe_can_read_the_loopback_api(tmp_path):
    # Execute the embedded client construction without requiring an installed wheel.
    expression = next(
        node
        for node in ast.walk(ast.parse(verify_release.WHEEL_PROBE))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TestClient"
    )
    context = {"TestClient": TestClient, "create_app": create_app, "Path": Path, "data": tmp_path}
    with eval(compile(ast.Expression(expression), "<wheel-probe>", "eval"), context) as client:
        response = client.get("/api/storage")
        assert response.status_code == 200, response.text
        assert response.json()["data_dir"] == str(tmp_path.resolve())


@pytest.mark.skipif(shutil.which("node") is None, reason="browser launcher requires Node")
def test_failed_browser_stops_its_real_active_worker(tmp_path, monkeypatch):
    tests = tmp_path / "frontend/tests"
    tests.mkdir(parents=True)
    (tests / "browser.mjs").write_text(
        """import {writeFile} from 'node:fs/promises';
const config = {
  grid: {bounds: [[-24,24],[-18,18]], points: [256,192]},
  state: {center: [-6,-4], momentum: [1,.5], sigma: [1.5,1.5]},
  solver: {duration: 100, dt: .001}, sampling: {snapshots: 2}
};
const response = await fetch(process.env.WAVEPACKET_URL + '/api/runs', {
  method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(config)
});
const record = await response.json();
if (response.status !== 202) throw new Error(JSON.stringify(record));
await writeFile('admitted-run.json', JSON.stringify(record));
process.exit(1);
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_browser, "ROOT", tmp_path)
    result, raised = None, None
    try:
        result = check_browser.main()
    except OSError as error:
        raised = error
    record = json.loads((tmp_path / "admitted-run.json").read_text(encoding="utf-8"))
    owner = record["owner"]
    alive = False
    try:
        process = psutil.Process(owner["pid"])
        alive = abs(process.create_time() - owner["create_time"]) < 0.01 and process.is_running()
        if alive:
            # The regression must not leak the real worker it deliberately starts.
            process.terminate()
            process.wait(timeout=10)
    except psutil.NoSuchProcess:
        pass
    assert not alive, "The failed browser left its owned numerical worker alive"
    assert raised is None, f"Temporary run data could not be cleaned up: {raised}"
    assert result == 1
    assert (tests / "artifacts/server.log").is_file()


def write_study_metadata(root):
    """Write report-contract fixtures; no generated measurement is scientific evidence."""
    source = Path(__file__).resolve().parents[1] / "src/wavepacket"
    destination = root / "src/wavepacket"
    destination.mkdir(parents=True)
    hashes = {}
    for name in verify_release.SCIENCE_SOURCES | {"studies.py"}:
        content = (source / name).read_bytes()
        (destination / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    for name, builder in (
        ("accuracy-cost", accuracy_cost_protocol),
        ("tunnelling", tunnelling_protocol),
    ):
        directory = root / "results/studies" / name
        directory.mkdir(parents=True)
        protocol = builder()
        canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False)
        protocol_hash = hashlib.sha256(canonical.encode()).hexdigest()
        report = {
            "study": name,
            "status": "measured",
            "protocol_sha256": protocol_hash,
            "provenance": {
                "source_sha256": hashes,
                "source_sha256_at_start": hashes,
                "sources_changed_during_run": [],
            },
            "environment": {"threads": dict.fromkeys(THREAD_VARIABLES, "1")},
        }
        if name == "accuracy-cost":
            panels = []
            for panel in protocol["panels"]:
                measurements = []
                for method in panel["methods"]:
                    for dt in panel["timesteps"]:
                        config = SimulationConfig.model_validate(panel["config"]).model_dump()
                        config["solver"].update(method=method, dt=dt)
                        resolved = SimulationConfig.model_validate(config)
                        measurements.append(
                            {
                                "method": method,
                                "dt": dt,
                                "config": resolved.model_dump(mode="json"),
                                "configuration_sha256": config_fingerprint(resolved),
                                "warm_timings": [{"total_seconds": 1.0}] * protocol["repeats"],
                                "raw_l2_error": 1e-4,
                                "warm_total_median_seconds": 1.0,
                            }
                        )
                panels.append(
                    {
                        "id": panel["id"],
                        "measurements": measurements,
                        "target_attainment": target_attainment(
                            measurements, protocol["accuracy_targets_raw_l2"]
                        ),
                    }
                )
            report["panels"] = panels
        else:
            report["packets"] = [
                {"momentum": momentum, "sigma": sigma}
                for momentum in protocol["momentum_centers"]
                for sigma in protocol["density_sigma"]
            ]
            report["refinement"] = [{"axis": axis} for axis in ("space", "time", "domain")]
        (directory / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
        (directory / "protocol.sha256").write_text(protocol_hash, encoding="utf-8")
        (directory / "results.json").write_text(json.dumps(report), encoding="utf-8")


@pytest.mark.parametrize(
    "corruption", ["missing", "source", "invalidated", "protocol", "repetitions"]
)
def test_release_rejects_missing_stale_or_incomplete_primary_study(tmp_path, corruption):
    write_study_metadata(tmp_path)
    assert set(verify_release.inspect_studies(tmp_path)) == {"accuracy-cost", "tunnelling"}
    directory = tmp_path / "results/studies/accuracy-cost"
    path = directory / "results.json"
    if corruption == "missing":
        path.unlink()
    elif corruption == "source":
        with (tmp_path / "src/wavepacket/studies.py").open("ab") as stream:
            stream.write(b"\n# Changed after measurement.\n")
    else:
        report = json.loads(path.read_text(encoding="utf-8"))
        if corruption == "invalidated":
            report["status"] = "invalidated_by_source_changes"
        elif corruption == "protocol":
            report["protocol_sha256"] = "0" * 64
        else:
            report["panels"][0]["measurements"][0]["warm_timings"].pop()
        path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_release.inspect_studies(tmp_path)


@pytest.mark.parametrize("duplicate", ["accuracy", "packet", "refinement"])
def test_release_requires_each_unique_frozen_study_case(tmp_path, duplicate):
    write_study_metadata(tmp_path)
    assert set(verify_release.inspect_studies(tmp_path)) == {"accuracy-cost", "tunnelling"}
    name = "accuracy-cost" if duplicate == "accuracy" else "tunnelling"
    path = tmp_path / "results/studies" / name / "results.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if duplicate == "accuracy":
        rows = report["panels"][0]["measurements"]
        rows[-1] = rows[0]
    elif duplicate == "packet":
        report["packets"][-1] = report["packets"][0]
    else:
        report["refinement"].append(report["refinement"][0])
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_release.inspect_studies(tmp_path)
