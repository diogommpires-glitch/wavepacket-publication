from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from wavepacket.config import SimulationConfig
from wavepacket.runner import compare_runs, load_run, read_frame, run_simulation


def tiny_config(dimension=1):
    data = {"grid": {"bounds": [[-12, 12]] * dimension, "points": [64] * dimension},
            "state": {"center": [-2] * dimension, "momentum": [1] * dimension, "sigma": [1] * dimension},
            "solver": {"dt": .01, "duration": .1}, "sampling": {"snapshots": 5, "observable_every": 2}}
    return SimulationConfig.model_validate(data)


def test_artifact_roundtrip_preserves_complex_state_and_provenance(tmp_path):
    config = tiny_config()
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    loaded = load_run(folder)
    assert loaded["config"] == config
    assert record["status"] == "completed"
    with h5py.File(folder / "state.h5") as store:
        assert store["psi"].dtype == np.dtype("complex128")
        assert store["psi"].shape == (5, 64)
        assert np.linalg.norm(store["psi"][-1].imag) > 0
        assert store["time"][-1] == .1
    manifest = json.loads((folder / "manifest.json").read_text())
    assert len(manifest["artifact_sha256"]["state.h5"]) == 64
    assert len(manifest["source_sha256"]["propagators.py"]) == 64
    assert "norm" in loaded["observables"][0]
    assert not (folder / "state.h5.partial").exists()
    report = (folder / "report.html").read_text(encoding="utf-8")
    assert " | Wavepacket report</title>" in report
    assert "WAVEPACKET / REPRODUCIBLE RUN REPORT" in report


def test_replay_axes_and_preview_downsampling_do_not_change_full_norm(tmp_path):
    config = tiny_config(2)
    record = run_simulation(config, tmp_path)
    frame = read_frame(Path(record["path"]), 4, max_axis=16)
    assert frame["shape"] == [16, 16]
    assert len(frame["axes"]["x"]) == 16
    assert len(frame["density"]) == 16
    assert abs(frame["observables"]["norm"] - 1) < 1e-12
    assert "current_x" in frame and "current_y" in frame


def test_cancelled_run_keeps_only_valid_samples_and_is_not_success(tmp_path):
    record = run_simulation(tiny_config(), tmp_path, cancelled=lambda: True)
    assert record["status"] == "cancelled"
    folder = Path(record["path"])
    with h5py.File(folder / "state.h5") as store:
        assert len(store["time"]) == 1
        assert store.attrs["status"] == "cancelled"
    assert compare_runs([folder])["all_completed"] is False


def test_last_short_step_reaches_requested_time(tmp_path):
    config = tiny_config().model_copy(update={"solver": tiny_config().solver.model_copy(update={"duration": .105})})
    record = run_simulation(config, tmp_path)
    with h5py.File(Path(record["path"]) / "state.h5") as store:
        assert store["time"][-1] == .105


@pytest.mark.parametrize("format_version", [1, 2])
def test_final_short_step_replay_retains_completed_step(tmp_path, format_version):
    data = tiny_config().model_dump(mode="json")
    data["solver"].update(dt=.02, duration=.021)
    data["sampling"]["snapshots"] = 3
    config = SimulationConfig.model_validate(data)
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    if format_version == 1:
        with h5py.File(folder / "state.h5", "r+") as store:
            store.attrs["format_version"] = 1
            del store["diagnostics_json"]
    frame = read_frame(folder, 2)
    assert frame["time"] == .021
    assert frame["step"] == frame["total_steps"] == 2

