import json

import numpy as np
import pytest

from wavepacket.model import initial_state, make_grid
from wavepacket.validation import (
    _temporal_order,
    fixture,
    packet_transmission_reference,
    run_validation,
    stationary_transmission,
)


def test_quick_scientific_suite_and_artifact(tmp_path):
    report = run_validation("quick", tmp_path)
    assert report["status"] == "passed", report
    assert report["summary"] == {"passed": 7, "failed": 0, "total": 7}
    assert report["not_run"]  # Quick never pretends it ran the complete study.
    saved = json.loads((tmp_path / "validation.json").read_text())
    assert saved["summary"] == report["summary"]
    assert report["provenance"]["sources_changed_during_run"] == []
    assert len(report["provenance"]["source_sha256"]["validation.py"]) == 64
    assert all(case["configurations"] for case in report["cases"])


@pytest.mark.parametrize("method,kinetic", [("strang", "spectral"), ("strang", "fd2"), ("cn", "fd2"), ("yoshida4", "spectral")])
def test_integrator_orders_against_fixed_independent_hamiltonian(method, kinetic):
    result = _temporal_order(method, kinetic)
    assert result["status"] == "passed", result


def test_stable_scattering_matrix_matches_closed_form_single_barrier():
    k = np.array([0.3, 1.0, 1.7, 2.5, 4.0])
    height, width = 2.0, 1.3
    energy = k**2 / 2
    expected = np.empty_like(k)
    below = energy < height
    expected[below] = 1 / (1 + height**2 * np.sinh(np.sqrt(2 * (height - energy[below])) * width)**2 / (4 * energy[below] * (height - energy[below])))
    expected[~below] = 1 / (1 + height**2 * np.sin(np.sqrt(2 * (energy[~below] - height)) * width)**2 / (4 * energy[~below] * (energy[~below] - height)))
    assert np.allclose(stationary_transmission(k, [(height, width)]), expected, rtol=1e-10, atol=1e-12)
    assert stationary_transmission(np.array([1.0]), [(100.0, 100.0)])[0] < 1e-100


def test_packet_reference_accounts_for_bandwidth():
    config = fixture()
    grid = make_grid(config.grid)
    result = packet_transmission_reference(initial_state(config, grid), grid, [(2.5, 2.0)])
    assert 0 <= result["weighted_transmission"] <= 1
    assert result["initial_negative_momentum_mass"] < 1e-10
    assert not np.isclose(result["weighted_transmission"], stationary_transmission(np.array([2.0]), [(2.5, 2.0)])[0], rtol=0.01)


def test_invalid_suite_rejected():
    with pytest.raises(ValueError):
        run_validation("unknown")
