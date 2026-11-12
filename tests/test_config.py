import pytest
from pydantic import ValidationError

from wavepacket.config import SimulationConfig


def test_config_json_round_trip():
    config = SimulationConfig()
    assert SimulationConfig.model_validate_json(config.model_dump_json()) == config
    assert config.n_steps == 100


@pytest.mark.parametrize("patch", [
    {"grid": {"bounds": [[1, 1]], "points": [64]}},
    {"grid": {"bounds": [[-1e308, 1e308]], "points": [64]}},
    {"grid": {"bounds": [[-10, 10], [-10, 10]], "points": [32]}},
    {"solver": {"dt": 0}},
    {"solver": {"dt": 1e-320, "duration": 1e300}},
    {"solver": {"method": "cn", "kinetic": "spectral"}},
    {"solver": {"method": "cn", "kinetic": "fd2"}, "grid": {"bounds": [[-10, 10], [-10, 10]], "points": [32, 32]}},
    {"solver": {"method": "yoshida4"}, "boundary": {"kind": "cap"}},
    {"boundary": {"kind": "cap", "width": 41}},
    {"state": {"sigma": [0]}},
    {"state": {"params": {"chirp": [float("nan")]}}},
    {"potential": {"params": {"height": float("inf")}}},
    {"potential": {"kind": "harmonic", "params": {"omeag": 1}}},
    {"potential": {"kind": "harmonic", "params": {"omega": "fast"}}},
    {"potential": {"kind": "double_well", "params": {"height": -1}}},
    {"potential": {"kind": "rectangle", "params": {"width": -1}}},
    {"potential": {"kind": "waveguide", "params": {"angle": 2}}},
    {"state": {"kind": "gaussian", "params": {"unknown": 1}}},
    {"state": {"kind": "sum", "params": {"components": [{"state": {"params": {"typo": 1}}}]}}},
    {"solver": {"dt": 1e-8, "duration": 2}},
    {"grid": {"points": [300_000]}},
    {"sampling": {"snapshots": 129}},
    {"sampling": {"screen_x": 0}},
    {"grid": {"bounds": [[-10, 10], [-10, 10]], "points": [32, 32]}, "sampling": {"screen_x": 10}},
    {"budget": {"max_output_bytes": 1024}},
    {"unknown": "value"},
])
def test_invalid_configs_rejected(patch):
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate(patch)


def test_cn_and_caps_have_explicit_compatibility():
    assert SimulationConfig.model_validate({"solver": {"method": "cn", "kinetic": "fd2"}}).solver.method == "cn"
    assert SimulationConfig.model_validate({"boundary": {"kind": "cap"}}).boundary.kind == "cap"


@pytest.mark.parametrize("potential_kind", ["free", "waveguide"])
def test_nested_waveguide_mode_requires_waveguide_potential(potential_kind):
    state = {"kind": "waveguide_mode"}
    for _ in range(2):
        state = {"kind": "sum", "params": {"components": [{"state": state}]}}
    data = {
        "grid": {"bounds": [[-12, 12], [-12, 12]], "points": [32, 32]},
        "potential": {"kind": potential_kind},
        "state": state,
    }
    if potential_kind == "free":
        with pytest.raises(ValidationError, match="waveguide_mode requires a two-dimensional waveguide potential"):
            SimulationConfig.model_validate(data)
    else:
        config = SimulationConfig.model_validate(data)
        assert config.state.kind == "sum"
        assert config.potential.kind == "waveguide"


def test_unrepresentable_parameter_is_a_named_validation_error():
    with pytest.raises(ValidationError, match=r"potential\.params\.height must be a finite JSON number"):
        SimulationConfig.model_validate({
            "potential": {"kind": "gaussian", "params": {"height": 10**1000}},
        })
