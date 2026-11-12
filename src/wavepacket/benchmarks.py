"""Measured work/precision studies; no machine-dependent performance claims."""
from __future__ import annotations

import json
import math
import os
import platform
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import scipy
from scipy.linalg import expm

from .config import SimulationConfig
from .model import initial_state, make_grid
from .observables import measure
from .operators import potential
from .propagators import make_stepper
from .validation import fixture, independent_hamiltonian, state_error


def _coherent_reference(grid, t: float) -> np.ndarray:
    omega = np.array([1.0, 1.5])
    angle = np.pi / 6
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    q0 = rotation.T @ np.array([2.0, -1.0])
    p0 = rotation.T @ np.array([0.5, 1.0])
    q = q0 * np.cos(omega * t) + p0 / omega * np.sin(omega * t)
    p = p0 * np.cos(omega * t) - omega * q0 * np.sin(omega * t)
    center, momentum = rotation @ q, rotation @ p
    displacement = [coordinate - c for coordinate, c in zip(grid.mesh, center, strict=True)]
    coordinates = [rotation[0, i] * displacement[0] + rotation[1, i] * displacement[1] for i in (0, 1)]
    result = np.ones(grid.shape, complex)
    for coordinate, frequency in zip(coordinates, omega, strict=True):
        result *= (frequency / np.pi)**0.25 * np.exp(-0.5 * frequency * coordinate**2)
    result *= np.exp(1j * sum(k * x for k, x in zip(momentum, displacement, strict=True)))
    return result


def _timed(config: SimulationConfig, reference: np.ndarray, *, align: bool, repeats: int = 3) -> dict:
    measurements = []
    final = None
    # The first iteration warms libraries/FFT paths and is explicitly excluded.
    for repeat in range(repeats + 1):
        started = time.perf_counter()
        grid = make_grid(config.grid)
        values = potential(config, grid)
        psi = initial_state(config, grid)
        step = make_stepper(config, grid, values)
        setup = time.perf_counter() - started
        started = time.perf_counter()
        now = 0.0
        for _ in range(config.n_steps):
            dt = min(config.solver.dt, config.solver.duration - now)
            psi = step(psi, dt)
            now += dt
        stepping = time.perf_counter() - started
        started = time.perf_counter()
        diagnostics = measure(psi, grid, values, kinetic=config.solver.kinetic)
        diagnostic_time = time.perf_counter() - started
        if repeat:
            measurements.append({"setup_seconds": setup, "stepping_seconds": stepping,
                                 "diagnostics_seconds": diagnostic_time})
        final = psi
    assert final is not None
    return {
        "config": config.model_dump(mode="json"), "warmups": 1, "repeats": repeats,
        "timings": measurements,
        "median_seconds": {key: statistics.median(row[key] for row in measurements) for key in measurements[0]},
        "state_error": state_error(final, reference, grid, align=align),
        "error_phase_aligned": align,
        "density_l2_error": float(np.linalg.norm((np.abs(final)**2 - np.abs(reference)**2).ravel()) * math.sqrt(grid.cell_volume)),
        "final_norm": float(np.vdot(final, final).real * grid.cell_volume),
        "diagnostics": diagnostics,
    }


def run_benchmarks(output: str | Path | None = None) -> dict[str, Any]:
    rows = []
    # All1D methods use exactly the same FD2 discrete Hamiltonian and reference.
    base = fixture(points=128, length=16.0, duration=0.8, kinetic="fd2",
                   state={"kind": "gaussian", "center": [-2.0], "momentum": [1.0], "sigma": [1.0]},
                   potential_spec={"kind": "harmonic", "params": {"omega": [1.0]}})
    grid = make_grid(base.grid)
    reference = expm(-1j * independent_hamiltonian(grid, potential(base, grid), "fd2") * 0.8) @ initial_state(base, grid)
    for method in ("cn", "strang", "yoshida4"):
        for dt in (0.08, 0.04, 0.02):
            data = base.model_dump()
            data["solver"].update(method=method, dt=dt)
            row = _timed(SimulationConfig.model_validate(data), reference, align=False)
            rows.append({"family": "1d-same-fd2-H", "reference": "independent-dense-exponential", **row})
    for method in ("strang", "yoshida4"):
        for dt in (0.04, 0.02, 0.01):
            config = fixture(ndim=2, points=128, length=20.0, duration=1.0, dt=dt, method=method,
                             state={"kind": "ho_coherent", "center": [2.0, -1.0], "momentum": [0.5, 1.0], "sigma": [1.0, 1.0],
                                    "params": {"omega": [1.0, 1.5], "angle": np.pi / 6}},
                             potential_spec={"kind": "harmonic", "params": {"omega": [1.0, 1.5], "angle": np.pi / 6}})
            reference = _coherent_reference(make_grid(config.grid), 1.0)
            row = _timed(config, reference, align=True)
            rows.append({"family": "2d-spectral-rotated-oscillator", "reference": "analytic-coherent-state-up-to-global-phase", **row})
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        revision = None
    report: dict[str, Any] = {
        "schema_version": 1, "created_utc": datetime.now(UTC).isoformat(),
        "status": "measured", "code_revision": revision,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "platform": platform.platform(), "processor": platform.processor(),
                        "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
                        "memory_bytes": psutil.virtual_memory().total,
                        "thread_environment": {key: os.environ.get(key) for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}},
        "comparisons": rows,
        "interpretation": ["Compare error against measured work; equal timesteps do not imply equal accuracy or equal work.",
                           "Setup, stepping and final diagnostics are timed separately; reference generation and artifact I/O are excluded.",
                           "One warm-up is excluded and three repetitions are retained; small-case timing remains noisy.",
                           "The1D family fixes the FD2 Hamiltonian; the2D family compares spectral methods to a continuum analytical state.",
                           "No timing threshold is used as a correctness test and no speedup is promised."]}
    if output is not None:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "benchmarks.json"
        report["artifact_path"] = str(path.resolve())
        path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
