"""Grid-weighted observables and separately reported state-error conventions."""
from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy import fft
from scipy.ndimage import map_coordinates

from .config import GridSpec, SimulationConfig
from .model import Grid, _eigenpairs, make_grid
from .operators import apply_hamiltonian, well_wall


def norm(psi: NDArray, grid: Grid) -> float:
    return float(np.vdot(psi, psi).real * grid.cell_volume)


def waveguide_mode_content(config: SimulationConfig, psi: NDArray, grid: Grid, *,
                           longitudinal_window: tuple[float, float] = (4.0, 12.0), count: int = 4) -> dict:
    """Project a finite straight output window onto confined transverse modes."""
    if grid.ndim != 2 or config.potential.kind != "waveguide" or psi.shape != grid.shape:
        raise ValueError("mode content requires a matching two-dimensional waveguide state")
    if count < 1 or count > 9 or longitudinal_window[1] <= longitudinal_window[0]:
        raise ValueError("mode count must be1..9 and longitudinal window must have positive length")
    params = config.potential.params
    angle = float(params.get("angle", math.pi/6))
    bend = float(params.get("bend_x", 0))
    center = float(params.get("center_y", 0))
    width = float(params.get("width", 4))
    height = float(params.get("height", 20))
    smoothing = float(params.get("smoothing", 0.2))
    extent = max(width, 10.0)
    dv = min(grid.spacing)
    points = max(64, math.ceil(2*extent/dv))
    transverse = make_grid(GridSpec(bounds=((-extent, extent),), points=(points,)))
    wall = well_wall(transverse.axes[0], width, height, smoothing)
    energies, modes = _eigenpairs(transverse, wall, config.solver.kinetic, count)
    confined = energies < height
    modes, energies = modes[confined], energies[confined]
    if len(modes) == 0:
        raise ValueError("waveguide has no confined transverse modes in this window")
    du = min(grid.spacing)
    n_long = math.ceil((longitudinal_window[1] - longitudinal_window[0])/du)
    du = (longitudinal_window[1] - longitudinal_window[0])/n_long
    u = longitudinal_window[0] + (np.arange(n_long) + 0.5)*du
    U, V = np.meshgrid(u, transverse.axes[0], indexing="xy")
    x = bend + math.cos(angle)*U - math.sin(angle)*V
    y = center + math.sin(angle)*U + math.cos(angle)*V
    if (np.any(x < grid.bounds[0][0]) or np.any(x > grid.axes[0][-1])
            or np.any(y < grid.bounds[1][0]) or np.any(y > grid.axes[1][-1])):
        raise ValueError("rotated mode window must lie inside the sampled physical domain")
    coordinates = np.array([(y-grid.axes[1][0])/grid.spacing[1], (x-grid.axes[0][0])/grid.spacing[0]])
    sampled = (map_coordinates(psi.real, coordinates, order=3, mode="constant")
               + 1j*map_coordinates(psi.imag, coordinates, order=3, mode="constant"))
    coefficients = modes.conj() @ sampled * transverse.cell_volume
    mode_probabilities = np.sum(np.abs(coefficients)**2, axis=1)*du
    window_probability = float(np.sum(np.abs(sampled)**2)*transverse.cell_volume*du)
    projected = float(mode_probabilities.sum())
    unresolved = window_probability - projected
    if unresolved < -1e-10:
        raise FloatingPointError("transverse mode projection exceeds finite-window probability")
    total = norm(psi, grid)
    floor = 64*np.finfo(float).eps
    X, Y = grid.mesh[0] - bend, grid.mesh[1] - center
    longitudinal = math.cos(angle)*X + math.sin(angle)*Y
    distance = np.where(X < 0, Y, math.cos(angle)*Y - math.sin(angle)*X)
    inside = np.abs(distance) < width/2
    left = X < -4
    right = (X >= 0) & (longitudinal > 4)
    retained = ~(left | right)
    density = np.abs(psi)**2
    partition = {name: float(np.sum(density[mask])*grid.cell_volume) for name, mask in
                 {"incoming_channel": left & inside, "outgoing_channel": right & inside,
                  "retained_channel": retained & inside, "outside_channel": ~inside}.items()}
    return {"longitudinal_window": list(longitudinal_window), "transverse_window": [-extent, extent],
            "mode_energies": energies.tolist(), "mode_probabilities": mode_probabilities.tolist(),
            "window_probability": window_probability, "unresolved_window_probability": max(0.0, unresolved),
            "mode_fractions_in_window": (mode_probabilities/window_probability).tolist() if window_probability > floor else None,
            "conditional_status": "resolved" if window_probability > floor else "below_reporting_floor" if window_probability > 0 else "numerically_zero",
            "surviving_probability_partition": partition, "partition_error": abs(sum(partition.values())-total),
            "interpolation": "cubic in rotated coordinates; refine the physical grid and projection window before interpreting small mode populations"}


def regional_probability(psi: NDArray, grid: Grid, mask: NDArray) -> float:
    if np.shape(mask) != grid.array_shape:
        raise ValueError("region mask must match grid shape")
    return float(np.sum(np.abs(psi) ** 2 * mask) * grid.cell_volume)


