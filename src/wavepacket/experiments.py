"""Curated experiments: scientific questions, limitations, and reproducible inputs.

Evidence labels describe the validation route, not a certificate for arbitrary
edits to a preset.  The validation report contains the checks actually run.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from .config import SimulationConfig, config_fingerprint


def _config(
    name: str, *, dimension: int = 1, potential: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None, bounds: list[list[float]] | None = None,
    points: list[int] | None = None, duration: float = 8.0, dt: float = 0.01,
    cap: bool = False,
) -> dict[str, Any]:
    if dimension == 1:
        bounds = bounds or [[-40.0, 40.0]]
        points = points or [1024]
        initial = {"kind": "gaussian", "center": [-12.0], "momentum": [2.0], "sigma": [2.0]}
    else:
        bounds = bounds or ([[-42.0, 42.0], [-30.0, 30.0]] if cap else [[-24.0, 24.0], [-18.0, 18.0]])
        points = points or ([448, 320] if cap else [256, 192])
        initial = {"kind": "gaussian", "center": [-12.0, 0.0], "momentum": [3.0, 0.0], "sigma": [2.0, 2.0]}
    return {
        "name": name,
        "grid": {"bounds": bounds, "points": points},
        "state": state or initial,
        "potential": potential or {"kind": "free"},
        "solver": {"method": "strang", "kinetic": "spectral", "dt": dt, "duration": duration},
        "boundary": {"kind": "cap" if cap else "periodic", "width": (25.0 if dimension == 1 else 15.0) if cap else 5.0, "strength": 4.0, "power": 4},
        "sampling": {"observable_every": 10, "snapshots": 81, "screen_x": 6.0 if dimension == 2 else None},
        "units": {"mode": "dimensionless", "length_nm": 1.0},
    }


def _entry(identifier: str, title: str, dimension: int, question: str, evidence: str,
           limitations: list[str], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": identifier, "title": title, "name": title, "dimension": dimension,
        "scientific_question": question, "evidence": evidence,
        "validation_status": "See the saved validation report; custom edits are unverified.",
        "limitations": limitations, "config": config,
    }


_EXPERIMENTS = [
    _entry("1d-free", "Free Gaussian dispersion", 1,
           "How do a packet's centre, width and phase evolve without a potential?", "analytic",
           ["The finite periodic domain approximates the line only before boundary wraparound."],
           _config("1d-free", duration=8.0)),
    _entry("1d-interference", "Counterpropagating coherent packets", 1,
           "How does the relative phase change the interference of two freely evolving packets?", "analytic",
           ["These are coherent components of one single-particle state, not two interacting particles."],
           _config("1d-interference", duration=8.0, state={
               "kind": "sum", "params": {"components": [
                   {"state": {"center": [-10.0], "momentum": [2.0], "sigma": [1.5]}, "amplitude": 1.0},
                   {"state": {"center": [10.0], "momentum": [-2.0], "sigma": [1.5]}, "amplitude": 1.0},
               ]}})),
    _entry("1d-coherent", "Harmonic coherent-state motion", 1,
           "Does the oscillator packet follow the exact centre trajectory without changing its width?", "analytic",
           ["The harmonic model is a prescribed external potential; it contains no dissipation."],
           _config("1d-coherent", bounds=[[-12.0, 12.0]], points=[512], duration=2 * math.pi, dt=0.005,
                   potential={"kind": "harmonic", "params": {"omega": [1.0]}},
                   state={"kind": "ho_coherent", "center": [-3.0], "momentum": [1.0], "sigma": [1.0], "params": {"omega": [1.0]}})),
    _entry("1d-squeezed", "Squeezed oscillator breathing", 1,
           "How does an initially squeezed state's position variance oscillate?", "analytic-moments",
           ["The state is a Gaussian squeezed state; no quantum-optics measurement apparatus is modelled."],
           _config("1d-squeezed", bounds=[[-12.0, 12.0]], points=[512], duration=2 * math.pi, dt=0.005,
                   potential={"kind": "harmonic", "params": {"omega": [1.0]}},
                   state={"kind": "ho_squeezed", "center": [0.0], "momentum": [0.0], "sigma": [1.0], "params": {"omega": [1.0], "squeeze": [0.65]}})),
    _entry("1d-barrier", "Finite rectangular-barrier scattering", 1,
           "Does packet transmission approach its momentum-weighted stationary-scattering reference?", "scattering-reference",
           ["A finite-bandwidth packet is not a plane wave at its mean energy.", "R/T is meaningful after separation; barrier discontinuities require spatial refinement."],
           _config("1d-barrier", bounds=[[-60.0, 60.0]], points=[2048], duration=22.0, dt=0.001, cap=True,
                   potential={"kind": "rectangle", "params": {"height": 2.5, "width": 2.0, "center": 0.0}},
                   state={"kind": "gaussian", "center": [-20.0], "momentum": [2.0], "sigma": [3.0]})),
    _entry("1d-double-barrier", "Double-barrier resonance and dwell", 1,
           "How do finite momentum bandwidth and transient trapped probability alter resonant transmission?", "scattering-reference",
           ["Narrow resonances can require much longer propagation and wider packets.", "Interaction-region probability must be reported rather than prematurely forcing R+T=1."],
           _config("1d-double-barrier", bounds=[[-70.0, 70.0]], points=[2048], duration=35.0, dt=0.005, cap=True,
                   potential={"kind": "double_barrier", "params": {"height": 2.5, "width": 1.0, "separation": 5.0}},
                   state={"kind": "gaussian", "center": [-24.0], "momentum": [2.0], "sigma": [4.0]})),
    _entry("1d-double-well", "Double-well coherent transfer", 1,
           "How does the lowest eigenpair's energy splitting determine coherent probability transfer?", "discrete-eigen-reference",
           ["This is a closed single-particle double well; it does not model chemistry or environmental decoherence.", "The initial state is a normalized superposition of the two lowest discrete eigenstates."],
           _config("1d-double-well", bounds=[[-12.0, 12.0]], points=[512], duration=80.0, dt=0.01,
                   potential={"kind": "double_well", "params": {"height": 0.4, "separation": 5.0, "tilt": 0.0}},
                   state={"kind": "eigen_superposition", "center": [0.0], "momentum": [0.0], "sigma": [1.0], "params": {"indices": [0, 1], "coefficients": [1.0, 1.0]}})),
    _entry("1d-gaussian-barrier", "Smooth Gaussian-barrier scattering", 1,
           "How does smooth-barrier transmission change with energy and numerical resolution?", "empirical-convergence",
           ["Convergence and independent propagation checks establish numerical evidence, not a closed-form transmission formula."],
           _config("1d-gaussian-barrier", bounds=[[-60.0, 60.0]], points=[1024], duration=22.0, dt=0.005, cap=True,
                   potential={"kind": "gaussian", "params": {"height": 2.5, "sigma": 1.0, "center": 0.0}},
                   state={"kind": "gaussian", "center": [-20.0], "momentum": [2.0], "sigma": [3.0]})),
    _entry("2d-free", "Two-dimensional free dispersion", 2,
           "Does the two-dimensional implementation reproduce the product of exact one-dimensional packets?", "analytic",
           ["The packet is separable; the rotated-oscillator test adds a nonseparable verification case."],
           _config("2d-free", dimension=2, duration=5.0,
                   state={"kind": "gaussian", "center": [-6.0, -4.0], "momentum": [1.0, 0.5], "sigma": [1.5, 1.5]})),
    _entry("2d-crossing", "Crossing coherent wave packets", 2,
           "How do coherent packet components interfere while propagating through one another?", "analytic",
           ["The components belong to one coherent state; their crossing does not simulate particle-particle collisions."],
           _config("2d-crossing", dimension=2, duration=7.0, state={
               "kind": "sum", "center": [0.0, 0.0], "momentum": [0.0, 0.0], "sigma": [1.5, 1.5],
               "params": {"components": [
                   {"state": {"center": [-8.0, -4.0], "momentum": [2.0, 1.0], "sigma": [1.5, 1.5]}, "amplitude": 1.0},
                   {"state": {"center": [8.0, 4.0], "momentum": [-2.0, -1.0], "sigma": [1.5, 1.5]}, "amplitude": 1.0},
               ]}})),
    _entry("2d-orbit", "Coherent oscillator orbit", 2,
           "Does a localized packet follow the exact two-axis harmonic orbit?", "analytic-moments",
           ["The orbit describes expectation values of a wave function, not a classical particle trajectory."],
           _config("2d-orbit", dimension=2, bounds=[[-10.0, 10.0], [-10.0, 10.0]], points=[192, 192], duration=2 * math.pi, dt=0.005,
                   potential={"kind": "harmonic", "params": {"omega": [1.0, 1.0]}},
                   state={"kind": "ho_coherent", "center": [3.0, 0.0], "momentum": [0.0, 3.0], "sigma": [1.0, 1.0], "params": {"omega": [1.0, 1.0]}})),
    _entry("2d-rotated", "Rotated anisotropic oscillator", 2,
           "Can the engine reproduce coupled laboratory-axis motion and rotated Gaussian covariance?", "analytic-moments",
           ["The normal-mode problem is analytically solvable, although the state and potential are nonseparable in display axes."],
           _config("2d-rotated", dimension=2, bounds=[[-10.0, 10.0], [-10.0, 10.0]], points=[192, 192], duration=6.0, dt=0.005,
                   potential={"kind": "harmonic", "params": {"omega": [1.0, 1.5], "angle": math.pi / 6}},
                   state={"kind": "ho_coherent", "center": [2.0, -1.0], "momentum": [0.5, 1.0], "sigma": [1.0, 1.0], "params": {"omega": [1.0, 1.5], "angle": math.pi / 6}})),
    _entry("2d-single-slit", "Single-slit diffraction", 2,
           "How does finite-aperture geometry change the outgoing probability distribution?", "empirical-convergence",
           ["A finite-height prescribed wall is not an ideal impenetrable screen.", "A density snapshot is not a detector arrival distribution."],
           _config("2d-single-slit", dimension=2, duration=11.0, dt=0.005, cap=True,
                   potential={"kind": "slit", "params": {"height": 30.0, "xcenter": 0.0, "thickness": 1.0, "slit_width": 3.0, "slit_separation": 6.0, "count": 1, "smoothing": 0.25}},
                   state={"kind": "gaussian", "center": [-12.0, 0.0], "momentum": [3.0, 0.0], "sigma": [2.0, 4.0]})),
    _entry("2d-double-slit", "Double-slit interference", 2,
           "Which interference features persist under timestep, grid and wall-resolution refinement?", "empirical-convergence",
           ["The prescribed static wall does not model measurement or wave-function collapse.", "Signed screen current can include recrossings; clipping it changes the observable."],
           _config("2d-double-slit", dimension=2, duration=11.0, dt=0.005, cap=True,
                   potential={"kind": "slit", "params": {"height": 30.0, "xcenter": 0.0, "thickness": 1.0, "slit_width": 2.0, "slit_separation": 6.0, "count": 2, "smoothing": 0.25}},
                   state={"kind": "gaussian", "center": [-12.0, 0.0], "momentum": [3.0, 0.0], "sigma": [2.0, 4.0]})),
    _entry("2d-obstacle", "Scattering from a circular obstacle", 2,
           "How do an extended incident packet and a smooth circular potential redistribute probability?", "empirical-convergence",
           ["The finite packet does not directly define a monochromatic scattering cross-section."],
           _config("2d-obstacle", dimension=2, duration=10.0, dt=0.005, cap=True,
                   potential={"kind": "disk", "params": {"height": 20.0, "radius": 2.5, "center": [0.0, 0.0], "smoothing": 0.3}},
                   state={"kind": "gaussian", "center": [-12.0, 0.0], "momentum": [3.0, 0.0], "sigma": [2.0, 4.0]})),
    _entry("2d-waveguide", "Bent finite-wall waveguide", 2,
           "How do bend geometry and transverse confinement affect transmission and reflection?", "empirical-convergence",
           ["Finite walls permit tunnelling and the bend can excite transverse modes.", "This is a single-particle external-potential model, not a material device simulation."],
           _config("2d-waveguide", dimension=2, duration=10.0, dt=0.005, cap=True,
                   potential={"kind": "waveguide", "params": {"height": 25.0, "width": 5.0, "bend_x": 0.0, "angle": math.pi / 8, "center_y": 0.0, "smoothing": 0.3}},
                   state={"kind": "waveguide_mode", "center": [-12.0, 0.0], "momentum": [3.0, 0.0], "sigma": [2.0, 0.8], "params": {"mode": 0}})),
]


def list_experiments() -> list[dict[str, Any]]:
    """Return independent metadata/config copies suitable for JSON or the lab UI."""
    entries = copy.deepcopy(_EXPERIMENTS)
    for entry in entries:
        config = get_experiment(entry["id"])
        entry["evidence_record"] = {
            "configuration_sha256": config_fingerprint(config), "status": "report_required",
            "check_ids": ["preset-boundary-sensitivity"] if config.boundary.kind == "cap" else [],
            "scope": "A matching saved check certifies only its stated configuration, duration and observable; custom edits are unverified.",
            "conditions": {"boundary": config.boundary.model_dump(mode="json"),
                           "packet_momentum": config.state.momentum, "packet_sigma": config.state.sigma,
                           "duration": config.solver.duration, "dt": config.solver.dt,
                           "grid": config.grid.model_dump(mode="json")},
        }
    return entries


def get_experiment(identifier: str) -> SimulationConfig:
    for experiment in _EXPERIMENTS:
        if experiment["id"] == identifier:
            return SimulationConfig.model_validate(copy.deepcopy(experiment["config"]))
    raise KeyError(f"unknown experiment {identifier!r}")


def write_examples(directory: str | Path) -> list[Path]:
    """Materialise exactly the configs used by the catalogue; never rewrite inputs."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for experiment in _EXPERIMENTS:
        path = directory / f"{experiment['id']}.json"
        path.write_text(get_experiment(experiment["id"]).model_dump_json(indent=2) + "\n", encoding="utf-8")
        written.append(path)
    manifest = directory / "catalogue.json"
    manifest.write_text(json.dumps(list_experiments(), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return written
