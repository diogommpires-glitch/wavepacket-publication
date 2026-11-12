"""Validated, JSON-serialisable inputs for reproducible simulations.

Coordinates in a config are always in physical axis order (x, y).  Numerical
arrays use image order (ny, nx); the Grid object performs that translation.
All numerical inputs are dimensionless.  UnitSpec supplies display conversions.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _number(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    try:
        finite = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be a finite JSON number")
    if (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def _vector_param(value: Any, name: str, ndim: int, *, positive: bool = False, integer: bool = False) -> None:
    values = value if isinstance(value, (tuple, list)) else [value]
    if len(values) not in (1, ndim):
        raise ValueError(f"{name} needs one or {ndim} values")
    for item in values:
        _number(item, name, positive=positive)
        if integer and (not isinstance(item, int) or not 0 <= item <= 20):
            raise ValueError(f"{name} needs integer values from zero to twenty")


def _coefficient(value: Any, name: str) -> None:
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"{name} complex coefficient needs [real, imaginary]")
        for component in value:
            _number(component, name)
    else:
        _number(value, name)


def _validate_state(spec: StateSpec, ndim: int, potential_kind: str, depth: int = 0) -> None:
    if depth > 3:
        raise ValueError("state sums may be nested at most three levels")
    for name in ("center", "momentum", "sigma"):
        _vector_param(getattr(spec, name), f"state.{name}", ndim, positive=name == "sigma")
    allowed = {"gaussian": {"chirp"},
               "ho_coherent": {"omega", "angle", "quantum_numbers", "squeeze"},
               "ho_squeezed": {"omega", "angle", "quantum_numbers", "squeeze"},
               "sum": {"components"}, "eigen_superposition": {"indices", "coefficients"},
               "waveguide_mode": {"mode"}}[spec.kind]
    unknown = spec.params.keys() - allowed
    if unknown:
        raise ValueError(f"unknown {spec.kind} state parameter(s): {', '.join(sorted(unknown))}")
    p = spec.params
    for name in ("chirp", "omega", "squeeze", "quantum_numbers"):
        if name in p:
            _vector_param(p[name], f"state.params.{name}", ndim, positive=name == "omega", integer=name == "quantum_numbers")
    if "squeeze" in p:
        values = p["squeeze"] if isinstance(p["squeeze"], (list, tuple)) else [p["squeeze"]]
        if any(abs(value) > 20 for value in values):
            raise ValueError("squeeze magnitude must not exceed twenty")
    if "angle" in p:
        _number(p["angle"], "state.params.angle")
    if spec.kind == "sum":
        components = p.get("components", [])
        if not isinstance(components, (list, tuple)) or not 1 <= len(components) <= 8:
            raise ValueError("sum states need one to eight components")
        for component in components:
            if not isinstance(component, dict) or "state" not in component or component.keys() - {"state", "amplitude"}:
                raise ValueError("sum components need a state object and optional amplitude")
            _coefficient(component.get("amplitude", 1), "component.amplitude")
            _validate_state(StateSpec.model_validate(component["state"]), ndim, potential_kind, depth + 1)
    if spec.kind == "eigen_superposition":
        if ndim != 1:
            raise ValueError("eigenstate initialisation requires one dimension")
        indices = p.get("indices", [0, 1])
        if not isinstance(indices, (list, tuple)) or not indices or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i <= 15 for i in indices):
            raise ValueError("eigenstate indices must be integers from zero to fifteen")
        coefficients = p.get("coefficients", [1] * len(indices))
        if not isinstance(coefficients, (list, tuple)) or len(coefficients) != len(indices):
            raise ValueError("eigenstate indices and coefficients must match")
        for value in coefficients:
            _coefficient(value, "eigenstate coefficient")
    if spec.kind == "waveguide_mode":
        mode = p.get("mode", 0)
        if ndim != 2 or isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 8:
            raise ValueError("waveguide mode requires 2D and an integer mode from zero to eight")
        if potential_kind != "waveguide":
            raise ValueError("waveguide_mode requires a two-dimensional waveguide potential")


def _validate_potential(spec: PotentialSpec, ndim: int) -> None:
    allowed = {"free": set(), "harmonic": {"omega", "angle", "center"},
               "rectangle": {"height", "width", "center", "smoothing"},
               "gaussian": {"height", "sigma", "center"},
               "double_barrier": {"height", "width", "separation", "center"},
               "double_well": {"height", "separation", "tilt", "center"},
               "slit": {"height", "xcenter", "thickness", "slit_width", "slit_separation", "count", "center_y", "smoothing"},
               "disk": {"height", "radius", "center", "smoothing"},
               "waveguide": {"height", "width", "bend_x", "angle", "center_y", "smoothing"}}[spec.kind]
    unknown = spec.params.keys() - allowed
    if unknown:
        raise ValueError(f"unknown {spec.kind} potential parameter(s): {', '.join(sorted(unknown))}")
    if spec.kind in ("slit", "disk", "waveguide") and ndim != 2:
        raise ValueError(f"{spec.kind} potential requires two dimensions")
    p = spec.params
    vector_names = {"omega", "sigma"}
    if spec.kind in ("harmonic", "rectangle", "gaussian", "disk"):
        vector_names.add("center")
    if spec.kind == "rectangle":
        vector_names.add("width")
    positive_names = {"omega", "sigma", "width", "thickness", "radius", "separation", "slit_width", "slit_separation"}
    for name, value in p.items():
        if name in vector_names:
            _vector_param(value, f"potential.params.{name}", ndim, positive=name in positive_names)
        elif name == "count":
            if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2):
                raise ValueError("slit count must be integer one or two")
        else:
            _number(value, f"potential.params.{name}", positive=name in positive_names,
                    nonnegative=name == "smoothing")
    if spec.kind == "double_barrier" and p.get("separation", 4) <= p.get("width", 1):
        raise ValueError("double-barrier separation must exceed barrier width")
    if spec.kind == "double_well" and p.get("height", 1) <= 0:
        raise ValueError("double-well height must be positive")
    if spec.kind == "slit" and p.get("count", 2) == 2 and p.get("slit_separation", 4) <= p.get("slit_width", 1.5):
        raise ValueError("double-slit separation must exceed aperture width")
    if spec.kind in ("slit", "disk", "waveguide") and p.get("height", 20) <= 0:
        raise ValueError("finite wall/obstacle height must be positive")
    if spec.kind == "waveguide" and abs(p.get("angle", math.pi / 6)) >= math.pi / 3:
        raise ValueError("waveguide angle must have magnitude below pi/3")


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GridSpec(Spec):
    bounds: tuple[tuple[float, float], ...] = ((-40.0, 40.0),)
    points: tuple[int, ...] = (512,)

    @model_validator(mode="after")
    def valid_grid(self) -> GridSpec:
        if len(self.bounds) not in (1, 2) or len(self.points) != len(self.bounds):
            raise ValueError("grid must have matching one- or two-dimensional bounds and points")
        if any(hi <= lo for lo, hi in self.bounds):
            raise ValueError("every upper grid bound must exceed its lower bound")
        if any(not math.isfinite(hi - lo) for lo, hi in self.bounds):
            raise ValueError("grid extent must be finite")
        if any(n < 16 for n in self.points):
            raise ValueError("every grid axis needs at least 16 points")
        return self


class StateSpec(Spec):
    kind: Literal["gaussian", "sum", "ho_coherent", "ho_squeezed", "eigen_superposition", "waveguide_mode"] = "gaussian"
    center: tuple[float, ...] = (-10.0,)
    momentum: tuple[float, ...] = (2.0,)
    sigma: tuple[float, ...] = (2.0,)
    phase: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("center", "momentum", "sigma")
    @classmethod
    def nonempty_finite_vectors(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value or len(value) > 2:
            raise ValueError("state vectors must contain one or two values")
        return value

    @field_validator("sigma")
    @classmethod
    def positive_sigma(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(s <= 0 for s in value):
            raise ValueError("sigma is the density standard deviation and must be positive")
        return value


class PotentialSpec(Spec):
    kind: Literal["free", "harmonic", "rectangle", "gaussian", "double_barrier", "double_well", "slit", "disk", "waveguide"] = "free"
    params: dict[str, Any] = Field(default_factory=dict)


class SolverSpec(Spec):
    method: Literal["strang", "cn", "yoshida4"] = "strang"
    kinetic: Literal["spectral", "fd2"] = "spectral"
    dt: float = Field(default=0.02, gt=0)
    duration: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def representable_step_count(self) -> SolverSpec:
        if not math.isfinite(self.duration / self.dt):
            raise ValueError("duration/dt must be a finite step count")
        return self


class BoundarySpec(Spec):
    kind: Literal["periodic", "cap"] = "periodic"
    width: float = Field(default=8.0, gt=0)
    strength: float = Field(default=1.0, gt=0)
    power: int = Field(default=4, ge=2, le=12)


class SamplingSpec(Spec):
    observable_every: int = Field(default=10, ge=1)
    snapshots: int = Field(default=81, ge=2)
    screen_x: float | None = None


class BudgetSpec(Spec):
    max_steps: int = Field(default=200_000, ge=1)
    max_points: int = Field(default=262_144, ge=16)
    max_snapshots: int = Field(default=128, ge=2)
    max_output_bytes: int = Field(default=1_073_741_824, ge=1024)
    max_working_bytes: int = Field(default=536_870_912, ge=1_048_576)


class UnitSpec(Spec):
    mode: Literal["dimensionless", "electron"] = "dimensionless"
    length_nm: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def representable_scales(self) -> UnitSpec:
        from .units import electron_scales
        electron_scales(self.length_nm)
        return self


class SimulationConfig(Spec):
    name: str = Field(default="free-gaussian", min_length=1, max_length=100)
    schema_version: Literal[1] = 1
    grid: GridSpec = Field(default_factory=GridSpec)
    state: StateSpec = Field(default_factory=StateSpec)
    potential: PotentialSpec = Field(default_factory=PotentialSpec)
    solver: SolverSpec = Field(default_factory=SolverSpec)
    boundary: BoundarySpec = Field(default_factory=BoundarySpec)
    sampling: SamplingSpec = Field(default_factory=SamplingSpec)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    units: UnitSpec = Field(default_factory=UnitSpec)

    @property
    def n_steps(self) -> int:
        # Small tolerance avoids an extra near-zero step for floating quotients.
        return max(1, math.ceil(self.solver.duration / self.solver.dt - 1e-12))

    @model_validator(mode="after")
    def compatible_and_bounded(self) -> SimulationConfig:
        def finite_params(value: Any) -> None:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("state and potential parameters must be finite")
            if isinstance(value, dict):
                for item in value.values():
                    finite_params(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    finite_params(item)
        finite_params(self.state.params)
        finite_params(self.potential.params)
        ndim = len(self.grid.points)
        _validate_state(self.state, ndim, self.potential.kind)
        _validate_potential(self.potential, ndim)
        for vector in (self.state.center, self.state.momentum, self.state.sigma):
            if len(vector) not in (1, ndim):
                raise ValueError("state vector dimensions must match grid dimensions or broadcast one value")
        if self.solver.method == "cn" and (ndim != 1 or self.solver.kinetic != "fd2"):
            raise ValueError("Crank-Nicolson requires a one-dimensional fd2 Hamiltonian")
        if self.boundary.kind == "cap":
            if self.solver.method != "strang":
                raise ValueError("CAP is supported only by positive-step Strang splitting")
            if any(2 * self.boundary.width >= hi - lo for lo, hi in self.grid.bounds):
                raise ValueError("CAP layers must leave a nonempty interior on every axis")
        if self.state.kind == "eigen_superposition" and ndim != 1:
            raise ValueError("eigenstate initialisation is supported only in one dimension")
        if self.n_steps > self.budget.max_steps:
            raise ValueError(f"requested {self.n_steps} steps exceeds max_steps")
        count = math.prod(self.grid.points)
        if count > self.budget.max_points:
            raise ValueError(f"requested {count} grid points exceeds max_points")
        if self.sampling.snapshots > self.budget.max_snapshots:
            raise ValueError("requested snapshots exceeds max_snapshots")
        if self.sampling.screen_x is not None:
            if ndim != 2:
                raise ValueError("screen_x requires a two-dimensional simulation")
            lo, hi = self.grid.bounds[0]
            if not lo < self.sampling.screen_x < hi:
                raise ValueError("screen_x must lie strictly inside the x bounds")
        # Uncompressed complex128 checkpoints dominate the output budget.
        frames = min(self.sampling.snapshots, self.n_steps + 1)
        if frames * count * 16 > self.budget.max_output_bytes:
            raise ValueError("requested complex snapshots exceed max_output_bytes")
        return self


def config_fingerprint(config: SimulationConfig) -> str:
    """Hash the full resolved config; even name, budget or unit edits change identity."""
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
