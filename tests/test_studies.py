import numpy as np
import pytest

from wavepacket.config import SimulationConfig, config_fingerprint
from wavepacket.experiments import get_experiment
from wavepacket.model import initial_state, make_grid
from wavepacket.observables import measurement_validity, waveguide_mode_content
from wavepacket.studies import _coherent, _freeze, accuracy_cost_protocol, target_attainment
from wavepacket.validation import (
    _double_well,
    gaussian_transmission_reference,
    propagate,
    state_error,
)


def test_frozen_protocol_and_exact_config_identity(tmp_path):
    protocol = accuracy_cost_protocol()
    digest = _freeze(protocol, tmp_path)
    assert len(digest) == 64
    assert _freeze(protocol, tmp_path) == digest
    with pytest.raises(ValueError, match="frozen study protocol differs"):
        _freeze({**protocol, "seed": 3}, tmp_path)
    for panel in protocol["panels"]:
        config = SimulationConfig.model_validate(panel["config"])
        assert config.boundary.kind == "periodic"
        for method in panel["methods"]:
            data = config.model_dump()
            data["solver"]["method"] = method
            assert SimulationConfig.model_validate(data).grid == config.grid
    data = config.model_dump()
    data["name"] += "-edited"
    assert config_fingerprint(config) != config_fingerprint(SimulationConfig.model_validate(data))


def test_rotated_analytic_reference_preserves_global_dynamical_phase():
    config = SimulationConfig.model_validate(accuracy_cost_protocol()["panels"][2]["config"])
    grid = make_grid(config.grid)
    assert state_error(_coherent(config, 0), initial_state(config, grid), grid) < 1e-12
    data = config.model_dump()
    data["solver"].update(method="yoshida4", dt=0.001)
    state, _, _ = propagate(SimulationConfig.model_validate(data))
    assert state_error(state, _coherent(config, 1), grid) < 1e-9


def test_unattained_targets_are_explicit_and_raw_error_is_primary():
    rows = [{"method": "cn", "dt": 0.1, "raw_l2_error": 1e-4,
             "phase_aligned_l2_error": 1e-10, "warm_total_median_seconds": 0.01}]
    result = target_attainment(rows, [1e-3, 1e-7])
    assert result[0]["status"] == "attained"
    assert result[1]["status"] == "unattained_on_frozen_sweep"
    assert result[1]["best_timestep"] is None


def test_narrow_resonance_reference_refines_scan_and_crosschecks_quadrature():
    result = gaussian_transmission_reference(1.8744, 6, [(2.5, 1), (0, 4), (2.5, 1)], accuracy_target=1e-7)
    assert len(result["momentum_scan"]) >= 2
    assert result["reference_disagreement"] < min(1e-8, 1e-7 / 10)
    assert any(abs(k - 1.8744) < 0.001 for k in result["detected_resonance_momenta"])
    assert 0 < result["weighted_transmission"] < 1
    assert np.isfinite(result["quadrature_error_estimate"])


def test_double_well_gap_converges_beyond_eigensolver_residual():
    result = _double_well()
    assert result["status"] == "passed", result
    assert result["metrics"]["maximum_residual_over_gap"] < 1e-7
    assert len(result["metrics"]["gap_convergence"]) == 6


def test_straight_guide_projection_and_disjoint_mass_partition():
    data = get_experiment("2d-waveguide").model_dump()
    data["potential"]["params"]["angle"] = 0.0
    data["state"]["center"] = [10.0, 0.0]
    config = SimulationConfig.model_validate(data)
    grid = make_grid(config.grid)
    content = waveguide_mode_content(config, initial_state(config, grid), grid,
                                     longitudinal_window=(4.0, 16.0))
    assert content["mode_fractions_in_window"][0] > 0.999
    assert sum(content["mode_fractions_in_window"][1:]) < 1e-5
    assert content["partition_error"] < 1e-12
    assert content["window_probability"] > 0.99
    assert abs(sum(content["mode_probabilities"]) + content["unresolved_window_probability"]
               - content["window_probability"]) < 1e-12


def test_periodic_and_nyquist_states_qualify_line_uncertainty():
    config = SimulationConfig.model_validate(accuracy_cost_protocol()["panels"][0]["config"])
    grid = make_grid(config.grid)
    plane = np.ones(grid.shape, complex)/np.sqrt(16)
    assert measurement_validity(plane, grid)["uncertainty_status"] == "boundary_or_nyquist_contaminated"
    localized = initial_state(config, grid)
    assert measurement_validity(localized, grid)["uncertainty_status"] == "localized_line_approximation"
