import math

import numpy as np
import pytest
from scipy.linalg import expm

from wavepacket.config import SimulationConfig
from wavepacket.model import eigenbasis, initial_state, make_grid, normalise
from wavepacket.observables import current, measure, norm, state_errors
from wavepacket.operators import absorber, apply_hamiltonian, potential
from wavepacket.propagators import make_stepper


def setup(patch):
    config = SimulationConfig.model_validate(patch)
    grid = make_grid(config.grid)
    V, W = potential(config, grid), absorber(config, grid)
    psi = initial_state(config, grid)
    return config, grid, V, W, psi, make_stepper(config, grid, V, W)


def evolve(stepper, state, dt, duration):
    for _ in range(round(duration / dt)):
        state = stepper(state, dt)
    return state


def test_physical_axis_order_and_shape():
    _, grid, _, _, psi, _ = setup({"grid": {"bounds": [[-8, 8], [-5, 5]], "points": [64, 32]},
                                  "state": {"center": [1, -1], "momentum": [0, 0], "sigma": [.5, .4]}})
    assert grid.array_shape == (32, 64)
    assert grid.mesh[0][3, 4] == grid.axes[0][4]
    assert grid.mesh[1][3, 4] == grid.axes[1][3]
    assert grid.axes[0][-1] < 8
    assert norm(psi, grid) == pytest.approx(1)
    metrics = measure(psi, grid, np.zeros(grid.shape))
    assert metrics["x_mean"] == pytest.approx(1, abs=1e-10)
    assert metrics["y_mean"] == pytest.approx(-1, abs=1e-10)


def test_free_gaussian_matches_complex_analytic_solution():
    config, grid, V, _, psi, stepper = setup({})
    result = evolve(stepper, psi, .02, 2)
    x = grid.axes[0]
    sigma, x0, k, time = 2, -10, 2, 2
    gamma = 1 + 1j * time / (2 * sigma ** 2)
    reference = ((2 * np.pi * sigma ** 2) ** -.25 / np.sqrt(gamma)
                 * np.exp(-(x - x0 - k * time) ** 2 / (4 * sigma ** 2 * gamma)
                          + 1j * k * (x - x0 - k * time / 2)))
    assert state_errors(result, reference, grid)["raw_l2"] < 1e-12
    assert abs(norm(result, grid) - 1) < 1e-12


@pytest.mark.parametrize("method,kinetic,expected_order", [("strang", "fd2", 2), ("cn", "fd2", 2), ("yoshida4", "fd2", 4)])
def test_time_order_against_independent_discrete_hamiltonian(method, kinetic, expected_order):
    config, grid, V, _, initial, stepper = setup({
        "grid": {"bounds": [[-8, 8]], "points": [64]},
        "state": {"center": [.8], "momentum": [.4], "sigma": [.8]},
        "potential": {"kind": "harmonic", "params": {"omega": [1]}},
        "solver": {"method": method, "kinetic": kinetic, "dt": .04, "duration": .4}})
    n, dx = grid.points[0], grid.spacing[0]
    H = np.diag(np.ones(n) / dx ** 2 + V).astype(complex)
    for i in range(n):
        H[i, (i + 1) % n] -= .5 / dx ** 2
        H[i, (i - 1) % n] -= .5 / dx ** 2
    reference = expm(-.4j * H) @ initial
    errors = [state_errors(evolve(stepper, initial, dt, .4), reference, grid)["raw_l2"]
              for dt in (.04, .02, .01)]
    orders = np.log2(np.array(errors[:-1]) / errors[1:])
    assert np.all(np.abs(orders - expected_order) < .12), (errors, orders)


