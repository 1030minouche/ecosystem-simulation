"""Tests pour engine/timescale.py — découplage temps bio / temps de calcul."""
from ecosim.engine.timescale import apply_time_acceleration, is_duration_field


def test_is_duration_field_recognizes_known_suffixes():
    assert is_duration_field("max_age")
    assert is_duration_field("gestation_ticks")
    assert is_duration_field("sexual_maturity_ticks")
    assert is_duration_field("reproduction_cooldown_length")


def test_is_duration_field_rejects_non_durations():
    assert not is_duration_field("speed")
    assert not is_duration_field("color")
    assert not is_duration_field("energy_consumption")
    assert not is_duration_field("temp_min")


def test_apply_time_acceleration_default_is_noop():
    params = {"max_age": 100_000, "gestation_ticks": 1_000, "speed": 1.2}
    assert apply_time_acceleration(params, time_acceleration=1.0) is params


def test_apply_time_acceleration_zero_or_negative_is_noop():
    params = {"max_age": 100_000}
    assert apply_time_acceleration(params, time_acceleration=0.0) is params
    assert apply_time_acceleration(params, time_acceleration=-2.0) is params


def test_apply_time_acceleration_scales_durations_only():
    params = {
        "max_age": 1_000_000,
        "gestation_ticks": 1_000,
        "reproduction_cooldown_length": 60_000,
        "speed": 1.2,
        "energy_consumption": 0.03,
        "color": [0.9, 0.9, 0.8],
    }
    scaled = apply_time_acceleration(params, time_acceleration=10.0)
    assert scaled["max_age"] == 100_000
    assert scaled["gestation_ticks"] == 100
    assert scaled["reproduction_cooldown_length"] == 6_000
    # Non-durations unchanged
    assert scaled["speed"] == 1.2
    assert scaled["energy_consumption"] == 0.03
    assert scaled["color"] == [0.9, 0.9, 0.8]


def test_apply_time_acceleration_preserves_int_type():
    params = {"gestation_ticks": 1_000}
    scaled = apply_time_acceleration(params, time_acceleration=10.0)
    assert isinstance(scaled["gestation_ticks"], int)


def test_apply_time_acceleration_preserves_float_type():
    params = {"some_age": 1234.5}
    scaled = apply_time_acceleration(params, time_acceleration=10.0)
    assert isinstance(scaled["some_age"], float)
    assert scaled["some_age"] == 123.45


def test_apply_time_acceleration_returns_copy():
    """Le dict d'origine ne doit pas être muté quand on accélère."""
    params = {"max_age": 1_000}
    scaled = apply_time_acceleration(params, time_acceleration=10.0)
    assert scaled is not params
    assert params["max_age"] == 1_000  # original intact


def test_apply_time_acceleration_min_one_for_int():
    """Une durée int ne tombe jamais à zéro (évite la division par 0 plus loin)."""
    params = {"gestation_ticks": 5}
    scaled = apply_time_acceleration(params, time_acceleration=100.0)
    assert scaled["gestation_ticks"] == 1