def momentum_distribution(psi: NDArray, grid: Grid) -> tuple[tuple[NDArray, ...], NDArray]:
    """Return unshifted k axes and probability PER BIN (not continuum density)."""
    axes = tuple(2 * np.pi * fft.fftfreq(n, d=dx) for n, dx in zip(grid.points, grid.spacing, strict=True))
    probability = np.abs(fft.fftn(psi, norm="ortho")) ** 2 * grid.cell_volume
    return axes, probability


def current(psi: NDArray, grid: Grid, kinetic: str = "spectral") -> tuple[NDArray, ...]:
    """Physical-axis current components.

    Spectral j is sampled at grid nodes. FD2 j is on the positive half-grid
    face: Im(conj(psi_i)*psi_(i+1))/dx, compatible with discrete continuity.
    """
    if kinetic == "fd2":
        return tuple(np.imag(np.conj(psi) * np.roll(psi, -1, axis=-1 - i)) / dx
                     for i, dx in enumerate(grid.spacing))
    if kinetic != "spectral":
        raise ValueError("kinetic must be spectral or fd2")
    axes = tuple(2 * np.pi * fft.fftfreq(n, d=dx) for n, dx in zip(grid.points, grid.spacing, strict=True))
    wavevectors = (axes[0],) if grid.ndim == 1 else np.meshgrid(*axes, indexing="xy")
    spectrum = fft.fftn(psi)
    return tuple(np.imag(np.conj(psi) * fft.ifftn(1j * k * spectrum)) for k in wavevectors)


def state_errors(psi: NDArray, reference: NDArray, grid: Grid) -> dict[str, float | None]:
    if psi.shape != grid.array_shape or reference.shape != grid.array_shape:
        raise ValueError("compared states must match grid shape")
    inner = np.vdot(reference, psi) * grid.cell_volume
    p, q = norm(psi, grid), norm(reference, grid)
    raw = float(np.sqrt(np.sum(np.abs(psi - reference) ** 2) * grid.cell_volume))
    aligned = psi * np.exp(-1j * np.angle(inner)) if abs(inner) else psi
    phase_error = float(np.sqrt(np.sum(np.abs(aligned - reference) ** 2) * grid.cell_volume))
    fidelity = float(np.clip(abs(inner / math.sqrt(p) / math.sqrt(q)) ** 2, 0, 1)) if p > 0 and q > 0 else None
    return {"raw_l2": raw, "phase_aligned_l2": phase_error,
            "fidelity": fidelity, "relative_phase": float(np.angle(inner)) if abs(inner) else None}


def _validity(total: float, initial_norm: float) -> dict[str, str | float | None]:
    if not math.isfinite(total) or total < 0 or not math.isfinite(initial_norm) or initial_norm <= 0:
        raise ValueError("surviving norm must be finite/nonnegative and initial norm finite/positive")
    floor = 64 * np.finfo(float).eps * initial_norm
    if total == 0:
        status, reason = "numerically_zero", "No surviving probability is represented; conditional observables are undefined."
    elif total <= floor:
        status, reason = "below_reporting_floor", "Conditional observables are withheld below the declared reporting floor."
    else:
        status, reason = "resolved", None
    return {"conditional_status": status, "reporting_floor": float(floor),
            "initial_norm": initial_norm, "reason": reason}


def measurement_validity(psi: NDArray, grid: Grid, initial_norm: float = 1.0) -> dict[str, str | float | None]:
    """Reporting policy, not a statement that every small positive state is inaccurate."""
    total = norm(psi, grid)
    validity = _validity(total, initial_norm)
    if validity["conditional_status"] != "resolved":
        validity["uncertainty_status"] = "unavailable"
        return validity
    edge = np.zeros(grid.shape, dtype=bool)
    for axis in range(grid.ndim):
        first = [slice(None)]*grid.ndim
        first[axis] = slice(0, 2)
        edge[tuple(first)] = True
        first[axis] = slice(-2, None)
        edge[tuple(first)] = True
    edge_fraction = float(np.sum(np.abs(psi[edge])**2)*grid.cell_volume/total)
    axes, weights = momentum_distribution(psi, grid)
    waves = (axes[0],) if grid.ndim == 1 else np.meshgrid(*axes, indexing="xy")
    high = np.zeros(grid.shape, dtype=bool)
    for wave, spacing in zip(waves, grid.spacing, strict=True):
        high |= np.abs(wave) >= 0.8*np.pi/spacing
    high_fraction = float(np.sum(weights[high])/total)
    contaminated = edge_fraction > 1e-6 or high_fraction > 1e-6
    validity.update(uncertainty_status="boundary_or_nyquist_contaminated" if contaminated else "localized_line_approximation",
                    uncertainty_reason="Position-momentum uncertainty approximates the line only for localized, resolved states; a periodic sampled coordinate is not an exact canonical position operator.")
    return validity


