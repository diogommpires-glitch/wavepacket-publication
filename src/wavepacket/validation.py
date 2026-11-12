"""Executable scientific checks with independent references and explicit evidence.

The quick suite is suitable for development; the full suite also performs
scattering, absorber, domain and spatial-resolution studies.  A failed check is
recorded, never silently omitted or converted into an unchecked pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import tempfile
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from scipy.integrate import quad, simpson
from scipy.linalg import eigh, expm
from scipy.signal import find_peaks
from scipy.special import erfc

from .config import SimulationConfig, config_fingerprint
from .model import Grid, eigenbasis, initial_state, make_grid, normalise
from .observables import waveguide_mode_content
from .operators import absorber, apply_hamiltonian, potential
from .propagators import make_stepper

_CASE_CONFIGS: ContextVar[list[dict] | None] = ContextVar("validation_configs", default=None)


def _record_config(config: SimulationConfig, **overrides: np.ndarray | None) -> SimulationConfig:
    records = _CASE_CONFIGS.get()
    if records is None:
        return config
    data = config.model_dump(mode="json")
    arrays = {}
    for name, value in overrides.items():
        if value is None:
            continue
        array = np.ascontiguousarray(value)
        description = {"shape": list(array.shape), "dtype": str(array.dtype),
                       "sha256": hashlib.sha256(array.tobytes()).hexdigest()}
        if array.size <= 1024:
            description["real"] = array.real.tolist()
            if np.iscomplexobj(array):
                description["imaginary"] = array.imag.tolist()
        arrays[name] = description
    record = {"configuration": data, "overrides": arrays}
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if not any(item["sha256"] == digest for item in records):
        records.append({"sha256": digest, **record})
    return config


def fixture(*, ndim: int = 1, points: int = 512, length: float = 80.0,
            duration: float = 2.0, dt: float = 0.02, method: str = "strang",
            kinetic: str = "spectral", state: dict | None = None,
            potential_spec: dict | None = None, boundary: dict | None = None) -> SimulationConfig:
    return _record_config(SimulationConfig.model_validate({
        "name": "validation-fixture", "grid": {"bounds": [[-length / 2, length / 2]] * ndim, "points": [points] * ndim},
        "state": state or {"kind": "gaussian", "center": [-10.0] if ndim == 1 else [-6.0, -4.0],
                           "momentum": [2.0] if ndim == 1 else [1.0, 0.5], "sigma": [2.0] if ndim == 1 else [1.5, 1.5]},
        "potential": potential_spec or {"kind": "free"},
        "solver": {"method": method, "kinetic": kinetic, "dt": dt, "duration": duration},
        "boundary": boundary or {"kind": "periodic"}, "sampling": {"snapshots": 2, "observable_every": 100},
    }))


def probability(psi: np.ndarray, grid: Grid) -> float:
    return float(np.vdot(psi, psi).real * grid.cell_volume)


def state_error(actual: np.ndarray, reference: np.ndarray, grid: Grid, *, align: bool = False) -> float:
    if align:
        overlap = np.vdot(reference, actual)
        reference = reference * np.exp(1j * np.angle(overlap))
    return float(np.linalg.norm((actual - reference).ravel()) * math.sqrt(grid.cell_volume))


def propagate(config: SimulationConfig, psi: np.ndarray | None = None,
              values: np.ndarray | None = None) -> tuple[np.ndarray, Grid, dict[str, float]]:
    """Small headless loop deliberately independent of the artifact/UI runner."""
    _record_config(config, initial_state=psi, potential=values)
    grid = make_grid(config.grid)
    values = potential(config, grid) if values is None else values
    psi = initial_state(config, grid) if psi is None else np.asarray(psi, complex).copy()
    norm0 = probability(psi, grid)
    energy0 = float((np.vdot(psi, apply_hamiltonian(psi, grid, values, config.solver.kinetic)) * grid.cell_volume).real)
    minimum, maximum = norm0, norm0
    step = make_stepper(config, grid, values, absorber(config, grid))
    now = 0.0
    for _ in range(config.n_steps):
        dt = min(config.solver.dt, config.solver.duration - now)
        psi = step(psi, dt)
        now += dt
        norm = probability(psi, grid)
        minimum, maximum = min(minimum, norm), max(maximum, norm)
    energy = float((np.vdot(psi, apply_hamiltonian(psi, grid, values, config.solver.kinetic)) * grid.cell_volume).real)
    return psi, grid, {"initial_norm": norm0, "final_norm": probability(psi, grid),
                       "initial_energy_unconditional": energy0, "final_energy_unconditional": energy,
                       "relative_energy_change": abs(energy - energy0) / max(1.0, abs(energy0)),
                       "max_norm_drift": max(abs(maximum - norm0), abs(minimum - norm0)), "time": now,
                       "absorbed_probability": step.total_absorbed,
                       "norm_absorption_budget_error": abs(probability(psi, grid) + step.total_absorbed - norm0)}


def analytic_free(grid: Grid, center: list[float], momentum: list[float],
                  sigma: list[float], t: float) -> np.ndarray:
    """Infinite-line Gaussian, density-SD convention, hbar=mass=1."""
    result = np.ones(grid.shape, dtype=complex)
    for x, c, k, s in zip(grid.mesh, center, momentum, sigma, strict=True):
        z = 1 + 1j * t / (2 * s * s)
        result *= ((2 * np.pi * s * s) ** -0.25 / np.sqrt(z)
                   * np.exp(-(x - c - k * t) ** 2 / (4 * s * s * z)
                            + 1j * k * (x - c) - 0.5j * k * k * t))
    return result


def independent_hamiltonian(grid: Grid, values: np.ndarray, kinetic: str) -> np.ndarray:
    """Explicit DFT/stencil construction, not a call to production operators."""
    if grid.size > 1024:
        raise ValueError("dense independent references are limited to 1024 points")
    matrices = []
    for n, spacing in zip(grid.points, grid.spacing, strict=True):
        if kinetic == "fd2":
            identity = np.eye(n)
            matrix = (identity - 0.5 * np.roll(identity, 1, axis=1)
                      - 0.5 * np.roll(identity, -1, axis=1)) / spacing**2
        elif kinetic == "spectral":
            index = np.arange(n)
            transform = np.exp(-2j * np.pi * np.outer(index, index) / n) / math.sqrt(n)
            k = 2 * np.pi * np.fft.fftfreq(n, spacing)
            matrix = transform.conj().T @ ((0.5 * k**2)[:, None] * transform)
        else:
            raise ValueError("unknown kinetic discretisation")
        matrices.append(matrix)
    matrix = matrices[0] if grid.ndim == 1 else (
        np.kron(np.eye(grid.points[1]), matrices[0])
        + np.kron(matrices[1], np.eye(grid.points[0])))
    return np.asarray(matrix, complex) + np.diag(values.ravel())


def _result(passed: bool, metrics: dict, criteria: dict, evidence: str,
            notes: list[str] | None = None) -> dict:
    return {"status": "passed" if passed else "failed", "metrics": metrics,
            "criteria": criteria, "evidence": evidence, "notes": notes or []}


def _operators() -> dict:
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(1729)
    for ndim in (1, 2):
        config = fixture(ndim=ndim, points=16, length=16.0)
        grid = make_grid(config.grid)
        values = 0.3 * np.cos(grid.mesh[0])
        psi = normalise(rng.normal(size=grid.shape) + 1j * rng.normal(size=grid.shape), grid)
        _record_config(config, potential=values, initial_state=psi)
        for kinetic in ("spectral", "fd2"):
            matrix = independent_hamiltonian(grid, values, kinetic)
            action = apply_hamiltonian(psi, grid, values, kinetic)
            residual = float(np.linalg.norm(matrix - matrix.conj().T) / max(1.0, np.linalg.norm(matrix)))
            error = state_error(action, (matrix @ psi.ravel()).reshape(grid.shape), grid)
            rows.append({"dimension": ndim, "kinetic": kinetic, "hermiticity": residual, "action_error": error})
    return _result(all(row["hermiticity"] < 1e-12 and row["action_error"] < 1e-11 for row in rows),
                   {"comparisons": rows}, {"hermiticity": 1e-12, "operator_action": 1e-11}, "independent-discrete-reference")


def _free(ndim: int) -> dict:
    config = fixture(ndim=ndim, points=512 if ndim == 1 else 128,
                     length=80.0 if ndim == 1 else 48.0, duration=2.0 if ndim == 1 else 1.0)
    psi, grid, diagnostics = propagate(config)
    reference = analytic_free(grid, list(config.state.center), list(config.state.momentum),
                              list(config.state.sigma), config.solver.duration)
    error = state_error(psi, reference, grid)
    threshold = 1e-10 if ndim == 1 else 1e-9
    return _result(error < threshold and diagnostics["max_norm_drift"] < 1e-11,
                   {"weighted_l2_error": error, **diagnostics},
                   {"weighted_l2_error": threshold, "max_norm_drift": 1e-11}, "analytic",
                   ["Finite periodic domain chosen so analytic tails at its edges are negligible."])


def _dense_reference(ndim: int, kinetic: str, method: str) -> dict:
    config = fixture(ndim=ndim, points=32 if ndim == 1 else 16, length=16.0,
                     duration=0.4, dt=0.002, kinetic=kinetic, method=method,
                     state={"kind": "gaussian", "center": [-2.0] * ndim, "momentum": [1.0] * ndim, "sigma": [1.0] * ndim})
    grid = make_grid(config.grid)
    values = 0.4 * (1 - np.cos(2 * np.pi * grid.mesh[0] / 16.0))
    if ndim == 2:
        values += 0.2 * np.sin(2 * np.pi * grid.mesh[0] / 16.0) * np.sin(2 * np.pi * grid.mesh[1] / 16.0)
    psi0 = initial_state(config, grid)
    matrix = independent_hamiltonian(grid, values, kinetic)
    reference = (expm(-1j * matrix * config.solver.duration) @ psi0.ravel()).reshape(grid.shape)
    psi, _, diagnostics = propagate(config, psi0, values)
    error = state_error(psi, reference, grid)
    limit = 2e-6 if method == "cn" else 2e-7
    return _result(error < limit and diagnostics["max_norm_drift"] < 1e-11,
                   {"weighted_l2_error": error, **diagnostics},
                   {"weighted_l2_error": limit, "max_norm_drift": 1e-11}, "independent-discrete-reference")


def _free_superposition(ndim: int) -> dict:
    from .experiments import get_experiment

    original = get_experiment("1d-interference" if ndim == 1 else "2d-crossing")
    data = original.model_dump()
    data["solver"].update(duration=4.0, dt=0.02)
    data["sampling"]["snapshots"] = 2
    config = SimulationConfig.model_validate(data)
    grid = make_grid(config.grid)
    initial = np.zeros(grid.shape, complex)
    reference = np.zeros(grid.shape, complex)
    for component in config.state.params["components"]:
        state = component["state"]
        center, momentum, sigma = state["center"], state["momentum"], state["sigma"]
        start = analytic_free(grid, center, momentum, sigma, 0.0)
        scale = math.sqrt(probability(start, grid))
        amplitude = complex(component.get("amplitude", 1.0))
        initial += amplitude * start / scale
        reference += amplitude * analytic_free(grid, center, momentum, sigma, 4.0) / scale
    scale = math.sqrt(probability(initial, grid))
    initial, reference = initial / scale, reference / scale
    initial_error = state_error(initial_state(config, grid), initial, grid)
    psi, _, diagnostics = propagate(config)
    error = state_error(psi, reference, grid)
    return _result(initial_error < 1e-12 and error < 1e-8,
                   {"initial_state_error": initial_error, "state_error": error, **diagnostics},
                   {"initial_state_error": 1e-12, "state_error": 1e-8}, "analytic-superposition",
                   ["Complex amplitudes are added before forming density; these are one-particle coherent states."])


def _reversal() -> dict:
    config = fixture(points=128, length=24.0, duration=2.0, dt=0.002,
                     state={"kind": "gaussian", "center": [-2.0], "momentum": [1.0], "sigma": [1.0]},
                     potential_spec={"kind": "harmonic", "params": {"omega": [1.0]}})
    grid = make_grid(config.grid)
    values, psi0 = potential(config, grid), initial_state(config, grid)
    step = make_stepper(config, grid, values)
    psi = psi0.copy()
    maximum_drift = 0.0
    for sign in (1, -1):
        for _ in range(config.n_steps):
            psi = step(psi, sign * config.solver.dt)
            maximum_drift = max(maximum_drift, abs(probability(psi, grid) - 1))
    error = state_error(psi, psi0, grid)
    return _result(error < 1e-10 and maximum_drift < 1e-11,
                   {"roundtrip_l2_error": error, "max_norm_drift": maximum_drift},
                   {"roundtrip_l2_error": 1e-10, "max_norm_drift": 1e-11}, "discrete-invariant",
                   ["Reversal is tested only for a closed static Hermitian run."])


def _oscillator_superposition() -> dict:
    config = fixture(points=256, length=24.0, duration=1.0, dt=0.001,
                     potential_spec={"kind": "harmonic", "params": {"omega": [1.0]}})
    grid = make_grid(config.grid)
    x = grid.axes[0]
    ground = np.pi**-0.25 * np.exp(-x * x / 2)
    excited = math.sqrt(2) * x * ground
    psi0 = normalise((ground + excited).astype(complex), grid)
    reference = (ground * np.exp(-0.5j) + excited * np.exp(-1.5j)) / math.sqrt(2)
    psi, _, diagnostics = propagate(config, psi0)
    error = state_error(psi, reference, grid)
    aligned = state_error(psi, reference, grid, align=True)
    return _result(error < 1e-5 and diagnostics["max_norm_drift"] < 1e-11,
                   {"raw_state_error": error, "phase_aligned_error": aligned, **diagnostics},
                   {"raw_state_error": 1e-5, "max_norm_drift": 1e-11}, "analytic",
                   ["The relative phase of n=0 and n=1 is checked; global phase alignment alone would miss an energy error."])


def _closed_energy() -> dict:
    rows = []
    for method, kinetic, threshold in (("cn", "fd2", 1e-10), ("strang", "spectral", 1e-4), ("yoshida4", "spectral", 1e-7)):
        config = fixture(points=256, length=24.0, duration=2.0, dt=0.005, method=method, kinetic=kinetic,
                         state={"kind": "gaussian", "center": [-2.0], "momentum": [1.0], "sigma": [0.8]},
                         potential_spec={"kind": "harmonic", "params": {"omega": [1.0]}})
        _, _, diagnostics = propagate(config)
        rows.append({"method": method, "kinetic": kinetic, "relative_energy_change": diagnostics["relative_energy_change"],
                     "threshold": threshold, "passed": diagnostics["relative_energy_change"] < threshold})
    return _result(all(row["passed"] for row in rows), {"comparisons": rows},
                   {"cn_relative_energy_change": 1e-10, "strang": 1e-4, "yoshida4": 1e-7}, "closed-static-energy",
                   ["CN preserves the fixed discrete-H energy to solve/roundoff error; splitting has a finite time-discretisation error.",
                    "No corresponding energy-conservation claim is applied to CAP runs."])


def _oscillator_moments(ndim: int = 1, squeezed: bool = False) -> dict:
    omega = np.array([1.0] if ndim == 1 else [1.0, 1.5])
    angle = 0.0 if ndim == 1 else math.pi / 6
    center = np.array([2.0] if ndim == 1 else [2.0, -1.0])
    momentum = np.array([0.5] if ndim == 1 else [0.5, 1.0])
    if squeezed:
        center[:] = momentum[:] = 0
    params = {"omega": omega.tolist(), "angle": angle}
    if squeezed:
        params["squeeze"] = [0.65]
    config = fixture(ndim=ndim, points=256 if ndim == 1 else 128, length=24 if ndim == 1 else 20,
                     duration=1.0, dt=0.001,
                     state={"kind": "ho_squeezed" if squeezed else "ho_coherent", "center": center.tolist(),
                            "momentum": momentum.tolist(), "sigma": [1.0] * ndim, "params": params},
                     potential_spec={"kind": "harmonic", "params": {"omega": omega.tolist(), "angle": angle}})
    psi, grid, diagnostics = propagate(config)
    rotation = np.eye(1) if ndim == 1 else np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    q0, p0 = rotation.T @ center, rotation.T @ momentum
    q = q0 * np.cos(omega) + p0 / omega * np.sin(omega)
    expected_center = rotation @ q
    variance = (np.exp(1.3) / (2 * omega) * np.cos(omega)**2
                + np.exp(-1.3) / (2 * omega) * np.sin(omega)**2) if squeezed else 1 / (2 * omega)
    expected_covariance = rotation @ np.diag(variance) @ rotation.T
    density = np.abs(psi)**2
    observed_center = np.array([np.sum(density * x) * grid.cell_volume for x in grid.mesh])
    observed_covariance = np.array([[np.sum(density * (x - cx) * (y - cy)) * grid.cell_volume
                                    for y, cy in zip(grid.mesh, observed_center, strict=True)]
                                   for x, cx in zip(grid.mesh, observed_center, strict=True)])
    mean_error = float(np.max(np.abs(observed_center - expected_center)))
    covariance_error = float(np.max(np.abs(observed_covariance - expected_covariance)))
    errors = {}
    if not squeezed:
        evolved_p = p0 * np.cos(omega) - omega * q0 * np.sin(omega)
        lab_p = rotation @ evolved_p
        displacement = [coordinate - c for coordinate, c in zip(grid.mesh, expected_center, strict=True)]
        normal_coordinates = [sum(rotation[j, i] * displacement[j] for j in range(ndim)) for i in range(ndim)]
        reference = np.ones(grid.shape, complex)
        for coordinate, frequency in zip(normal_coordinates, omega, strict=True):
            reference *= (frequency / np.pi)**0.25 * np.exp(-0.5 * frequency * coordinate**2)
        # The ansatz exp[i p(t)(x-q(t))+i theta(t)] has
        # theta=.5[p(t)q(t)-p0q0]-.5*sum(omega)*t, with theta(0)=0.
        phase = 0.5 * (float(evolved_p @ q) - float(p0 @ q0)) - 0.5 * float(np.sum(omega))
        reference *= np.exp(1j * (sum(k * x for k, x in zip(lab_p, displacement, strict=True)) + phase))
        errors = {"raw_state_error": state_error(psi, reference, grid),
                  "phase_aligned_state_error": state_error(psi, reference, grid, align=True)}
    passed = max(mean_error, covariance_error, *errors.values()) < 1e-5 and diagnostics["max_norm_drift"] < 1e-11
    return _result(passed,
                   {"mean_error": mean_error, "covariance_error": covariance_error,
                    "observed_center": observed_center.tolist(), "expected_center": expected_center.tolist(),
                    "observed_covariance": observed_covariance.tolist(), **errors, **diagnostics},
                   {"mean_error": 1e-5, "covariance_error": 1e-5, "state_error_when_coherent": 1e-5, "max_norm_drift": 1e-11}, "analytic-state-and-moments" if not squeezed else "analytic-moments")


def _temporal_order(method: str, kinetic: str) -> dict:
    steps = [0.2, 0.1, 0.05] if method == "yoshida4" else [0.08, 0.04, 0.02]
    duration = 0.8
    rows = []
    reference = None
    for dt in steps:
        config = fixture(points=32, length=16.0, duration=duration, dt=dt, method=method, kinetic=kinetic,
                         state={"kind": "gaussian", "center": [-2.0], "momentum": [1.0], "sigma": [1.0]})
        grid = make_grid(config.grid)
        values = 0.8 * np.cos(2 * np.pi * grid.axes[0] / 16) + 0.3 * np.cos(4 * np.pi * grid.axes[0] / 16)
        psi0 = initial_state(config, grid)
        if reference is None:
            reference = expm(-1j * independent_hamiltonian(grid, values, kinetic) * duration) @ psi0
        psi, _, _ = propagate(config, psi0, values)
        rows.append({"dt": dt, "error": state_error(psi, reference, grid)})
    orders = [math.log2(a["error"] / b["error"]) for a, b in zip(rows, rows[1:], strict=False)]
    expected = 4 if method == "yoshida4" else 2
    lower, upper = (3.6, 4.4) if expected == 4 else (1.8, 2.2)
    return _result(all(lower < order < upper for order in orders),
                   {"samples": rows, "observed_orders": orders}, {"order_interval": [lower, upper]},
                   "same-H-temporal-convergence", ["Independent dense exponential fixes spatial discretisation and avoids mixing space and time errors."])


def _fd_spatial() -> dict:
    rows = []
    for points in (128, 256, 512):
        config = fixture(points=points, length=40.0, duration=1.0, dt=0.05, kinetic="fd2",
                         state={"kind": "gaussian", "center": [-5.0], "momentum": [1.5], "sigma": [1.0]})
        psi, grid, _ = propagate(config)
        reference = analytic_free(grid, [-5.0], [1.5], [1.0], 1.0)
        rows.append({"points": points, "dx": grid.spacing[0], "error": state_error(psi, reference, grid)})
    orders = [math.log2(a["error"] / b["error"]) for a, b in zip(rows, rows[1:], strict=False)]
    return _result(all(1.8 < value < 2.2 for value in orders), {"samples": rows, "observed_orders": orders},
                   {"order_interval": [1.8, 2.2]}, "continuum-spatial-convergence",
                   ["Free FD2 splitting is exact in time for the discrete kinetic operator; the remaining error is spatial."])


def _spectral_spatial() -> dict:
    rows = []
    for points in (32, 64, 128, 256):
        config = fixture(points=points, length=40.0, duration=1.0, dt=0.05,
                         state={"kind": "gaussian", "center": [-5.0], "momentum": [2.0], "sigma": [0.8]})
        psi, grid, _ = propagate(config)
        reference = analytic_free(grid, [-5.0], [2.0], [0.8], 1.0)
        rows.append({"points": points, "error": state_error(psi, reference, grid)})
    return _result(rows[-1]["error"] < 1e-9 and rows[-1]["error"] < rows[0]["error"],
                   {"samples": rows}, {"finest_error": 1e-9}, "continuum-spatial-convergence",
                   ["Spectral error decay is measured; a universal algebraic order is not asserted."])


def _domain() -> dict:
    rows = []
    solutions = []
    for length, points in ((40.0, 256), (80.0, 512)):
        config = fixture(points=points, length=length, duration=4.0, dt=0.02,
                         state={"kind": "gaussian", "center": [-8.0], "momentum": [1.0], "sigma": [1.5]})
        psi, grid, _ = propagate(config)
        reference = analytic_free(grid, [-8.0], [1.0], [1.5], 4.0)
        rows.append({"length": length, "points": points, "error": state_error(psi, reference, grid)})
        solutions.append(psi)
    # The enlarged grid contains the same physical sample locations.
    cropped = solutions[1][128:384]
    disagreement = float(np.linalg.norm(solutions[0] - cropped) * math.sqrt(40 / 256))
    return _result(disagreement < 1e-7, {"samples": rows, "domain_disagreement": disagreement},
                   {"domain_disagreement": 1e-7}, "domain-sensitivity",
                   ["Domain enlargement holds dx, dt and physical initial conditions fixed."])


def _cap() -> dict:
    rows = []
    settings = [(k, 25.0, 4.0, True) for k in (1.0, 2.0, 4.0)]
    settings += [(2.0, width, strength, False) for width, strength in ((20.0, 4.0), (30.0, 4.0), (25.0, 2.0), (25.0, 8.0))]
    for momentum, width, strength, selected in settings:
        duration = 140.0 / momentum
        config = fixture(points=1024, length=160.0, duration=duration, dt=0.04,
                         state={"kind": "gaussian", "center": [-30.0], "momentum": [momentum], "sigma": [3.0]},
                         boundary={"kind": "cap", "width": width, "strength": strength, "power": 4})
        grid = make_grid(config.grid)
        psi = initial_state(config, grid)
        values, loss = potential(config, grid), absorber(config, grid)
        step = make_stepper(config, grid, values, loss)
        absorbed_rate = 0.0
        last_norm = probability(psi, grid)
        last_rate = float(2 * np.sum(loss * np.abs(psi)**2) * grid.cell_volume)
        max_increase = 0.0
        now = 0.0
        for _ in range(config.n_steps):
            dt = min(config.solver.dt, duration - now)
            psi = step(psi, dt)
            norm = probability(psi, grid)
            rate = float(2 * np.sum(loss * np.abs(psi)**2) * grid.cell_volume)
            absorbed_rate += 0.5 * dt * (rate + last_rate)
            max_increase = max(max_increase, norm - last_norm)
            last_norm, last_rate = norm, rate
            now += dt
        # At the final time the freely transmitted packet has left the interior;
        # probability returning upstream diagnoses absorber-induced reflection.
        reflected = float(np.sum(np.abs(psi[grid.axes[0] < 30.0])**2) * grid.cell_volume)
        outgoing = analytic_free(grid, [-30.0], [momentum], [3.0], duration)
        upstream = grid.axes[0] < 30.0
        free_tail = float(np.sum(np.abs(outgoing[upstream])**2) * grid.cell_volume)
        upstream_error = float(np.sum(np.abs(psi[upstream] - outgoing[upstream])**2) * grid.cell_volume)
        budget_error = abs(last_norm + absorbed_rate - 1.0)
        ledger_error = abs(last_norm + step.total_absorbed - 1.0)
        rows.append({"momentum": momentum, "width": width, "strength": strength, "selected_default": selected,
                     "returned_interior_probability": reflected,
                     "analytic_free_tail_probability": free_tail, "upstream_error_probability": upstream_error,
                     "remaining_norm": last_norm, "integrated_absorption_rate": absorbed_rate,
                     "stepper_absorbed_ledger": step.total_absorbed, "ledger_budget_error": ledger_error,
                     "budget_error": budget_error, "largest_norm_increase": max_increase})
    passed = all(row["upstream_error_probability"] < 1e-3 and row["budget_error"] < 2e-4
                 and row["ledger_budget_error"] < 1e-10
                 and row["largest_norm_increase"] < 1e-12 for row in rows if row["selected_default"])
    return _result(passed, {"calibration_samples": rows},
                   {"upstream_error_probability_vs_analytic_free": 1e-3, "rate_budget_error": 2e-4, "ledger_budget_error": 1e-10, "norm_increase": 1e-12},
                   "absorber-calibration",
                   ["This calibrates one quartic layer on k=1,2,4 packets; it is not reflection-free for arbitrary states.",
                    "Analytical free propagation separates a genuine outgoing packet tail from boundary-induced upstream state error.",
                    "The integrated loss rate is sampled independently of the norm decrement; the explicit damping ledger is also reported.",
                    "Additional settings are sensitivity measurements. Three packet samples do not establish a continuous momentum band."])


def _preset_boundary_sensitivity() -> dict:
    from .experiments import get_experiment, list_experiments

    rows = []
    for entry in list_experiments():
        config = get_experiment(entry["id"])
        if config.boundary.kind != "cap":
            continue
        grid = make_grid(config.grid)
        padding = [math.ceil(config.boundary.width / spacing) for spacing in grid.spacing]
        data = config.model_dump()
        data["grid"] = {
            "bounds": [[lo - count * spacing, hi + count * spacing]
                       for (lo, hi), count, spacing in zip(grid.bounds, padding, grid.spacing, strict=True)],
            "points": [n + 2 * count for n, count in zip(grid.points, padding, strict=True)],
        }
        data["budget"]["max_points"] = max(config.budget.max_points, math.prod(data["grid"]["points"]))
        enlarged = SimulationConfig.model_validate(data)
        original, _, diagnostics = propagate(_record_config(config))
        reference, _, reference_diagnostics = propagate(enlarged)
        slices = tuple(slice(count, count + n) for count, n in reversed(list(zip(padding, grid.points, strict=True))))
        interior = absorber(config, grid) == 0
        error = float(np.linalg.norm((original - reference[slices])[interior]) * math.sqrt(grid.cell_volume))
        interior_probability = float(np.sum(np.abs(original[interior])**2) * grid.cell_volume)
        rows.append({"id": entry["id"], "configuration_sha256": config_fingerprint(config),
                     "reference_configuration_sha256": config_fingerprint(enlarged),
                     "conditions": entry["evidence_record"]["conditions"],
                     "observable": "raw complex L2 state difference where the original CAP is zero",
                     "interior_state_l2_difference": error, "interior_probability": interior_probability,
                     "original_probability_budget_error": diagnostics["norm_absorption_budget_error"],
                     "reference_probability_budget_error": reference_diagnostics["norm_absorption_budget_error"],
                     "passed": error < 1e-3 and diagnostics["norm_absorption_budget_error"] < 1e-10})
    return _result(all(row["passed"] for row in rows), {"presets": rows},
                   {"interior_state_l2_difference": 1e-3, "norm_absorption_budget_error": 1e-10},
                   "exact-preset-domain-and-cap-displacement",
                   ["The original grid, potential, packet, timestep and full published duration are unchanged.",
                    "The reference moves each boundary and CAP outward by at least one layer width at fixed grid spacing.",
                    "This tests the stated interior state observable; it does not certify reflection at all energies, incidence angles or later times."])


def stationary_transmission(momentum: np.ndarray | float,
                            segments: list[tuple[float, float]]) -> np.ndarray:
    """Stable scattering-matrix composition through finite rectangular layers.

    Each segment is (potential height, width); both asymptotic leads have V=0.
    Unlike a transfer matrix, evanescent propagation factors never grow.
    """
    k_values = np.asarray(momentum, float)
    if not np.all(np.isfinite(k_values)):
        raise ValueError("momenta must be finite")
    if any(not math.isfinite(h) or not math.isfinite(w) or w < 0 for h, w in segments):
        raise ValueError("layers require finite heights and nonnegative widths")
    result = np.zeros_like(k_values)

    def cascade(a, b):
        rl, trl, tlr, rr = a
        sl, srl, slr, sr = b
        denominator = 1 - rr * sl
        return (rl + trl * sl * tlr / denominator, trl * srl / denominator,
                slr * tlr / denominator, sr + slr * rr * srl / denominator)

    positive = k_values > 0
    energy = 0.5 * k_values[positive]**2 + 1e-14j
    current = np.sqrt(2 * energy)
    scattering = (np.zeros_like(current), np.ones_like(current), np.ones_like(current), np.zeros_like(current))
    for height, width in [*segments, (0.0, 0.0)]:
        following = np.sqrt(2 * (energy - height))
        denominator = current + following
        reflection = (current - following) / denominator
        interface = (reflection, 2 * following / denominator, 2 * current / denominator, -reflection)
        scattering = cascade(scattering, interface)
        if width:
            phase = np.exp(1j * following * width)
            scattering = cascade(scattering, (0j, phase, phase, 0j))
        current = following
    result[positive] = abs(scattering[2])**2
    return result


def gaussian_transmission_reference(momentum: float, sigma: float,
                                    segments: list[tuple[float, float]], *,
                                    accuracy_target: float = 1e-7) -> dict[str, Any]:
    """Cross-check adaptive quadrature against a separately refined momentum scan."""
    if (not math.isfinite(momentum) or not math.isfinite(sigma) or sigma <= 0
            or not math.isfinite(accuracy_target) or accuracy_target <= 0):
        raise ValueError("Gaussian reference requires finite momentum, positive sigma and accuracy target")
    tolerance = min(1e-8, accuracy_target / 10)
    deviation = 0.5 / sigma
    upper = max(0.0, momentum) + 12 * deviation
    if deviation == 0 or tolerance/10 == 0 or not math.isfinite(upper) or upper > math.sqrt(np.finfo(float).max):
        raise ValueError("Gaussian reference scales must be representable in float64")

    def density(k):
        return np.exp(-0.5 * ((k - momentum) / deviation)**2) / (math.sqrt(2 * np.pi) * deviation)

    scans = []
    previous = None
    for power in range(14, 21):
        k = np.linspace(0, upper, 2**power + 1)
        transmission = stationary_transmission(k, segments)
        integral = float(simpson(density(k) * transmission, x=k))
        scans.append({"points": len(k), "spacing": float(k[1] - k[0]), "weighted_transmission": integral})
        peaks, _ = find_peaks(transmission)
        # Peak positions partition the adaptive integrator without sharing its quadrature nodes.
        points = k[peaks].tolist()
        adaptive, estimate = quad(lambda value: float(density(value) * stationary_transmission(value, segments)),
                                  0, upper, points=points, epsabs=tolerance / 10,
                                  epsrel=tolerance / 10, limit=max(200, 4 * len(points)))
        if previous is not None and abs(integral - previous) < tolerance and abs(adaptive - integral) < tolerance:
            return {"weighted_transmission": adaptive, "quadrature_error_estimate": estimate,
                    "refined_scan_transmission": integral, "reference_disagreement": abs(adaptive - integral),
                    "required_agreement": tolerance, "momentum_scan": scans,
                    "detected_resonance_momenta": points, "integration_bounds": [0.0, upper],
                    "initial_negative_momentum_mass": float(0.5 * erfc(momentum / (math.sqrt(2) * deviation))),
                    "omitted_upper_tail_bound": float(0.5 * erfc(12 / math.sqrt(2)))}
        previous = integral
    raise ValueError(f"stationary quadrature/scan failed to agree within {tolerance}")


def packet_transmission_reference(psi: np.ndarray, grid: Grid,
                                  segments: list[tuple[float, float]]) -> dict[str, float]:
    if grid.ndim != 1:
        raise ValueError("stationary packet transmission reference is one-dimensional")
    k = 2 * np.pi * np.fft.fftfreq(grid.points[0], grid.spacing[0])
    weights = np.abs(np.fft.fft(psi))**2 * grid.cell_volume / grid.size
    positive = k > 0
    return {"weighted_transmission": float(np.sum(weights[positive] * stationary_transmission(k[positive], segments))),
            "initial_negative_momentum_mass": float(np.sum(weights[k < 0]))}


def _scattering(double: bool = False) -> dict:
    parameters = {"height": 2.5, "width": 1.0 if double else 2.0}
    if double:
        parameters["separation"] = 5.0
    potential_spec = {"kind": "double_barrier" if double else "rectangle", "params": parameters}
    # Resonant dwell at T=38 leaves about 2.8% between the barriers.  Extend
    # both time and domain at the same dx, rather than relaxing the separation
    # tolerance or letting periodic wraparound masquerade as transmission.
    config = fixture(points=10240 if double else 6144, length=400.0 if double else 240.0,
                     duration=80.0 if double else 38.0, dt=0.001,
                     state={"kind": "gaussian", "center": [-30.0], "momentum": [2.0], "sigma": [3.0]},
                     potential_spec=potential_spec)
    grid = make_grid(config.grid)
    psi0 = initial_state(config, grid)
    segments = [(2.5, 1.0), (0.0, 4.0), (2.5, 1.0)] if double else [(2.5, 2.0)]
    reference = gaussian_transmission_reference(2.0, 3.0, segments)
    fft_reference = packet_transmission_reference(psi0, grid, segments)
    psi, _, diagnostics = propagate(config, psi0)
    x, density = grid.axes[0], np.abs(psi)**2
    cut = 4.0 if double else 2.0
    transmitted = float(np.sum(density[x > cut]) * grid.cell_volume)
    reflected = float(np.sum(density[x < -cut]) * grid.cell_volume)
    interaction = float(np.sum(density[(x >= -cut) & (x <= cut)]) * grid.cell_volume)
    difference = abs(transmitted - reference["weighted_transmission"])
    limit = 0.025 if double else 0.015
    return _result(difference < limit and interaction < 0.01 and diagnostics["max_norm_drift"] < 1e-10
                   and diagnostics["relative_energy_change"] < 1e-3,
                   {"transmitted": transmitted, "reflected": reflected, "interaction_mass": interaction,
                    "transmission_error": difference, "probability_partition": transmitted + reflected + interaction,
                    "fft_bin_reference": fft_reference,
                    "fft_bin_quadrature_disagreement": abs(fft_reference["weighted_transmission"] - reference["weighted_transmission"]),
                    **reference, **diagnostics}, {"transmission_error": limit, "interaction_mass": 0.01, "max_norm_drift": 1e-10,
                                                 "relative_energy_change": 1e-3},
                   "momentum-weighted-stationary-reference",
                   ["Finite-grid rectangular edges contribute spatial error; finite-time trapped mass is reported explicitly.",
                    "Adaptive momentum integration is cross-checked against a separately refined Simpson scan; FFT bins are reported separately.",
                    "The reference composes bounded scattering matrices rather than exponentially growing transfer matrices."])


def _double_well() -> dict:
    config = fixture(points=128, length=16.0, duration=1.0, dt=0.01, method="yoshida4",
                     potential_spec={"kind": "double_well", "params": {"height": 0.4, "separation": 5.0}})
    grid = make_grid(config.grid)
    values = potential(config, grid)
    matrix = independent_hamiltonian(grid, values, "spectral")
    truth, _ = eigh(matrix, subset_by_index=[0, 1])
    observed, basis = eigenbasis(config, grid, 2)
    eigenvalue_error = float(np.max(np.abs(observed - truth)))
    residuals = [float(np.linalg.norm(matrix @ state - value * state) * math.sqrt(grid.cell_volume))
                 for value, state in zip(observed, basis, strict=True)]
    psi0 = normalise(basis[0] + basis[1], grid)
    duration = min(float(np.pi / (observed[1] - observed[0])), 150.0)
    exact = (basis[0] * np.exp(-1j * observed[0] * duration)
             + basis[1] * np.exp(-1j * observed[1] * duration)) / math.sqrt(2)
    data = config.model_dump()
    data["solver"].update(duration=duration, dt=0.02)
    psi, _, _ = propagate(SimulationConfig.model_validate(data), psi0)
    error = state_error(psi, exact, grid)
    convergence = []
    for points, length, axis in ((128, 24.0, "space"), (256, 24.0, "space"),
                                 (512, 24.0, "space"), (128, 16.0, "domain"),
                                 (192, 24.0, "domain"), (256, 32.0, "domain")):
        refined = fixture(points=points, length=length, potential_spec=config.potential.model_dump())
        refined_grid = make_grid(refined.grid)
        energies, modes = eigenbasis(refined, refined_grid, 2)
        gap = float(energies[1] - energies[0])
        residual = max(float(np.linalg.norm(apply_hamiltonian(mode, refined_grid, potential(refined, refined_grid),
                                "spectral") - energy * mode) * math.sqrt(refined_grid.cell_volume))
                       for energy, mode in zip(energies, modes, strict=True))
        convergence.append({"axis": axis, "points": points, "length": length,
                            "spacing": refined_grid.spacing[0], "eigenvalues": energies.tolist(),
                            "gap": gap, "transfer_time_pi_over_gap": math.pi / gap,
                            "maximum_residual": residual, "residual_over_gap": residual / gap})
    space_change = abs(convergence[2]["gap"] - convergence[1]["gap"]) / convergence[2]["gap"]
    domain_change = abs(convergence[5]["gap"] - convergence[4]["gap"]) / convergence[5]["gap"]
    residual_ratio = max(row["residual_over_gap"] for row in convergence)
    return _result(eigenvalue_error < 1e-8 and max(residuals) < 1e-8 and error < 1e-3
                   and max(space_change, domain_change) < 1e-5 and residual_ratio < 1e-7,
                   {"eigenvalues": observed.tolist(), "eigenvalue_error": eigenvalue_error,
                    "eigen_residuals": residuals, "gap": float(observed[1] - observed[0]),
                    "test_duration": duration, "state_error": error, "gap_convergence": convergence,
                    "relative_gap_space_change": space_change, "relative_gap_domain_change": domain_change,
                    "maximum_residual_over_gap": residual_ratio},
                   {"eigenvalue_error": 1e-8, "eigen_residual": 1e-8, "state_error": 1e-3,
                    "relative_gap_space_domain_change": 1e-5, "residual_over_gap": 1e-7},
                   "independent-eigen-reference-and-gap-convergence",
                   ["Grid refinement fixes the domain; domain enlargement fixes dx=0.125.",
                    "Eigenpair residuals are compared with the physical splitting, not only an absolute tolerance."])


def _geometry_refinement() -> dict:
    from .experiments import get_experiment

    rows = []
    for identifier in ("1d-gaussian-barrier", "2d-single-slit", "2d-double-slit", "2d-obstacle", "2d-waveguide"):
        original = get_experiment(identifier)
        values: list[dict[str, Any]] = []
        dimension = len(original.grid.points)
        for scale in (0.5, 1.0, 2.0):
            data = original.model_dump()
            data["grid"]["points"] = [max(16, int(n * scale)) for n in original.grid.points]
            data["solver"].update(duration=6.0 if dimension == 2 else 16.0, dt=0.01)
            data["sampling"]["snapshots"] = 2
            # At the fine2D grid retain enough memory budget for the two stored frames.
            data["budget"]["max_points"] = max(262144, math.prod(data["grid"]["points"]))
            config = SimulationConfig.model_validate(data)
            psi, grid, diagnostics = propagate(config)
            right = float(np.sum(np.abs(psi)[grid.mesh[0] > 2.0]**2) * grid.cell_volume)
            values.append({"points": list(grid.points), "right_region_probability": right,
                           "final_norm": diagnostics["final_norm"]})
            if scale == 1.0:
                timestep_data = data.copy()
                timestep_data["solver"] = {**data["solver"], "dt": 0.005}
        half_step, half_grid, _ = propagate(SimulationConfig.model_validate(timestep_data))
        half_right = float(np.sum(np.abs(half_step)[half_grid.mesh[0] > 2.0]**2) * half_grid.cell_volume)
        time_change = abs(half_right - values[1]["right_region_probability"])
        coarse_change = abs(values[1]["right_region_probability"] - values[0]["right_region_probability"])
        fine_change = abs(values[2]["right_region_probability"] - values[1]["right_region_probability"])
        rows.append({"id": identifier, "samples": values, "coarse_change": coarse_change,
                     "fine_change": fine_change, "timestep_half_right_probability": half_right,
                     "timestep_change": time_change, "passed": fine_change < 0.005 and time_change < 0.005})
    return _result(all(row["passed"] for row in rows), {"studies": rows},
                   {"fine_change_in_right_region_probability": 0.005, "timestep_change": 0.005}, "empirical-space-time-refinement",
                   ["This finite-time regional observable is not claimed to be an asymptotic detector distribution.",
                    "Agreement of this observable alone does not certify every pixel of an interference pattern."])


def _waveguide_modes() -> dict:
    from .experiments import get_experiment
    original = get_experiment("2d-waveguide")
    rows = []
    for scale in (1, 2):
        data = original.model_dump()
        data["grid"]["points"] = [scale*n for n in original.grid.points]
        data["budget"]["max_points"] = max(original.budget.max_points, math.prod(data["grid"]["points"]))
        data["solver"].update(duration=6.0, dt=0.01/scale)
        data["sampling"]["snapshots"] = 2
        config = SimulationConfig.model_validate(data)
        state, grid, diagnostics = propagate(config)
        content = waveguide_mode_content(config, state, grid)
        rows.append({"points": list(grid.points), "dt": config.solver.dt,
                     "absorbed_probability": diagnostics["absorbed_probability"], **content})
    mode_change = float(np.max(np.abs(np.asarray(rows[0]["mode_probabilities"]) - np.asarray(rows[1]["mode_probabilities"]))))
    partition_error = max(row["partition_error"] for row in rows)
    return _result(mode_change < 0.005 and partition_error < 1e-12,
                   {"samples": rows, "maximum_mode_probability_change": mode_change},
                   {"maximum_mode_probability_change": 0.005, "partition_error": 1e-12},
                   "finite-window-transverse-mode-projection-and-probability-partition",
                   ["Input, output, retained channel and outside-wall probabilities form a disjoint surviving-mass partition.",
                    "Mode probabilities refer only to the stated rotated finite window, with confined modes and unresolved mass reported.",
                    "Grid and timestep are jointly refined here; separate global refinement checks qualify those axes independently."])


def _screen_run(config: SimulationConfig, screen_x: float = 6.0) -> dict:
    """Integrate the signed nodal jx with a separate x-only DFT derivative.

    This avoids the production current helper and does not clip backflow or
    reinterpret repeated crossings as first-arrival detections.
    """
    _record_config(config)
    grid = make_grid(config.grid)
    if grid.ndim != 2 or config.solver.kinetic != "spectral":
        raise ValueError("screen refinement uses2D spectral states")
    psi = initial_state(config, grid)
    values, loss = potential(config, grid), absorber(config, grid)
    step = make_stepper(config, grid, values, loss)
    ix = int(np.argmin(np.abs(grid.axes[0] - screen_x)))
    frequencies = 2 * np.pi * np.fft.fftfreq(grid.points[0], grid.spacing[0])
    factor = 1j * frequencies * np.exp(2j * np.pi * np.arange(grid.points[0]) * ix / grid.points[0]) / grid.points[0]

    def flux(state: np.ndarray) -> np.ndarray:
        derivative = np.sum(np.fft.fft(state, axis=-1) * factor[None, :], axis=-1)
        return np.imag(np.conj(state[:, ix]) * derivative)

    previous = flux(psi)
    integrated = np.zeros(grid.points[1])
    now = 0.0
    for _ in range(config.n_steps):
        dt = min(config.solver.dt, config.solver.duration - now)
        psi = step(psi, dt)
        latest = flux(psi)
        integrated += 0.5 * dt * (previous + latest)
        previous = latest
        now += dt
    return {"y": grid.axes[1].tolist(), "signed_integrated_current": integrated.tolist(),
            "screen_x_requested": screen_x, "screen_x_actual": float(grid.axes[0][ix]),
            "final_screen_density": (np.abs(psi[:, ix])**2).tolist(),
            "signed_total_flux": float(np.sum(integrated) * grid.spacing[1]),
            "negative_profile_integral": float(np.sum(np.minimum(integrated, 0)) * grid.spacing[1]),
            "configuration": config.model_dump(mode="json")}


def _profile_difference(first: dict, reference: dict) -> float:
    a_axis, b_axis = np.asarray(first["y"]), np.asarray(reference["y"])
    spacing = min(a_axis[1] - a_axis[0], b_axis[1] - b_axis[0])
    axis = np.arange(min(a_axis[0], b_axis[0]), max(a_axis[-1], b_axis[-1]) + 0.25 * spacing, spacing)
    a = np.interp(axis, a_axis, first["signed_integrated_current"], left=0, right=0)
    b = np.interp(axis, b_axis, reference["signed_integrated_current"], left=0, right=0)
    scale = float(np.trapezoid(np.abs(b), axis))
    if scale < 1e-12:
        raise ValueError("screen profile has insufficient flux for a meaningful relative comparison")
    return float(np.trapezoid(np.abs(a - b), axis) / scale)


def _slit_profiles() -> dict:
    from .experiments import get_experiment

    studies = []
    for identifier in ("2d-single-slit", "2d-double-slit"):
        config = get_experiment(identifier)
        base = config.model_dump()
        base["solver"]["duration"] = 9.0
        base["sampling"]["snapshots"] = 2
        variants = {"baseline": base}
        fine = json.loads(json.dumps(base))
        fine["grid"]["points"] = [2 * n for n in config.grid.points]
        fine["budget"]["max_points"] = max(262144, math.prod(fine["grid"]["points"]))
        variants["space_half"] = fine
        half_time = json.loads(json.dumps(base))
        half_time["solver"]["dt"] /= 2
        variants["timestep_half"] = half_time
        enlarged = json.loads(json.dumps(base))
        enlarged["grid"]["bounds"] = [[lo - 6.0, hi + 6.0] for lo, hi in config.grid.bounds]
        enlarged["grid"]["points"] = [round((hi - lo + 12.0) / dx)
                                         for (lo, hi), dx in zip(config.grid.bounds, make_grid(config.grid).spacing, strict=True)]
        variants["domain_enlarged"] = enlarged
        alternative = json.loads(json.dumps(base))
        alternative["boundary"].update(width=6.0, strength=6.0)
        variants["cap_alternative"] = alternative
        profiles = {name: _screen_run(SimulationConfig.model_validate(data)) for name, data in variants.items()}
        differences = {name: _profile_difference(profiles["baseline"], profile)
                       for name, profile in profiles.items() if name != "baseline"}
        studies.append({"id": identifier, "duration": 9.0, "screen_x": 6.0,
                        "relative_l1_differences": differences,
                        "passed": all(value < 0.01 for value in differences.values()), "profiles": profiles})
    return _result(all(study["passed"] for study in studies), {"studies": studies},
                   {"signed_profile_relative_l1_change": 0.01}, "screen-profile-space-time-domain-cap-sensitivity",
                   ["Profiles retain their signed current; no normalization to unity or negative-flux clipping is applied.",
                    "L1 differences are divided by the reference profile's absolute integral; axes are interpolated and extra-domain tails retained.",
                    "The measured profile is a time-integrated signed flux, not a first-detection probability."])


def _run_case(name: str, function: Callable[[], dict]) -> dict:
    started = time.perf_counter()
    token = _CASE_CONFIGS.set([])
    try:
        result = function()
    except Exception as error:  # Preserve every failed scientific check in the report.
        result = {"status": "failed", "error": f"{type(error).__name__}: {error}",
                  "metrics": {}, "criteria": {}, "evidence": "execution-failed", "notes": []}
    records = _CASE_CONFIGS.get()
    _CASE_CONFIGS.reset(token)
    return {"id": name, "elapsed_seconds": time.perf_counter() - started, "configurations": records, **result}


def run_validation(suite: str = "quick", output: str | Path | None = None) -> dict[str, Any]:
    if suite not in ("quick", "full"):
        raise ValueError("suite must be 'quick' or 'full'")
    sources = ("config.py", "model.py", "operators.py", "propagators.py", "observables.py", "experiments.py", "validation.py", "units.py")
    hashes_at_start = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources}
    cases: list[tuple[str, Callable[[], dict]]] = [
        ("independent-operators-1d-2d", _operators),
        ("analytic-free-1d", lambda: _free(1)), ("analytic-free-2d", lambda: _free(2)),
        ("dense-reference-strang-spectral-1d", lambda: _dense_reference(1, "spectral", "strang")),
        ("dense-reference-cn-fd2", lambda: _dense_reference(1, "fd2", "cn")),
        ("closed-norm-reversal", _reversal), ("oscillator-relative-phase", _oscillator_superposition),
    ]
    full_cases: list[tuple[str, Callable[[], dict]]] = [
        ("analytic-interference-1d", lambda: _free_superposition(1)),
        ("analytic-crossing-2d", lambda: _free_superposition(2)),
        ("closed-static-energy", _closed_energy),
        ("dense-reference-strang-spectral-2d", lambda: _dense_reference(2, "spectral", "strang")),
        ("dense-reference-strang-fd2", lambda: _dense_reference(1, "fd2", "strang")),
        ("dense-reference-yoshida4", lambda: _dense_reference(1, "spectral", "yoshida4")),
        ("analytic-coherent-1d", lambda: _oscillator_moments(1)),
        ("analytic-squeezed-1d", lambda: _oscillator_moments(1, True)),
        ("analytic-rotated-oscillator-2d", lambda: _oscillator_moments(2)),
        ("temporal-order-strang-spectral", lambda: _temporal_order("strang", "spectral")),
        ("temporal-order-strang-fd2", lambda: _temporal_order("strang", "fd2")),
        ("temporal-order-cn-fd2", lambda: _temporal_order("cn", "fd2")),
        ("temporal-order-yoshida4", lambda: _temporal_order("yoshida4", "spectral")),
        ("fd2-continuum-spatial-order", _fd_spatial), ("spectral-spatial-refinement", _spectral_spatial),
        ("domain-enlargement", _domain), ("cap-calibration", _cap),
        ("preset-boundary-sensitivity", _preset_boundary_sensitivity),
        ("rectangular-packet-transmission", _scattering),
        ("double-barrier-packet-transmission", lambda: _scattering(True)),
        ("double-well-eigenpair-and-transfer", _double_well),
        ("curated-geometry-spatial-refinement", _geometry_refinement),
        ("waveguide-finite-window-mode-content", _waveguide_modes),
        ("published-slit-screen-profile-refinement", _slit_profiles),
    ]
    results = [_run_case(name, check) for name, check in cases + (full_cases if suite == "full" else [])]
    passed = sum(case["status"] == "passed" for case in results)
    hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources}
    changed_sources = [name for name in sources if hashes[name] != hashes_at_start[name]]
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        revision = None
    report: dict[str, Any] = {
        "schema_version": 1, "suite": suite, "created_utc": datetime.now(UTC).isoformat(),
        "status": "passed" if passed == len(results) and not changed_sources else "failed",
        "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results)},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "platform": platform.platform()},
        "provenance": {"code_revision": revision, "source_sha256": hashes, "source_sha256_at_start": hashes_at_start,
                       "sources_changed_during_run": changed_sources,
                       "configuration_hash": "SHA256 of canonical JSON containing configuration and any explicit initial-state/potential overrides", "random_test_seed": 1729},
        "cases": results, "not_run": [] if suite == "full" else [name for name, _ in full_cases],
        "limitations": ["Passing fixed fixtures does not certify arbitrary configurations or general quantum accuracy.",
                        "Spectral local current is a diagnostic, not an exact finite-grid continuity certificate."]}
    if output is not None:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "validation.json"
        report["artifact_path"] = str(path.resolve())
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as stream:
            stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
            temporary = Path(stream.name)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return report
