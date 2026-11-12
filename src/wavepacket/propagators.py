"""Reusable static-H propagators, with CAP loss tracked before each damping.

Yoshida's negative substep is safe for closed unitary groups; it is deliberately
rejected for absorbers, where it would amplify rather than damp the state.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy import fft
from scipy.sparse import eye
from scipy.sparse.linalg import splu

from .config import SimulationConfig
from .model import Grid
from .operators import hamiltonian_matrix, kinetic_symbol


class Stepper:
    """Callable propagator. Input arrays are never mutated.

    ``last_loss`` and ``total_absorbed`` measure only explicit CAP damping,
    independently of FFT roundoff. ``absorbed_density`` can be integrated over
    spatial masks for regional loss accounting. Reversal is allowed for W=0.
    """
    def __init__(self, config: SimulationConfig, grid: Grid, V: NDArray, W: NDArray | None = None):
        self.grid = grid
        self.dt = config.solver.dt
        self.method = config.solver.method
        self.kinetic = config.solver.kinetic
        self.V = np.asarray(V, dtype=float).copy()
        self.W = np.zeros(grid.array_shape) if W is None else np.asarray(W, dtype=float).copy()
        if self.V.shape != grid.array_shape or self.W.shape != grid.array_shape:
            raise ValueError("potential and absorber must match grid shape")
        if not np.all(np.isfinite(self.V)) or not np.all(np.isfinite(self.W)) or np.any(self.W < 0):
            raise ValueError("potentials must be finite and absorber nonnegative")
        self.has_cap = bool(np.any(self.W > 0))
        if self.method != "strang" and self.has_cap:
            raise ValueError("CAP is supported only by Strang splitting")
        self.T = kinetic_symbol(grid, self.kinetic)
        self.last_loss = 0.0
        self.total_absorbed = 0.0
        self.absorbed_density = np.zeros(grid.array_shape)
        self.last_absorbed_density = np.zeros(grid.array_shape)
        self._phases: dict[float, tuple[NDArray, NDArray]] = {}
        self._cn: dict[float, tuple[Callable, object]] = {}
        self._H = None
        if self.method == "cn":
            if grid.ndim != 1 or self.kinetic != "fd2":
                raise ValueError("Crank-Nicolson requires a 1D fd2 Hamiltonian")
            self._H = hamiltonian_matrix(grid, self.V, "fd2")

    def _phase(self, h: float) -> tuple[NDArray, NDArray]:
        if h not in self._phases:
            if len(self._phases) >= 8:
                self._phases.clear()
            self._phases[h] = (np.exp((-1j * self.V - self.W) * (h / 2)), np.exp(-1j * self.T * h))
        return self._phases[h]

    def _strang(self, psi: NDArray, h: float) -> NDArray[np.complex128]:
        half, kinetic = self._phase(h)
        if self.has_cap:
            # Stable when W*h is tiny: 1-exp(-W*h) would lose significant digits.
            fraction = -np.expm1(-self.W * h)
            self.last_absorbed_density += np.abs(psi) ** 2 * fraction
        result = fft.ifftn(kinetic * fft.fftn(half * psi))
        if self.has_cap:
            self.last_absorbed_density += np.abs(result) ** 2 * (-np.expm1(-self.W * h))
        return half * result

    def __call__(self, psi: NDArray, dt: float | None = None) -> NDArray[np.complex128]:
        h = self.dt if dt is None else float(dt)
        if not math.isfinite(h):
            raise ValueError("step size must be finite")
        if self.has_cap and h < 0:
            raise ValueError("negative timesteps are forbidden with a CAP")
        state = np.asarray(psi, dtype=np.complex128)
        if state.shape != self.grid.array_shape:
            raise ValueError("state shape does not match grid")
        self.last_absorbed_density.fill(0)
        if h == 0:
            result = state.copy()
        elif self.method == "strang":
            result = self._strang(state, h)
        elif self.method == "yoshida4":
            w1 = 1 / (2 - 2 ** (1 / 3))
            w0 = -2 ** (1 / 3) / (2 - 2 ** (1 / 3))
            result = self._strang(self._strang(self._strang(state, w1 * h), w0 * h), w1 * h)
        elif self.method == "cn":
            assert self._H is not None
            if h not in self._cn:
                if len(self._cn) >= 8:
                    self._cn.clear()
                identity = eye(self.grid.size, dtype=complex, format="csc")
                left = identity + 0.5j * h * self._H
                right = identity - 0.5j * h * self._H
                self._cn[h] = (splu(left.tocsc()).solve, right)
            solve, right = self._cn[h]
            result = solve(right @ state.ravel()).reshape(self.grid.array_shape)
        else:
            raise ValueError(f"unknown propagator: {self.method}")
        self.last_loss = float(self.last_absorbed_density.sum() * self.grid.cell_volume)
        self.total_absorbed += self.last_loss
        self.absorbed_density += self.last_absorbed_density
        return np.asarray(result, dtype=np.complex128)


def make_stepper(config: SimulationConfig, grid: Grid, V: NDArray, W: NDArray | None = None) -> Stepper:
    return Stepper(config, grid, V, W)