def measure(psi: NDArray, grid: Grid, V: NDArray, kinetic: str = "spectral", W: NDArray | None = None,
            *, initial_norm: float = 1.0) -> dict[str, float | None]:
    probability = np.abs(psi) ** 2 * grid.cell_volume
    total = float(np.sum(probability))
    validity = _validity(total, initial_norm)
    result: dict[str, float | None] = {"norm": total}
    energy = float((np.vdot(psi, apply_hamiltonian(psi, grid, V, kinetic)) * grid.cell_volume).real)
    if not math.isfinite(energy):
        raise FloatingPointError("Hamiltonian expectation is not finite")
    result["energy_unconditional"] = energy
    k_axes, k_probability = momentum_distribution(psi, grid)
    wavevectors = (k_axes[0],) if grid.ndim == 1 else np.meshgrid(*k_axes, indexing="xy")
    labels = ("x", "y")[:grid.ndim]
    names = ["energy", "high_k_fraction"]
    for label in labels:
        names.extend([f"{label}_mean", f"{label}_variance", f"p{label}_mean", f"p{label}_variance",
                      f"{label}_p{label}_covariance", f"{label}_p{label}_uncertainty", f"{label}_p{label}_robertson"])
    if grid.ndim == 2:
        names.extend(["x_y_covariance", "px_py_covariance", "x_py_covariance", "y_px_covariance"])
    high_k = np.zeros(grid.array_shape, dtype=bool)
    for k, axis_spacing in zip(wavevectors, grid.spacing, strict=True):
        high_k |= np.abs(k) >= .8 * np.pi / axis_spacing
    high_probability = float(np.sum(k_probability[high_k]))
    result["high_k_probability"] = high_probability
    result["prob_left"] = float(np.sum(probability[grid.mesh[0] < 0]))
    result["prob_right"] = float(np.sum(probability[grid.mesh[0] >= 0]))
    edge = np.zeros(grid.array_shape, dtype=bool)
    for axis in range(grid.ndim):
        slices = [slice(None)] * grid.ndim
        slices[axis] = slice(0, 2)
        edge[tuple(slices)] = True
        slices[axis] = slice(-2, None)
        edge[tuple(slices)] = True
    result["edge_probability"] = float(np.sum(probability[edge]))
    if W is not None:
        result["cap_probability"] = float(np.sum(probability[W > 0]))
        result["loss_rate"] = float(2 * np.sum(W * probability))
    if validity["conditional_status"] != "resolved":
        result.update(dict.fromkeys(names))
        return result
    conditional: dict[str, float] = {"energy": energy / total, "high_k_fraction": high_probability / total}
    for label, coordinate, k in zip(labels, grid.mesh, wavevectors, strict=True):
        mean = float(np.sum(coordinate * probability) / total)
        variance = float(np.sum((coordinate - mean) ** 2 * probability) / total)
        pmean = float(np.sum(k * k_probability) / total)
        pvariance = float(np.sum((k - pmean) ** 2 * k_probability) / total)
        conditional.update({f"{label}_mean": mean, f"{label}_variance": variance,
                            f"p{label}_mean": pmean, f"p{label}_variance": pvariance})
    # Canonical momentum uses the same Fourier k labelling for both kinetic
    # models. FD2's face current is separately defined by discrete continuity.
    # Position/momentum uncertainty products approximate their line-domain
    # interpretation only for packets with negligible seam probability.
    spectrum = fft.fftn(psi)
    momentum_states = [fft.ifftn(k * spectrum) for k in wavevectors]
    for i, label in enumerate(labels):
        dposition = grid.mesh[i] - conditional[f"{label}_mean"]
        dmomentum_state = momentum_states[i] - conditional[f"p{label}_mean"] * psi
        covariance = float((np.vdot(dposition * psi, dmomentum_state) * grid.cell_volume).real / total)
        variance_product = conditional[f"{label}_variance"] * conditional[f"p{label}_variance"]
        conditional[f"{label}_p{label}_covariance"] = covariance
        conditional[f"{label}_p{label}_uncertainty"] = float(np.sqrt(max(variance_product, 0)))
        conditional[f"{label}_p{label}_robertson"] = variance_product - covariance ** 2
    if grid.ndim == 2:
        dx, dy = (grid.mesh[i] - conditional[f"{label}_mean"] for i, label in enumerate(labels))
        dpx, dpy = (wavevectors[i] - conditional[f"p{label}_mean"] for i, label in enumerate(labels))
        conditional["x_y_covariance"] = float(np.sum(dx * dy * probability) / total)
        conditional["px_py_covariance"] = float(np.sum(dpx * dpy * k_probability) / total)
        for i, j in ((0, 1), (1, 0)):
            value = np.vdot((grid.mesh[i] - conditional[f"{labels[i]}_mean"]) * psi,
                            momentum_states[j] - conditional[f"p{labels[j]}_mean"] * psi)
            conditional[f"{labels[i]}_p{labels[j]}_covariance"] = float(value.real * grid.cell_volume / total)
    if not all(math.isfinite(value) for value in conditional.values()):
        raise FloatingPointError("Conditional measurement is not representable")
    result.update(conditional)
    return result
