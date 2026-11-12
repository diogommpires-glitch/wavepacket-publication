"""Static potential catalogue and explicit spectral/finite-difference operators."""
from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy import fft
from scipy.sparse import csr_matrix, diags

from .config import SimulationConfig
from .model import Grid, vector


def kinetic_symbol(grid: Grid, kinetic: str = "spectral") -> NDArray[np.float64]:
    if kinetic not in ("spectral", "fd2"):
        raise ValueError("kinetic must be spectral or fd2")
    frequencies = tuple(2 * np.pi * fft.fftfreq(n, d=dx) for n, dx in zip(grid.points, grid.spacing, strict=True))
    wavevectors = (frequencies[0],) if grid.ndim == 1 else np.meshgrid(*frequencies, indexing="xy")
    if kinetic == "spectral":
        return np.asarray(sum(k * k / 2 for k in wavevectors), dtype=float)
    return np.asarray(sum(2 * np.sin(k * dx / 2) ** 2 / dx ** 2
                          for k, dx in zip(wavevectors, grid.spacing, strict=True)), dtype=float)


def apply_hamiltonian(psi: NDArray, grid: Grid, V: NDArray, kinetic: str = "spectral", W: NDArray | None = None) -> NDArray[np.complex128]:
    if psi.shape != grid.array_shape or V.shape != grid.array_shape:
        raise ValueError("Hamiltonian arrays must match grid shape")
    result = fft.ifftn(kinetic_symbol(grid, kinetic) * fft.fftn(psi)) + V * psi
    return result if W is None else result - 1j * W * psi


def hamiltonian_matrix(grid: Grid, V: NDArray, kinetic: str = "fd2", W: NDArray | None = None) -> csr_matrix:
    """Sparse periodic FD2 H, or a bounded dense spectral reference, in 1D."""
    if grid.ndim != 1:
        raise ValueError("explicit Hamiltonian requires a one-dimensional grid")
    if V.shape != grid.array_shape or (W is not None and W.shape != grid.array_shape):
        raise ValueError("Hamiltonian potential and absorber must match the grid")
    n, dx = grid.points[0], grid.spacing[0]
    if kinetic == "fd2":
        matrix = diags((-np.ones(n - 1) / (2 * dx * dx), np.ones(n) / (dx * dx),
                        -np.ones(n - 1) / (2 * dx * dx)), (-1, 0, 1), dtype=complex).tolil()
        matrix[0, -1] = matrix[-1, 0] = -1 / (2 * dx * dx)
        matrix = matrix.tocsr()
    elif kinetic == "spectral":
        if n > 1024:
            raise ValueError("dense spectral Hamiltonian is restricted to 1024 points")
        transform = fft.fft(np.eye(n), axis=0, norm="ortho")
        matrix = csr_matrix(transform.conj().T @ (kinetic_symbol(grid, kinetic)[:, None] * transform))
    else:
        raise ValueError("kinetic must be spectral or fd2")
    diagonal = np.asarray(V, dtype=complex) - (0 if W is None else 1j * W)
    return matrix + diags(diagonal, format="csr")


def _window(value: NDArray, half_width: float, smoothing: float = 0.0) -> NDArray:
    if half_width <= 0 or smoothing < 0:
        raise ValueError("potential widths must be positive and smoothing nonnegative")
    if smoothing == 0:
        return (np.abs(value) < half_width).astype(float)
    return 0.5 * (np.tanh((value + half_width) / smoothing) - np.tanh((value - half_width) / smoothing))


def well_wall(value: NDArray, width: float, height: float, smoothing: float) -> NDArray:
    if height <= 0:
        raise ValueError("confining wall height must be positive")
    return height * (1 - _window(value, width / 2, smoothing))


