"""Catalogue regression tests: smoke runs are not scientific certification."""
import json

import numpy as np
import pytest

from wavepacket.config import SimulationConfig
from wavepacket.experiments import get_experiment, list_experiments, write_examples
from wavepacket.model import initial_state, make_grid
from wavepacket.operators import absorber, potential
from wavepacket.propagators import make_stepper


def test_sixteen_curated_experiments_have_traceable_questions():
    entries = list_experiments()
    assert len(entries) == len({entry["id"] for entry in entries}) == 16
    assert sum(entry["dimension"] == 1 for entry in entries) == 8
    assert sum(entry["dimension"] == 2 for entry in entries) == 8
    for entry in entries:
        assert entry["scientific_question"] and entry["evidence"] and entry["limitations"]
        assert len(get_experiment(entry["id"]).grid.points) == entry["dimension"]
    entries[0]["config"]["name"] = "mutated"
    assert get_experiment("1d-free").name == "1d-free"


@pytest.mark.parametrize("identifier", [entry["id"] for entry in list_experiments()])
def test_all_presets_initialise_and_step_at_explicit_smoke_resolution(identifier):
    data = get_experiment(identifier).model_dump()
    data["grid"]["points"] = [64] if len(data["grid"]["points"]) == 1 else [32, 32]
    data["solver"].update(duration=0.02, dt=0.01)
    data["sampling"]["snapshots"] = 2
    config = SimulationConfig.model_validate(data)
    grid = make_grid(config.grid)
    values, loss = potential(config, grid), absorber(config, grid)
    psi = initial_state(config, grid)
    assert np.isclose(np.vdot(psi, psi).real * grid.cell_volume, 1)
    result = make_stepper(config, grid, values, loss)(psi)
    assert result.shape == grid.shape and np.isfinite(result).all()


def test_slit_and_obstacle_geometry_is_present_at_default_resolution():
    config = get_experiment("2d-double-slit")
    grid = make_grid(config.grid)
    values = potential(config, grid)
    ix = np.argmin(abs(grid.axes[0]))
    for center in (-3.0, 3.0):
        iy = np.argmin(abs(grid.axes[1] - center))
        assert values[iy, ix] < 0.2 * 30
    assert values[np.argmin(abs(grid.axes[1])), ix] > 0.8 * 30
    obstacle = get_experiment("2d-obstacle")
    field = potential(obstacle, grid)
    assert field[np.argmin(abs(grid.axes[1])), ix] > 0.9 * 20
    assert field[0, 0] < 1e-5


def test_examples_roundtrip(tmp_path):
    paths = write_examples(tmp_path)
    assert len(paths) == 16
    for path in paths:
        assert SimulationConfig.model_validate_json(path.read_text()).name == path.stem
    assert len(json.loads((tmp_path / "catalogue.json").read_text())) == 16


def test_unknown_preset_is_an_error():
    with pytest.raises(KeyError):
        get_experiment("not-a-preset")
