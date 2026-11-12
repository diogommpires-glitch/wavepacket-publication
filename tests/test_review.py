"""Independent integration checks for scientifically meaningful saved results."""

from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from wavepacket.config import SimulationConfig
from wavepacket.model import initial_state, make_grid
from wavepacket.observables import current
from wavepacket.operators import potential
from wavepacket.runner import frame_payload, read_frame, read_observables, run_simulation


def test_fd2_preview_uses_discrete_face_current():
    config = SimulationConfig.model_validate(
        {
            "grid": {"bounds": [[-8, 8], [-6, 6]], "points": [32, 32]},
            "state": {"center": [0, 0], "momentum": [1.1, 0.4], "sigma": [1, 1]},
            "solver": {"kinetic": "fd2"},
        }
    )
    grid = make_grid(config.grid)
    psi = initial_state(config, grid)
    frame = frame_payload(
        psi, grid, potential(config, grid), 0, {}, 0, 10, max_axis=64, kinetic="fd2"
    )
    expected = current(psi, grid, "fd2")
    np.testing.assert_allclose(frame["current_x"], expected[0], rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(frame["current_y"], expected[1], rtol=1e-6, atol=1e-9)
    assert "half-grid" in frame["current_location"]


@pytest.mark.parametrize("kinetic", ["spectral", "fd2"])
def test_saved_screen_integrates_signed_plane_wave_flux(tmp_path, kinetic):
    # An almost constant envelope makes a resolved periodic plane wave. Its
    # current is independently known; the integrator must retain a final short
    # dt and use every timestep rather than only display snapshots.
    k = 2 * np.pi / 8
    config = SimulationConfig.model_validate(
        {
            "name": "screen-plane-wave",
            "grid": {"bounds": [[-4, 4], [-4, 4]], "points": [32, 32]},
            "state": {"center": [0, 0], "momentum": [float(k), 0], "sigma": [1e8, 1e8]},
            "solver": {"kinetic": kinetic, "dt": 0.03, "duration": 0.1},
            "sampling": {"observable_every": 3, "snapshots": 3, "screen_x": 0.3},
        }
    )
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    with h5py.File(folder / "state.h5") as store:
        assert store["time"][-1] == pytest.approx(0.1)
        index = len(store["time"]) - 1
        integral = store["screen_integral"][-1]
    velocity = k if kinetic == "spectral" else np.sin(k * 0.25) / 0.25
    np.testing.assert_allclose(integral, 0.1 * velocity / 64, atol=1e-12)
    screen = read_frame(folder, index)["screen"]
    assert "signed" in screen["definition"]
    assert abs(screen["x"] - 0.3) <= 0.125 + 1e-12
    if kinetic == "fd2":
        assert screen["x"] - screen["density_x"] == pytest.approx(0.125)


def test_saved_cap_frame_retains_the_explicit_loss_ledger(tmp_path):
    config = SimulationConfig.model_validate(
        {
            "grid": {"bounds": [[-10, 10]], "points": [128]},
            "state": {"center": [5], "momentum": [3], "sigma": [1]},
            "solver": {"dt": 0.05, "duration": 0.5},
            "boundary": {"kind": "cap", "width": 3, "strength": 2},
            "sampling": {"snapshots": 3, "observable_every": 10},
        }
    )
    record = run_simulation(config, tmp_path)
    folder = Path(record["path"])
    frame = read_frame(folder, 2)
    final = record["summary"]["final"]
    assert final["absorbed_probability"] > 0
    assert frame["observables"]["absorbed_probability"] == pytest.approx(
        final["absorbed_probability"]
    )
    assert frame["observables"]["probability_budget_residual"] == pytest.approx(
        final["probability_budget_residual"]
    )


def test_cancellation_flushes_current_checkpoint_and_diagnostics(tmp_path):
    config = SimulationConfig.model_validate(
        {
            "grid": {"points": [64]},
            "solver": {"dt": 0.04, "duration": 0.2},
            "sampling": {"snapshots": 2, "observable_every": 10},
        }
    )
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls == 3

    record = run_simulation(config, tmp_path, cancelled=cancelled)
    folder = Path(record["path"])
    assert record["status"] == "cancelled"
    with h5py.File(folder / "state.h5") as store:
        assert store.attrs["completed_time"] == pytest.approx(0.08)
        assert store["time"][-1] == pytest.approx(0.08)
    assert record["summary"]["final"]["time"] == pytest.approx(0.08)
    assert read_observables(folder)[-1]["time"] == pytest.approx(0.08)


def test_worker_start_failure_is_persisted_and_releases_resources(tmp_path, monkeypatch):
    from wavepacket.api import RunManager

    class BrokenProcess:
        def start(self):
            raise OSError("simulated worker startup failure")

        def is_alive(self):
            return False

    manager = RunManager(tmp_path)
    context = manager.context
    monkeypatch.setattr(
        manager,
        "context",
        SimpleNamespace(
            Event=context.Event,
            Pipe=context.Pipe,
            Process=lambda **kwargs: BrokenProcess(),
        ),
    )
    with pytest.raises(OSError, match="simulated worker"):
        manager.start(SimulationConfig())
    assert manager.active_id is None and manager.process is None
    assert manager.event is None
    assert len(manager.records) == 1
    record = next(iter(manager.records.values()))
    assert record["status"] == "failed"
    assert (manager.folder(record["id"]) / "record.json").is_file()
    manager.close()