def potential(config: SimulationConfig, grid: Grid) -> NDArray[np.float64]:
    kind, p = config.potential.kind, config.potential.params
    if kind == "free":
        return np.zeros(grid.array_shape)
    x = grid.mesh[0]
    if kind == "harmonic":
        omega = vector(p.get("omega", 1.0), grid.ndim, "omega")
        if np.any(omega <= 0):
            raise ValueError("omega must be positive")
        center = vector(p.get("center", 0.0), grid.ndim, "center")
        q = [coord - c for coord, c in zip(grid.mesh, center, strict=True)]
        if grid.ndim == 2:
            a = float(p.get("angle", 0.0))
            c, s = math.cos(a), math.sin(a)
            q = [c * q[0] + s * q[1], -s * q[0] + c * q[1]]
        result = sum(0.5 * w * w * value * value for w, value in zip(omega, q, strict=True))
    elif kind == "rectangle":
        center = vector(p.get("center", 0.0), grid.ndim, "center")
        widths = vector(p.get("width", 2.0), grid.ndim, "width")
        result = np.ones(grid.array_shape) * float(p.get("height", 2.5))
        for axis, c, width in zip(grid.mesh, center, widths, strict=True):
            result *= _window(axis - c, width / 2, float(p.get("smoothing", 0.0)))
    elif kind == "gaussian":
        center = vector(p.get("center", 0.0), grid.ndim, "center")
        sigma = vector(p.get("sigma", 1.0), grid.ndim, "sigma")
        if np.any(sigma <= 0):
            raise ValueError("potential sigma must be positive")
        result = float(p.get("height", 2.5)) * np.exp(sum(-0.5 * ((axis - c) / s) ** 2
                    for axis, c, s in zip(grid.mesh, center, sigma, strict=True)))
    elif kind == "double_barrier":
        center_x, separation = float(p.get("center", 0.0)), float(p.get("separation", 4.0))
        width, height = float(p.get("width", 1.0)), float(p.get("height", 2.5))
        if separation <= width:
            raise ValueError("double-barrier separation must exceed each barrier width")
        result = height * (_window(x - center_x - separation / 2, width / 2)
                           + _window(x - center_x + separation / 2, width / 2))
    elif kind == "double_well":
        separation = float(p.get("separation", 4.0))
        if separation <= 0:
            raise ValueError("well separation must be positive")
        d = x - float(p.get("center", 0.0))
        result = float(p.get("height", 1.0)) * ((2 * d / separation) ** 2 - 1) ** 2 + float(p.get("tilt", 0.0)) * d
    elif kind == "slit":
        if grid.ndim != 2:
            raise ValueError("slit potential requires a two-dimensional grid")
        y = grid.mesh[1] - float(p.get("center_y", 0.0))
        count = int(p.get("count", 2))
        if count not in (1, 2):
            raise ValueError("slit count must be one or two")
        smoothing = float(p.get("smoothing", 0.0))
        opening = np.zeros(grid.array_shape)
        separation = float(p.get("slit_separation", 4.0))
        width = float(p.get("slit_width", 1.5))
        if count == 2 and separation <= width:
            raise ValueError("two slit openings must be separated")
        for slit_center in ([0.0] if count == 1 else [-separation / 2, separation / 2]):
            opening += _window(y - slit_center, width / 2, smoothing)
        result = float(p.get("height", 20.0)) * _window(x - float(p.get("xcenter", 0.0)),
                    float(p.get("thickness", 1.0)) / 2, smoothing) * (1 - np.clip(opening, 0, 1))
    elif kind == "disk":
        if grid.ndim != 2:
            raise ValueError("disk potential requires a two-dimensional grid")
        center = vector(p.get("center", (0.0, 0.0)), 2, "center")
        radius = float(p.get("radius", 2.0))
        smoothing = float(p.get("smoothing", 0.3))
        distance = np.sqrt(sum((coord - c) ** 2 for coord, c in zip(grid.mesh, center, strict=True)))
        if radius <= 0 or smoothing < 0:
            raise ValueError("disk radius must be positive and smoothing nonnegative")
        result = float(p.get("height", 20.0)) * ((distance < radius).astype(float) if smoothing == 0
                    else 0.5 * (1 - np.tanh((distance - radius) / smoothing)))
    elif kind == "waveguide":
        if grid.ndim != 2:
            raise ValueError("waveguide potential requires a two-dimensional grid")
        y = grid.mesh[1] - float(p.get("center_y", 0.0))
        bend = float(p.get("bend_x", 0.0))
        angle = float(p.get("angle", np.pi / 6))
        if abs(angle) >= np.pi / 3:
            raise ValueError("waveguide bend angle must be less than pi/3 in magnitude")
        # Signed distance to the two straight channel segments; finite wall
        # transmission is physical and must be included in probability budgets.
        distance = np.where(x < bend, y, np.cos(angle) * y - np.sin(angle) * (x - bend))
        result = well_wall(distance, float(p.get("width", 4.0)), float(p.get("height", 20.0)), float(p.get("smoothing", 0.2)))
    else:
        raise ValueError(f"unsupported potential: {kind}")
    array = np.asarray(result, dtype=float)
    if array.shape != grid.array_shape or not np.all(np.isfinite(array)):
        raise ValueError("potential must be finite and match grid shape")
    return array


def absorber(config: SimulationConfig, grid: Grid) -> NDArray[np.float64]:
    if config.boundary.kind == "periodic":
        return np.zeros(grid.array_shape)
    boundary = config.boundary
    result = np.zeros(grid.array_shape)
    for coordinate, (lo, hi) in zip(grid.mesh, grid.bounds, strict=True):
        distance = np.minimum(coordinate - lo, hi - coordinate)
        ramp = np.clip((boundary.width - distance) / boundary.width, 0, 1)
        result += boundary.strength * ramp ** boundary.power
    return result
