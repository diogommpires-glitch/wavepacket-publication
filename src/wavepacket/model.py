"""Grids and initial states with one explicit normalisation convention."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.sparse.linalg import LinearOperator, eigsh
from scipy.special import eval_hermite, factorial

from .config import GridSpec, SimulationConfig, StateSpec


@dataclass(frozen=True)
class Grid:
    axes: tuple[NDArray[np.float64], ...]
    spacing: tuple[float, ...]
    mesh: tuple[NDArray[np.float64], ...]
    bounds: tuple[tuple[float, float], ...]
    points: tuple[int, ...]

    @property
    def ndim(self) -> int:
        return len(self.axes)

    @property
    def array_shape(self) -> tuple[int, ...]:
        return tuple(reversed(self.points))

    @property
    def shape(self) -> tuple[int, ...]:
        return self.array_shape

    @property
    def cell_volume(self) -> float:
        return math.prod(self.spacing)

    @property
    def size(self) -> int:
        return math.prod(self.points)


def make_grid(spec: GridSpec) -> Grid:
    spacing = tuple((hi - lo) / n for (lo, hi), n in zip(spec.bounds, spec.points, strict=True))
    axes = tuple(lo + np.arange(n, dtype=np.float64) * dx
                 for (lo, _), n, dx in zip(spec.bounds, spec.points, spacing, strict=True))
    mesh = (axes[0],) if len(axes) == 1 else tuple(np.meshgrid(*axes, indexing="xy"))
    return Grid(axes, spacing, mesh, spec.bounds, spec.points)


def vector(value: Any, ndim: int, name: str) -> NDArray[np.float64]:
    array = np.atleast_1d(np.asarray(value, dtype=float))
    if array.size == 1:
        array = np.repeat(array, ndim)
    if array.shape != (ndim,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain {ndim} finite values or one broadcast value")
    return array


def normalise(psi: NDArray[np.complex128], grid: Grid) -> NDArray[np.complex128]:
    value = np.asarray(psi, dtype=np.complex128)
    if value.shape != grid.array_shape or not np.all(np.isfinite(value)):
        raise ValueError("wavefunction must be finite and match the grid array shape")
    scale = max(float(np.max(np.abs(value.real))), float(np.max(np.abs(value.imag))))
    if scale == 0:
        raise ValueError("wavefunction has zero probability")
    scaled = value.real / scale + 1j * (value.imag / scale)
    probability = float(np.vdot(scaled, scaled).real * grid.cell_volume)
    if not math.isfinite(probability) or probability <= 0:
        raise ValueError("wavefunction probability is not representable on this grid")
    result = scaled / math.sqrt(probability)
    if not np.all(np.isfinite(result)):
        raise ValueError("normalised wavefunction is not representable on this grid")
    return np.asarray(result, dtype=np.complex128)


def _amplitude(value: Any) -> complex:
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError("complex coefficients require [real, imaginary]")
        result = complex(*value)
    else:
        result = complex(value)
    if not (math.isfinite(result.real) and math.isfinite(result.imag)):
        raise ValueError("state coefficient must be finite")
    return result


def _relative_coefficients(values: list[Any]) -> list[complex]:
    coefficients = [_amplitude(value) for value in values]
    scale = max(max(abs(value.real), abs(value.imag)) for value in coefficients)
    if scale == 0:
        raise ValueError("state coefficients define a zero state")
    return [complex(value.real / scale, value.imag / scale) for value in coefficients]


def _state(spec: StateSpec, grid: Grid, config: SimulationConfig, depth: int = 0) -> NDArray[np.complex128]:
    if depth > 3:
        raise ValueError("state sums may be nested at most three levels")
    center = vector(spec.center, grid.ndim, "center")
    momentum = vector(spec.momentum, grid.ndim, "momentum")
    sigma = vector(spec.sigma, grid.ndim, "sigma")
    if np.any(sigma <= 0):
        raise ValueError("sigma must be positive")
    displacement = [axis - c for axis, c in zip(grid.mesh, center, strict=True)]
    carrier = np.exp(1j * (sum(k * d for k, d in zip(momentum, displacement, strict=True)) + spec.phase))
    if spec.kind == "gaussian":
        chirp = vector(spec.params.get("chirp", 0.0), grid.ndim, "chirp")
        exponent = sum(-d * d / (4 * s * s) + 0.5j * c * d * d
                       for d, s, c in zip(displacement, sigma, chirp, strict=True))
        return carrier * np.exp(exponent) * np.prod((2 * np.pi * sigma * sigma) ** -0.25)
    if spec.kind in ("ho_coherent", "ho_squeezed"):
        omega = vector(spec.params.get("omega", 1.0), grid.ndim, "omega")
        if np.any(omega <= 0):
            raise ValueError("oscillator frequencies must be positive")
        angle = float(spec.params.get("angle", 0.0))
        coordinates = displacement
        if grid.ndim == 2:
            c, s = math.cos(angle), math.sin(angle)
            coordinates = [c * displacement[0] + s * displacement[1],
                           -s * displacement[0] + c * displacement[1]]
        squeeze = vector(spec.params.get("squeeze", 0.0), grid.ndim, "squeeze")
        quantum_numbers = vector(spec.params.get("quantum_numbers", 0), grid.ndim, "quantum_numbers")
        if np.any(quantum_numbers < 0) or np.any(quantum_numbers != np.floor(quantum_numbers)) or np.any(quantum_numbers > 20):
            raise ValueError("quantum_numbers must be integers from zero to twenty")
        envelope = np.ones(grid.array_shape, dtype=float)
        for q, w, r, number in zip(coordinates, omega, squeeze, quantum_numbers, strict=True):
            # ell is oscillator length, so density SD at n=0 is ell/sqrt(2).
            ell = math.exp(r) / math.sqrt(w)
            n = int(number)
            envelope *= ((1 / (np.pi * ell * ell)) ** 0.25
                         * eval_hermite(n, q / ell) * np.exp(-q * q / (2 * ell * ell))
                         / math.sqrt(2 ** n * factorial(n)))
        return carrier * envelope
    if spec.kind == "sum":
        components = spec.params.get("components", [])
        if not 1 <= len(components) <= 8:
            raise ValueError("sum states need between one and eight components")
        result = np.zeros(grid.array_shape, dtype=np.complex128)
        coefficients = _relative_coefficients([component.get("amplitude", 1) for component in components])
        for component, coefficient in zip(components, coefficients, strict=True):
            data = component.get("state", {k: v for k, v in component.items() if k != "amplitude"})
            component_spec = StateSpec.model_validate(data)
            # Component normalisation makes amplitudes meaningful on finite grids.
            result += coefficient * normalise(_state(component_spec, grid, config, depth + 1), grid)
        return result * np.exp(1j * spec.phase)
    if spec.kind == "eigen_superposition":
        indices = spec.params.get("indices", [0, 1])
        if not indices or any(not isinstance(i, int) or i < 0 or i > 15 for i in indices):
            raise ValueError("eigenstate indices must be integers from zero to fifteen")
        coefficients = spec.params.get("coefficients", [1.0] * len(indices))
        if len(coefficients) != len(indices):
            raise ValueError("eigenstate coefficients and indices must match")
        _, basis = eigenbasis(config, grid, max(indices) + 1)
        relative = _relative_coefficients(coefficients)
        return sum(c * basis[i] for i, c in zip(indices, relative, strict=True)) * np.exp(1j * spec.phase)
    if spec.kind == "waveguide_mode":
        if grid.ndim != 2:
            raise ValueError("waveguide mode needs a two-dimensional grid")
        from .operators import well_wall
        params = config.potential.params
        y = grid.axes[1]
        gy = make_grid(GridSpec(bounds=(grid.bounds[1],), points=(grid.points[1],)))
        wall = well_wall(y - float(params.get("center_y", 0.0)), float(params.get("width", 4.0)),
                         float(params.get("height", 20.0)), float(params.get("smoothing", 0.2)))
        mode = int(spec.params.get("mode", 0))
        if not 0 <= mode <= 8:
            raise ValueError("waveguide mode must be between zero and eight")
        values, functions = _eigenpairs(gy, wall, config.solver.kinetic, mode + 1)
        if values[mode] >= float(params.get("height", 20.0)):
            raise ValueError("chosen waveguide mode is not confined below the finite wall")
        longitudinal = np.exp(-displacement[0] ** 2 / (4 * sigma[0] ** 2))
        return functions[mode][:, None] * longitudinal * carrier
    raise ValueError(f"unsupported state: {spec.kind}")


def initial_state(config: SimulationConfig, grid: Grid) -> NDArray[np.complex128]:
    return normalise(_state(config.state, grid, config), grid)


def _eigenpairs(grid: Grid, values: NDArray[np.float64], kinetic: str, count: int) -> tuple[NDArray[np.float64], NDArray[np.complex128]]:
    from .operators import apply_hamiltonian
    if grid.ndim != 1 or grid.size > 4096 or count >= grid.size - 1:
        raise ValueError("initial eigenproblems require 1D grids up to 4096 points and fewer modes than grid points")
    def action(value: NDArray) -> NDArray:
        return apply_hamiltonian(value.reshape(grid.array_shape), grid, values, kinetic).ravel()
    operator = LinearOperator((grid.size, grid.size), matvec=action, rmatvec=action, dtype=np.complex128)
    # Deterministic non-parity-restricted seed avoids missing odd modes.
    rng = np.random.default_rng(1729)
    eigenvalues, eigenvectors = eigsh(operator, k=count, which="SA", tol=1e-11,
                                    maxiter=max(1000, 30 * grid.size), v0=rng.normal(size=grid.size))
    order = np.argsort(eigenvalues)
    basis = eigenvectors[:, order].T.astype(np.complex128)
    for i, eigenvector in enumerate(basis):
        anchor = np.argmax(np.abs(eigenvector))
        basis[i] = normalise(eigenvector * np.exp(-1j * np.angle(eigenvector[anchor])), grid)
    return eigenvalues[order], basis


def eigenbasis(config: SimulationConfig, grid: Grid, count: int = 2) -> tuple[NDArray[np.float64], NDArray[np.complex128]]:
    from .operators import potential
    return _eigenpairs(grid, potential(config, grid), config.solver.kinetic, count)
