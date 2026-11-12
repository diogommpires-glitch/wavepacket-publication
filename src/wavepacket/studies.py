"""Frozen work/precision protocols and finite-bandwidth tunnelling measurements."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from scipy.linalg import eigh, expm
from scipy.special import erfc

from .config import SimulationConfig, config_fingerprint
from .model import initial_state, make_grid
from .observables import measure
from .operators import absorber, apply_hamiltonian, potential
from .propagators import make_stepper
from .validation import (
    fixture,
    gaussian_transmission_reference,
    independent_hamiltonian,
    state_error,
)

THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def _coherent(config: SimulationConfig, t: float) -> np.ndarray:
    grid = make_grid(config.grid)
    omega = np.asarray(config.state.params["omega"], float)
    angle = float(config.state.params.get("angle", 0))
    rotation = np.eye(1) if grid.ndim == 1 else np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    q0 = rotation.T @ np.asarray(config.state.center)
    p0 = rotation.T @ np.asarray(config.state.momentum)
    q = q0 * np.cos(omega * t) + p0 / omega * np.sin(omega * t)
    p = p0 * np.cos(omega * t) - omega * q0 * np.sin(omega * t)
    displacement = [x - c for x, c in zip(grid.mesh, rotation @ q, strict=True)]
    normal = [sum(rotation[j, i] * displacement[j] for j in range(grid.ndim)) for i in range(grid.ndim)]
    state = np.ones(grid.shape, complex)
    for x, frequency in zip(normal, omega, strict=True):
        state *= (frequency / np.pi)**0.25 * np.exp(-0.5 * frequency * x**2)
    phase = 0.5 * float(p @ q - p0 @ q0) - 0.5 * float(omega.sum()) * t
    state *= np.exp(1j * (sum(k * x for k, x in zip(rotation @ p, displacement, strict=True)) + phase))
    return state


def accuracy_cost_protocol() -> dict[str, Any]:
    smooth = fixture(points=128, length=16, duration=0.8, kinetic="fd2",
                     state={"kind": "ho_coherent", "center": [-2.0], "momentum": [1.0], "sigma": [1.0], "params": {"omega": [1.0]}},
                     potential_spec={"kind": "harmonic", "params": {"omega": [1.0]}})
    barrier = fixture(points=128, length=16, duration=1.6, kinetic="fd2",
                      state={"kind": "gaussian", "center": [-3.0], "momentum": [2.0], "sigma": [0.8]},
                      potential_spec={"kind": "rectangle", "params": {"height": 2.5, "width": 1.0}})
    rotated = fixture(ndim=2, points=96, length=20, duration=1.0,
                      state={"kind": "ho_coherent", "center": [2.0, -1.0], "momentum": [0.5, 1.0], "sigma": [1.0, 1.0],
                             "params": {"omega": [1.0, 1.5], "angle": math.pi / 6}},
                      potential_spec={"kind": "harmonic", "params": {"omega": [1.0, 1.5], "angle": math.pi / 6}})
    return {"schema_version": 2, "study": "accuracy-cost", "seed": 1729,
            "warmups": 1, "repeats": 5, "thread_environment_required": dict.fromkeys(THREAD_VARIABLES, "1"),
            "accuracy_targets_raw_l2": [1e-3, 1e-5, 1e-7],
            "panels": [
                {"id": "1d-smooth-same-fd2-H", "config": smooth.model_dump(mode="json"),
                 "methods": ["cn", "strang", "yoshida4"], "timesteps": [0.08 / 2**i for i in range(12)],
                 "reference": "independent dense Hermitian eigendecomposition, cross-checked with dense expm"},
                {"id": "1d-barrier-same-fd2-H", "config": barrier.model_dump(mode="json"),
                 "methods": ["cn", "strang", "yoshida4"], "timesteps": [0.04 / 2**i for i in range(12)],
                 "reference": "independent dense Hermitian eigendecomposition, cross-checked with dense expm",
                 "barrier_edges": "V=height for abs(x)<width/2; nodes on either edge have V=0, with no smoothing"},
                {"id": "2d-rotated-continuum", "config": rotated.model_dump(mode="json"),
                 "methods": ["strang", "yoshida4"], "timesteps": [0.08 / 2**i for i in range(9)],
                 "reference": "analytic continuum coherent state including its global dynamical phase"}],
            "timing": "One first call per case followed by five retained rounds; each round independently shuffled with seed1729. Reference generation and artifact I/O excluded.",
            "error_budget": "Raw complex L2 is primary. Global-phase-aligned L2 is secondary. Fixed-H temporal error is separated from grid, domain and reference differences. Closed Hamiltonians only; no CAP method comparison."}


def _freeze(protocol: dict, output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    path = output / "protocol.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != protocol:
        raise ValueError(f"frozen study protocol differs at {path}; choose a new output directory")
    path.write_text(json.dumps(protocol, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "protocol.sha256").write_text(digest + "\n", encoding="ascii")
    return digest


def _reference(config: SimulationConfig) -> tuple[np.ndarray, float]:
    grid = make_grid(config.grid)
    if grid.ndim == 2:
        return _coherent(config, config.solver.duration), 0.0
    matrix = independent_hamiltonian(grid, potential(config, grid), config.solver.kinetic)
    values, vectors = eigh(matrix)
    psi = initial_state(config, grid)
    reference = vectors @ (np.exp(-1j * values * config.solver.duration) * (vectors.conj().T @ psi))
    crosscheck = expm(-1j * matrix * config.solver.duration) @ psi
    return reference, state_error(reference, crosscheck, grid)


def _gaussian_domain_tail_bound(config: SimulationConfig) -> float:
    omega = np.asarray(config.state.params["omega"], float)
    angle = float(config.state.params.get("angle", 0))
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    q0 = rotation.T @ np.asarray(config.state.center)
    p0 = rotation.T @ np.asarray(config.state.momentum)
    center_envelope = np.abs(rotation) @ np.sqrt(q0**2 + (p0 / omega)**2)
    variance = np.diag(rotation @ np.diag(1 / (2*omega)) @ rotation.T)
    # Union bound on laboratory-axis Gaussian tails, uniform over all oscillator times.
    return float(sum(0.5*erfc((hi - bound)/math.sqrt(2*var))
                     + 0.5*erfc((-lo - bound)/math.sqrt(2*var))
                     for (lo, hi), bound, var in zip(config.grid.bounds, center_envelope, variance, strict=True)))


def _spatial_domain_budget(config: SimulationConfig, reference: np.ndarray) -> dict:
    grid = make_grid(config.grid)
    if grid.ndim == 2:
        # Spectral differentiation of the known state measures a separate continuum residual.
        from .operators import apply_hamiltonian
        now = config.solver.duration
        h = 1e-4
        derivative = (_coherent(config, now - 2*h) - 8*_coherent(config, now - h)
                      + 8*_coherent(config, now + h) - _coherent(config, now + 2*h)) / (12*h)
        residual = apply_hamiltonian(reference, grid, potential(config, grid)) - 1j * derivative
        return {"continuum_schrodinger_residual_l2": float(np.linalg.norm(residual) * math.sqrt(grid.cell_volume)),
                "domain_tail_mass_bound": _gaussian_domain_tail_bound(config),
                "qualification": "Residual and Gaussian tail bound are diagnostics, not a rigorous accumulated error bound."}
    samples = []
    previous_state = reference
    previous_grid = grid
    for factor, domain in ((2, False), (4, False), (2, True)):
        data = config.model_dump()
        data["grid"]["points"] = [grid.points[0] * factor]
        if domain:
            lo, hi = grid.bounds[0]
            data["grid"]["bounds"] = [[2*lo, 2*hi]]
        refined = SimulationConfig.model_validate(data)
        state, uncertainty = _reference(refined)
        if domain:
            start = grid.points[0] // 2
            restricted = state[start:start+grid.points[0]]
        else:
            restricted = state[::factor]
        sample = {"kind": "domain" if domain else "space", "config": refined.model_dump(mode="json"),
                  "reference_crosscheck_l2": uncertainty, "raw_l2_change": state_error(reference, restricted, grid)}
        if not domain:
            sample["raw_l2_change_from_previous_grid"] = state_error(previous_state, state[::2], previous_grid)
            previous_state, previous_grid = state, make_grid(refined.grid)
        samples.append(sample)
    result: dict[str, Any] = {"refinement_samples": samples,
              "qualification": "Grid changes compare exact evolutions of different discrete Hamiltonians, independently of timed temporal errors."}
    if config.potential.kind == "harmonic":
        result["fd2_to_analytic_continuum_raw_l2"] = state_error(reference, _coherent(config, config.solver.duration), grid)
    return result


def _trial(config: SimulationConfig) -> tuple[np.ndarray, dict[str, float], dict]:
    started = time.perf_counter()
    grid = make_grid(config.grid)
    values = potential(config, grid)
    state = initial_state(config, grid)
    step = make_stepper(config, grid, values)
    setup = time.perf_counter() - started
    stepping_started = time.perf_counter()
    for index in range(config.n_steps):
        state = step(state, min(config.solver.dt, config.solver.duration - index * config.solver.dt))
    stepping = time.perf_counter() - stepping_started
    diagnostics_started = time.perf_counter()
    diagnostics = measure(state, grid, values, kinetic=config.solver.kinetic)
    diagnostics_seconds = time.perf_counter() - diagnostics_started
    return state, {"setup_seconds": setup, "stepping_seconds": stepping,
                   "diagnostics_seconds": diagnostics_seconds, "total_seconds": time.perf_counter() - started}, diagnostics


def target_attainment(rows: list[dict], targets: list[float]) -> list[dict]:
    result = []
    for method in dict.fromkeys(row["method"] for row in rows):
        candidates = [row for row in rows if row["method"] == method]
        for target in targets:
            reached = [row for row in candidates if row["raw_l2_error"] <= target]
            best = min(reached, key=lambda row: row["warm_total_median_seconds"]) if reached else None
            result.append({"method": method, "target_raw_l2": target,
                           "status": "attained" if best else "unattained_on_frozen_sweep",
                           "best_timestep": best["dt"] if best else None,
                           "warm_total_median_seconds": best["warm_total_median_seconds"] if best else None,
                           "smallest_measured_raw_l2": min(row["raw_l2_error"] for row in candidates)})
    return result


def run_accuracy_cost(output: str | Path) -> dict[str, Any]:
    protocol = accuracy_cost_protocol()
    directory = Path(output)
    digest = _freeze(protocol, directory)
    source_hashes = _source_hashes()
    if any(os.environ.get(key) != "1" for key in THREAD_VARIABLES):
        raise ValueError("run scripts/run_studies.py so numerical-library thread counts are fixed before import")
    rng = np.random.default_rng(protocol["seed"])
    results = []
    order = []
    for panel in protocol["panels"]:
        base = SimulationConfig.model_validate(panel["config"])
        reference, uncertainty = _reference(base)
        budget = _spatial_domain_budget(base, reference)
        cases: list[dict[str, Any]] = []
        for method in panel["methods"]:
            for dt in panel["timesteps"]:
                data = base.model_dump()
                data["solver"].update(method=method, dt=dt)
                config = SimulationConfig.model_validate(data)
                cases.append({"config": config, "samples": []})
        for repeat in range(protocol["repeats"] + 1):
            for case_index in rng.permutation(len(cases)):
                case = cases[int(case_index)]
                config = case["config"]
                state, timing, diagnostics = _trial(config)
                order.append({"panel": panel["id"], "round": repeat, "case": int(case_index)})
                if repeat == 0:
                    case["first"] = timing
                    grid = make_grid(config.grid)
                    case["raw_l2_error"] = state_error(state, reference, grid)
                    case["phase_aligned_l2_error"] = state_error(state, reference, grid, align=True)
                    case["diagnostics"] = diagnostics
                else:
                    case["samples"].append(timing)
        rows = []
        for case in cases:
            config = case["config"]
            totals = [item["total_seconds"] for item in case["samples"]]
            rows.append({"method": config.solver.method, "dt": config.solver.dt,
                         "n_steps": config.n_steps, "configuration_sha256": config_fingerprint(config),
                         "config": config.model_dump(mode="json"), "first_call": case["first"],
                         "warm_timings": case["samples"], "warm_total_median_seconds": float(np.median(totals)),
                         "warm_total_iqr_seconds": float(np.percentile(totals, 75) - np.percentile(totals, 25)),
                         "raw_l2_error": case["raw_l2_error"], "phase_aligned_l2_error": case["phase_aligned_l2_error"],
                         "diagnostics": case["diagnostics"],
                         "fft_pairs": config.n_steps * (3 if config.solver.method == "yoshida4" else 1) if config.solver.method != "cn" else 0,
                         "sparse_solves": config.n_steps if config.solver.method == "cn" else 0})
        results.append({"id": panel["id"], "reference_crosscheck_l2": uncertainty,
                        "error_budget": budget, "measurements": rows,
                        "target_attainment": target_attainment(rows, protocol["accuracy_targets_raw_l2"])})
    report: dict[str, Any] = {"schema_version": 2, "study": "accuracy-cost", "status": "measured",
              "created_utc": datetime.now(UTC).isoformat(), "protocol_sha256": digest,
              "provenance": _provenance(source_hashes),
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                              "platform": platform.platform(), "threads": {key: os.environ[key] for key in THREAD_VARIABLES}},
              "panels": results, "execution_order": order,
              "limitations": ["Timing is machine-specific and excludes import, reference generation and artifact I/O.",
                              "Targets refer to the stated panel reference. Fixed-H temporal accuracy does not imply continuum accuracy.",
                              "Unattained targets remain reported; a finite sweep does not prove a method cannot attain them."]}
    if report["provenance"]["sources_changed_during_run"]:
        report["status"] = "invalidated_by_source_changes"
    (directory / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _plot_accuracy_cost(report, directory)
    return report


def tunnelling_protocol() -> dict[str, Any]:
    config = fixture(points=8192, length=400, duration=64, dt=0.01, method="cn", kinetic="fd2",
                     state={"kind": "gaussian", "center": [-30.0], "momentum": [2.0], "sigma": [3.0]},
                     potential_spec={"kind": "double_barrier", "params": {"height": 2.5, "width": 1.0, "separation": 5.0}})
    return {"schema_version": 2, "study": "tunnelling", "config": config.model_dump(mode="json"),
            "momentum_centers": [1.8744, 2.0], "density_sigma": [1.5, 3.0, 6.0],
            "segments": [[2.5, 1.0], [0.0, 4.0], [2.5, 1.0]],
            "sample_times": [16.0, 32.0, 64.0], "interaction_interval": [-4.0, 4.0],
            "reference_accuracy_target": 1e-7,
            "refinement_case": {"momentum": 1.8744, "sigma": 3.0, "space_points": 16384, "time_dt": 0.005},
            "interpretation": "Report R,T,retained interaction mass and dwell integral at each time; do not force early R+T=1. The asymptotic Gaussian bandwidth average is a reference, not a finite-time identity."}


def _tunnelling_run(config: SimulationConfig, sample_times: list[float], interval: list[float]) -> dict:
    grid = make_grid(config.grid)
    x = grid.axes[0]
    state = initial_state(config, grid)
    values = potential(config, grid)
    initial_energy = float(np.vdot(state, apply_hamiltonian(state, grid, values, config.solver.kinetic)).real*grid.cell_volume)
    initial_barrier_overlap = float(np.sum(np.abs(state[values != 0])**2)*grid.cell_volume)
    step = make_stepper(config, grid, values, absorber(config, grid))
    left, right = x < interval[0], x > interval[1]
    interaction = ~(left | right)
    retained = float(np.sum(np.abs(state[interaction])**2) * grid.cell_volume)
    dwell = 0.0
    samples = []
    for index in range(config.n_steps):
        dt = min(config.solver.dt, config.solver.duration - index * config.solver.dt)
        state = step(state, dt)
        density = np.abs(state)**2
        now_retained = float(np.sum(density[interaction]) * grid.cell_volume)
        dwell += 0.5 * dt * (retained + now_retained)
        retained = now_retained
        now = min((index + 1) * config.solver.dt, config.solver.duration)
        if any(abs(now - target) < 1e-10 for target in sample_times):
            reflected = float(np.sum(density[left]) * grid.cell_volume)
            transmitted = float(np.sum(density[right]) * grid.cell_volume)
            norm = reflected + transmitted + retained
            energy = float(np.vdot(state, apply_hamiltonian(state, grid, values, config.solver.kinetic)).real*grid.cell_volume)
            samples.append({"time": now, "left_probability": reflected, "right_probability": transmitted,
                            "retained_interaction_probability": retained, "surviving_norm": norm,
                            "partition_error": abs(norm + step.total_absorbed - 1),
                            "relative_energy_change": abs(energy-initial_energy)/max(1.0, abs(initial_energy)),
                            "interaction_dwell_integral": dwell,
                            "edge_probability": float(np.sum(density[np.abs(x) > 0.45*(grid.bounds[0][1]-grid.bounds[0][0])]) * grid.cell_volume)})
    return {"configuration_sha256": config_fingerprint(config), "config": config.model_dump(mode="json"),
            "initial_barrier_overlap_probability": initial_barrier_overlap,
            "initial_energy": initial_energy, "samples": samples}


def run_tunnelling(output: str | Path) -> dict[str, Any]:
    protocol = tunnelling_protocol()
    directory = Path(output)
    digest = _freeze(protocol, directory)
    source_hashes = _source_hashes()
    if any(os.environ.get(key) != "1" for key in THREAD_VARIABLES):
        raise ValueError("run scripts/run_studies.py so numerical-library thread counts are fixed before import")
    rows = []
    for momentum in protocol["momentum_centers"]:
        for sigma in protocol["density_sigma"]:
            data = json.loads(json.dumps(protocol["config"]))
            data["state"].update(momentum=[momentum], sigma=[sigma])
            reference = gaussian_transmission_reference(momentum, sigma, [tuple(pair) for pair in protocol["segments"]],
                                                        accuracy_target=protocol["reference_accuracy_target"])
            result = _tunnelling_run(SimulationConfig.model_validate(data), protocol["sample_times"], protocol["interaction_interval"])
            for sample in result["samples"]:
                sample["finite_time_transmission_difference"] = sample["right_probability"] - reference["weighted_transmission"]
            rows.append({"momentum": momentum, "sigma": sigma, "momentum_standard_deviation": 1/(2*sigma),
                         "reference": reference, **result})
    setting = protocol["refinement_case"]
    baseline = next(row for row in rows if row["momentum"] == setting["momentum"] and row["sigma"] == setting["sigma"])
    refinements = []
    for kind in ("space", "time", "domain"):
        data = json.loads(json.dumps(baseline["config"]))
        if kind == "space":
            data["grid"]["points"] = [setting["space_points"]]
        elif kind == "time":
            data["solver"]["dt"] = setting["time_dt"]
        else:
            data["grid"]["bounds"] = [[-300.0, 300.0]]
            data["grid"]["points"] = [12288]
        refined = _tunnelling_run(SimulationConfig.model_validate(data), protocol["sample_times"], protocol["interaction_interval"])
        changes = [{"time": sample["time"],
                    **{f"{key}_change": abs(sample[key] - base[key]) for key in
                       ("right_probability", "retained_interaction_probability", "interaction_dwell_integral")}}
                   for sample, base in zip(refined["samples"], baseline["samples"], strict=True)]
        refinements.append({"axis": kind, "changes": changes, **refined})
    report: dict[str, Any] = {"schema_version": 2, "study": "tunnelling", "status": "measured",
              "created_utc": datetime.now(UTC).isoformat(), "protocol_sha256": digest,
              "provenance": _provenance(source_hashes),
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                              "platform": platform.platform(), "threads": {key: os.environ[key] for key in THREAD_VARIABLES}},
              "packets": rows, "refinement": refinements,
              "limitations": ["A finite-time retained population can coexist with transmission and reflection.",
                              "Dwell is the unconditioned time integral of interaction-region probability; it is not a unique tunnelling traversal time.",
                              "Discontinuous barrier edges cause spatial error. The independently reported grid and domain changes qualify the finite-grid results."]}
    if report["provenance"]["sources_changed_during_run"]:
        report["status"] = "invalidated_by_source_changes"
    (directory / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _plot_tunnelling(report, directory)
    return report


def _source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
            ("config.py", "model.py", "operators.py", "propagators.py", "observables.py", "validation.py", "studies.py", "units.py", "experiments.py")}


def _provenance(start: dict[str, str]) -> dict:
    end = _source_hashes()
    return {"source_sha256": end, "source_sha256_at_start": start,
            "sources_changed_during_run": [name for name in start if start[name] != end[name]]}


def _plot_accuracy_cost(report: dict, directory: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, len(report["panels"]), figsize=(15, 4.5), constrained_layout=True)
    for axis, panel in zip(axes, report["panels"], strict=True):
        for method in dict.fromkeys(row["method"] for row in panel["measurements"]):
            rows = [row for row in panel["measurements"] if row["method"] == method]
            cost = [row["warm_total_median_seconds"] for row in rows]
            line = axis.loglog(cost, [row["raw_l2_error"] for row in rows], "o-", label=f"{method}, raw")[0]
            axis.loglog(cost, [row["phase_aligned_l2_error"] for row in rows], ":", color=line.get_color(), alpha=0.6)
        for target in (1e-3, 1e-5, 1e-7):
            axis.axhline(target, color="gray", alpha=0.25, linewidth=0.8)
        axis.set(title=panel["id"], xlabel="Warm total median (s)", ylabel="Complex state L2 error")
        axis.legend(fontsize=8)
        axis.grid(alpha=0.2)
    figure.suptitle("Fixed protocol work/precision — dotted lines remove global phase")
    figure.savefig(directory / "accuracy-cost.png", dpi=180)
    figure.savefig(directory / "accuracy-cost.pdf")
    plt.close(figure)


def _plot_tunnelling(report: dict, directory: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for row in report["packets"]:
        times = [sample["time"] for sample in row["samples"]]
        label = f"k={row['momentum']}, sigma={row['sigma']}"
        line = axes[0].plot(times, [sample["right_probability"] for sample in row["samples"]], "o-", label=label)[0]
        axes[0].axhline(row["reference"]["weighted_transmission"], color=line.get_color(), linestyle=":", alpha=0.35)
        axes[1].plot(times, [sample["retained_interaction_probability"] for sample in row["samples"]], "o-", label=label)
    axes[0].set(xlabel="Time", ylabel="Right-region probability", title="Dotted: asymptotic bandwidth reference")
    axes[1].set(xlabel="Time", ylabel="Interaction-region probability", title="Retained mass remains explicit")
    for axis in axes:
        axis.grid(alpha=0.2)
        axis.legend(fontsize=7)
    figure.savefig(directory / "tunnelling.png", dpi=180)
    figure.savefig(directory / "tunnelling.pdf")
    plt.close(figure)