@pytest.mark.parametrize("method,kinetic", [("strang", "spectral"), ("yoshida4", "spectral"), ("cn", "fd2")])
def test_reversibility_norm_and_input_not_mutated(method, kinetic):
    _, grid, _, _, initial, stepper = setup({"solver": {"method": method, "kinetic": kinetic},
                                            "potential": {"kind": "gaussian", "params": {"height": 2}}})
    untouched = initial.copy()
    result = evolve(stepper, initial, .02, .4)
    returned = evolve(stepper, result, -.02, -.4)
    assert np.array_equal(initial, untouched)
    assert norm(result, grid) == pytest.approx(1, abs=1e-12)
    assert state_errors(returned, initial, grid)["raw_l2"] < 2e-12


def test_cap_loss_budget_and_negative_step_rejected():
    _, grid, _, _, psi, stepper = setup({"grid": {"bounds": [[-10, 10]], "points": [256]},
                                        "state": {"center": [5], "sigma": [1], "momentum": [3]},
                                        "boundary": {"kind": "cap", "width": 3, "strength": 2},
                                        "solver": {"duration": 2, "dt": .01}})
    previous = norm(psi, grid)
    for _ in range(200):
        psi = stepper(psi)
        value = norm(psi, grid)
        assert value <= previous + 1e-14
        previous = value
    assert stepper.total_absorbed > .3
    assert norm(psi, grid) + stepper.total_absorbed == pytest.approx(1, abs=1e-12)
    assert stepper.absorbed_density.sum() * grid.cell_volume == pytest.approx(stepper.total_absorbed)
    with pytest.raises(ValueError, match="negative"):
        stepper(psi, -.01)


def test_fd2_symbol_and_current_satisfy_discrete_continuity():
    _, grid, V, _, psi, _ = setup({"grid": {"bounds": [[-8, 8], [-6, 6]], "points": [64, 32]},
                                  "state": {"center": [0, 0], "momentum": [1, .5], "sigma": [1, 1]}})
    rhs = -1j * apply_hamiltonian(psi, grid, V, "fd2")
    density_derivative = 2 * np.real(np.conj(psi) * rhs)
    currents = current(psi, grid, "fd2")
    divergence = sum((j - np.roll(j, 1, axis=-1 - i)) / dx
                     for i, (j, dx) in enumerate(zip(currents, grid.spacing, strict=True)))
    assert np.max(np.abs(density_derivative + divergence)) < 1e-13


def test_eigenstates_use_selected_hamiltonian_and_weighted_norm():
    config, grid, V, _, _, _ = setup({"grid": {"bounds": [[-8, 8]], "points": [128]},
                                      "state": {"center": [0], "momentum": [0]},
                                      "potential": {"kind": "harmonic", "params": {"omega": [1]}}})
    values, states = eigenbasis(config, grid, 2)
    assert values == pytest.approx([.5, 1.5], abs=1e-10)
    assert norm(states[0], grid) == pytest.approx(1)
    for energy, psi in zip(values, states, strict=True):
        residual = apply_hamiltonian(psi, grid, V) - energy * psi
        assert np.linalg.norm(residual) * math.sqrt(grid.cell_volume) < 1e-9


def test_global_phase_error_is_reported_separately():
    _, grid, _, _, psi, _ = setup({})
    errors = state_errors(psi * np.exp(.7j), psi, grid)
    assert errors["raw_l2"] > .5
    assert errors["phase_aligned_l2"] < 1e-15
    assert errors["fidelity"] == pytest.approx(1)


def test_chirped_gaussian_covariance_and_uncertainty():
    _, grid, V, _, psi, _ = setup({"state": {"center": [0], "momentum": [1], "sigma": [2], "params": {"chirp": [.3]}}})
    metrics = measure(psi, grid, V)
    # psi = exp(-x²/(4 sigma²) + i c x²/2): Cov(x,p)=c sigma².
    assert metrics["x_px_covariance"] == pytest.approx(1.2, abs=1e-12)
    assert metrics["px_variance"] == pytest.approx(1 / 16 + .3 ** 2 * 4, abs=1e-12)
    assert metrics["x_px_robertson"] == pytest.approx(.25, abs=1e-12)
    assert metrics["high_k_fraction"] < 1e-25


