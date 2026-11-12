import math

import pytest
from pydantic import ValidationError

from wavepacket.config import UnitSpec
from wavepacket.units import electron_scales


@pytest.mark.parametrize("length_nm", [1e-150, 1e150])
def test_unit_boundary_rejects_unrepresentable_supported_display_factors(length_nm):
    # A finite t0 is insufficient: the 2D current unit also divides by t0*L0.
    with pytest.raises(ValidationError, match="representable"):
        UnitSpec(mode="electron", length_nm=length_nm)


@pytest.mark.parametrize("length_nm", [1e-20, 1.0, 1e20])
def test_supported_density_and_current_display_factors_remain_finite(length_nm):
    UnitSpec(mode="electron", length_nm=length_nm)
    units = electron_scales(length_nm)
    factors = [1 / length_nm, 1 / length_nm**2,
               1 / units.time_fs, 1 / (units.time_fs * length_nm)]
    assert all(math.isfinite(factor) and factor > 0 for factor in factors)
