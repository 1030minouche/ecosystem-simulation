"""
Tests pour entities/species.py
  - sample_params : tirage gaussien, clamp ≥ 0, suppression des clés _std
  - Species       : construction et propriétés
"""
import random
import statistics

import pytest
from entities.species import Species, sample_params, _VARIABLE_FLOAT, _VARIABLE_INT


# ── Fixtures ────────────────────────────────────────────────────────────────

def _base_params(**overrides) -> dict:
    """Dict complet de params avec tous les *_std à 0 (simulation fixe)."""
    p = {
        "name": "TestBete",
        "type": "herbivore",
        "speed": 1.5,                       "speed_std": 0.0,
        "perception_radius": 10.0,          "perception_radius_std": 0.0,
        "reproduction_rate": 0.8,           "reproduction_rate_std": 0.0,
        "max_age": 100_000,                 "max_age_std": 0,
        "energy_start": 100.0,              "energy_start_std": 0.0,
        "energy_consumption": 0.05,         "energy_consumption_std": 0.0,
        "energy_from_food": 50.0,           "energy_from_food_std": 0.0,
        "growth_rate": 0.0,                 "growth_rate_std": 0.0,
        "juvenile_mortality_rate": 0.0,     "juvenile_mortality_rate_std": 0.0,
        "fear_factor": 1.0,                 "fear_factor_std": 0.0,
        "reproduction_cooldown_length": 1_000, "reproduction_cooldown_length_std": 0,
        "sexual_maturity_ticks": 500,       "sexual_maturity_ticks_std": 0,
        "gestation_ticks": 200,             "gestation_ticks_std": 0,
    }
    p.update(overrides)
    return p


# ── sample_params : comportement avec std = 0 ────────────────────────────────

class TestSampleParamsFixed:

    def test_float_values_exact_when_std_zero(self):
        result = sample_params(_base_params())
        assert result["speed"] == 1.5
        assert result["reproduction_rate"] == 0.8
        assert result["energy_start"] == 100.0

    def test_int_values_exact_when_std_zero(self):
        result = sample_params(_base_params())
        assert result["max_age"] == 100_000
        assert result["gestation_ticks"] == 200

    def test_std_keys_absent_from_result(self):
        result = sample_params(_base_params())
        assert not any(k.endswith("_std") for k in result)

    def test_non_numeric_keys_pass_through(self):
        result = sample_params(_base_params())
        assert result["name"] == "TestBete"
        assert result["type"] == "herbivore"

    def test_species_constructable_from_result(self):
        result = sample_params(_base_params())
        sp = Species(**result)
        assert sp.speed == 1.5
        assert sp.name == "TestBete"


# ── sample_params : variabilité gaussienne ───────────────────────────────────

class TestSampleParamsVariability:

    def test_float_param_varies_with_nonzero_std(self):
        random.seed(0)
        params = _base_params(speed_std=0.5)
        values = {round(sample_params(params)["speed"], 6) for _ in range(50)}
        assert len(values) > 1, "speed devrait varier quand speed_std > 0"

    def test_int_param_varies_with_nonzero_std(self):
        random.seed(0)
        params = _base_params(max_age_std=5_000)
        values = {sample_params(params)["max_age"] for _ in range(50)}
        assert len(values) > 1, "max_age devrait varier quand max_age_std > 0"

    def test_float_result_is_float(self):
        random.seed(0)
        params = _base_params(speed_std=0.2)
        for _ in range(10):
            assert isinstance(sample_params(params)["speed"], float)

    def test_int_result_is_int(self):
        random.seed(0)
        params = _base_params(max_age_std=1_000)
        for _ in range(10):
            assert isinstance(sample_params(params)["max_age"], int)

    def test_distribution_centered_on_mean(self):
        """Sur 2000 tirages, la moyenne doit être très proche de µ."""
        random.seed(42)
        params = _base_params(speed=2.0, speed_std=0.4)
        values = [sample_params(params)["speed"] for _ in range(2_000)]
        mean = statistics.mean(values)
        assert abs(mean - 2.0) < 0.05, f"Moyenne obtenue : {mean:.4f}, attendu ≈ 2.0"

    def test_different_simulations_produce_different_values(self):
        """10 démarrages de simulation consécutifs → valeurs différentes."""
        params = _base_params(speed_std=0.3)
        values = {round(sample_params(params)["speed"], 6) for _ in range(10)}
        assert len(values) > 1


# ── sample_params : clamp (jamais négatif) ───────────────────────────────────

class TestSampleParamsClamping:

    def test_float_never_negative_with_large_std(self):
        random.seed(0)
        # µ = 0.1, σ = 10 → beaucoup de tirages négatifs sans clamp
        params = _base_params(speed=0.1, speed_std=10.0)
        values = [sample_params(params)["speed"] for _ in range(500)]
        assert all(v >= 0.0 for v in values), "speed ne doit jamais être < 0"

    def test_int_never_negative_with_large_std(self):
        random.seed(0)
        params = _base_params(max_age=100, max_age_std=10_000)
        values = [sample_params(params)["max_age"] for _ in range(500)]
        assert all(v >= 0 for v in values), "max_age ne doit jamais être < 0"

    def test_juvenile_mortality_never_negative(self):
        random.seed(0)
        params = _base_params(juvenile_mortality_rate=0.001,
                               juvenile_mortality_rate_std=1.0)
        values = [sample_params(params)["juvenile_mortality_rate"]
                  for _ in range(500)]
        assert all(v >= 0.0 for v in values)


# ── sample_params : champs non-variables non touchés ─────────────────────────

class TestSampleParamsNonVariable:

    def test_unknown_param_with_std_key_passes_through_unchanged(self):
        """Un param hors _VARIABLE_FLOAT/_INT ne doit pas être tiré."""
        params = _base_params()
        params["dispersal_radius"] = 5
        params["dispersal_radius_std"] = 100.0   # std énorme, mais pas variable
        result = sample_params(params)
        assert result["dispersal_radius"] == 5

    def test_all_variable_float_params_listed(self):
        """Vérifie que les clés attendues sont bien dans _VARIABLE_FLOAT."""
        for key in ("speed", "reproduction_rate", "energy_start",
                    "energy_consumption", "energy_from_food",
                    "perception_radius", "growth_rate",
                    "juvenile_mortality_rate", "fear_factor"):
            assert key in _VARIABLE_FLOAT

    def test_all_variable_int_params_listed(self):
        for key in ("max_age", "reproduction_cooldown_length",
                    "sexual_maturity_ticks", "gestation_ticks"):
            assert key in _VARIABLE_INT


# ── Species : propriétés et valeurs par défaut ───────────────────────────────

class TestSpeciesModel:

    def test_species_stores_name_and_type(self):
        sp = Species(name="Loup", type="carnivore")
        assert sp.name == "Loup"
        assert sp.type == "carnivore"

    def test_nocturnal_property_from_activity_pattern(self):
        sp_noc = Species(name="A", type="herbivore", activity_pattern="nocturnal")
        sp_day = Species(name="B", type="herbivore", activity_pattern="diurnal")
        assert sp_noc.nocturnal is True
        assert sp_day.nocturnal is False

    def test_default_values(self):
        sp = Species(name="X", type="herbivore")
        assert sp.can_swim is False
        assert sp.gestation_ticks == 0
        assert sp.fear_factor == 0.0
        assert sp.litter_size_min == 1