def test_rotated_oscillator_position_covariance():
    angle = np.pi / 6
    _, grid, V, _, psi, _ = setup({"grid": {"bounds": [[-10, 10], [-10, 10]], "points": [128, 128]},
                                  "state": {"kind": "ho_coherent", "center": [0, 0], "momentum": [0, 0],
                                            "params": {"omega": [1, 1.5], "angle": float(angle)}},
                                  "potential": {"kind": "harmonic", "params": {"omega": [1, 1.5], "angle": float(angle)}}})
    metrics = measure(psi, grid, V)
    assert metrics["x_y_covariance"] == pytest.approx(np.cos(angle) * np.sin(angle) * (.5 - 1 / 3), abs=1e-12)
    assert metrics["energy"] == pytest.approx(1.25, abs=1e-12)


@pytest.mark.parametrize("factor", [1e-200, 1e200, 1e200 * (1 + 1j)])
def test_initial_normalisation_is_invariant_to_common_coefficient_scale(factor):
    config, grid, _, _, reference, _ = setup({"state": {"center": [0], "momentum": [1], "sigma": [1]}})
    data = config.model_dump()
    data["state"] = {"kind": "sum", "params": {"components": [
        {"state": config.state.model_dump(), "amplitude": [float(complex(factor).real), float(complex(factor).imag)]},
    ]}}
    actual = initial_state(SimulationConfig.model_validate(data), grid)
    expected = reference * np.exp(1j * np.angle(factor))
    assert norm(actual, grid) == pytest.approx(1, abs=2e-14)
    np.testing.assert_allclose(actual, expected, atol=2e-15)


def test_direct_normalisation_handles_finite_large_complex_components():
    grid = make_grid(SimulationConfig().grid)
    state = np.full(grid.shape, complex(1.6e308, 1.6e308))
    actual = normalise(state, grid)
    assert norm(actual, grid) == pytest.approx(1, abs=2e-14)
    assert np.angle(actual[0]) == pytest.approx(np.pi / 4)


def test_destructive_superposition_cancellation_is_rejected():
    data = {"state": {"kind": "sum", "params": {"components": [
        {"state": {"center": [0]}, "amplitude": 1e200},
        {"state": {"center": [0]}, "amplitude": -1e200},
    ]}}}
    config = SimulationConfig.model_validate(data)
    with pytest.raises(ValueError, match="zero"):
        initial_state(config, make_grid(config.grid))


@pytest.mark.parametrize("points", [8192, 32768])
def test_sparse_cn_supports_advertised_large_grids(points):
    _, grid, _, _, initial, stepper = setup({"grid": {"points": [points]},
        "solver": {"method": "cn", "kinetic": "fd2", "dt": .01, "duration": .02},
        "sampling": {"snapshots": 2}})
    actual = stepper(initial)
    assert np.all(np.isfinite(actual))
    assert norm(actual, grid) == pytest.approx(1, abs=2e-12)


def test_zero_and_tiny_surviving_states_withhold_conditional_observables():
    from wavepacket.observables import measurement_validity
    _, grid, V, _, state, _ = setup({})
    for factor, status in [(0, "numerically_zero"), (1e-8, "below_reporting_floor")]:
        metrics = measure(state * factor, grid, V)
        assert metrics["energy"] is None
        assert metrics["x_mean"] is None
        assert metrics["x_px_uncertainty"] is None
        assert metrics["norm"] == pytest.approx(factor ** 2, abs=1e-30)
        validity = measurement_validity(state * factor, grid)
        assert validity["conditional_status"] == status
        assert validity["reporting_floor"] == pytest.approx(64 * np.finfo(float).eps)
    errors = state_errors(state * 0, state, grid)
    assert errors["fidelity"] is None
    assert errors["relative_phase"] is None
    assert errors["raw_l2"] == pytest.approx(1)
