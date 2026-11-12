"""Electron display units; the numerical engine always uses hbar = mass = 1.

For length scale L0, E0 = hbar**2/(m_e L0**2), t0 = hbar/E0,
and p0 = hbar/L0.  E0 has no factor of two: that factor belongs to
the dimensionless Hamiltonian's kinetic term -1/2 Laplacian.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from scipy.constants import electron_mass, elementary_charge, hbar

if TYPE_CHECKING:
    from .config import UnitSpec


@dataclass(frozen=True)
class UnitScales:
    length_nm: float
    time_fs: float
    energy_ev: float
    momentum_si: float
    momentum_inverse_nm: float
    density_per_nm: float
    density_per_nm2: float
    current_per_fs: float
    current_per_nm_fs: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def electron_scales(length_nm: float = 1.0) -> UnitScales:
    if not math.isfinite(length_nm) or length_nm <= 0:
        raise ValueError("length_nm must be positive and finite")
    try:
        length_m = length_nm * 1e-9
        momentum = hbar / length_m
        energy_j = momentum * momentum / electron_mass
        time_fs = hbar / energy_j * 1e15
        inverse_length = 1 / length_nm
        inverse_time = 1 / time_fs
        scales = UnitScales(length_nm, time_fs, energy_j / elementary_charge, momentum,
                            inverse_length, inverse_length, inverse_length * inverse_length,
                            inverse_time, inverse_time * inverse_length)
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError(f"electron unit scales must be representable, got length_nm={length_nm}") from error
    if not all(math.isfinite(value) and value > 0 for value in scales.as_dict().values()):
        raise ValueError(f"electron unit scales must be representable, got length_nm={length_nm}")
    return scales


def to_physical(value: Any, quantity: str, length_nm: float = 1.0) -> Any:
    scales = electron_scales(length_nm)
    factors = {"length": scales.length_nm, "time": scales.time_fs,
               "energy": scales.energy_ev, "momentum": scales.momentum_si}
    if quantity not in factors:
        raise ValueError(f"unknown unit quantity: {quantity}")
    return value * factors[quantity]


def to_dimensionless(value: Any, quantity: str, length_nm: float = 1.0) -> Any:
    return value / to_physical(1.0, quantity, length_nm)


def unit_metadata(spec: UnitSpec) -> dict[str, Any]:
    return {"mode": spec.mode, "numerical_units": "hbar = m = 1",
            "length_label": "nm" if spec.mode == "electron" else "x / L0",
            "time_label": "fs" if spec.mode == "electron" else "t / t0",
            "energy_label": "eV" if spec.mode == "electron" else "E / E0",
            "scales": electron_scales(spec.length_nm).as_dict()}
