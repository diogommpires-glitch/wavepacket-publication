import numpy as np
import pytest
from scipy.constants import elementary_charge, hbar

from wavepacket.units import electron_scales, to_dimensionless, to_physical


def test_electron_scales_and_factor_of_two_convention():
    scales = electron_scales(1.0)
    assert scales.energy_ev == pytest.approx(0.0761996, rel=1e-5)
    assert scales.time_fs == pytest.approx(8.63799, rel=1e-5)
    assert scales.energy_ev * elementary_charge * scales.time_fs * 1e-15 == pytest.approx(hbar)
    assert scales.momentum_si == pytest.approx(hbar / 1e-9)


def test_scale_similarity_and_round_trip():
    one, two = electron_scales(1), electron_scales(2)
    assert two.energy_ev == pytest.approx(one.energy_ev / 4)
    assert two.time_fs == pytest.approx(one.time_fs * 4)
    for quantity in ("length", "time", "energy", "momentum"):
        value = np.array([-1.0, 0.0, 3.0])
        assert np.allclose(to_dimensionless(to_physical(value, quantity, 2), quantity, 2), value)


@pytest.mark.parametrize("length", [0, -1, float("nan"), float("inf"), 1e-200, 1e-160, 1e200])
def test_invalid_unit_scales(length):
    with pytest.raises(ValueError):
        electron_scales(length)


@pytest.mark.parametrize("length", [1e-200, 1e-160, 1e200])
def test_unit_spec_rejects_unrepresentable_derived_scales(length):
    from wavepacket.config import UnitSpec
    with pytest.raises(ValueError, match="representable"):
        UnitSpec(length_nm=length)
