"""
Invariant de l'étape 1 du plan de vectorisation : la SoA (state_arrays.py)
reflète exactement les listes engine.individuals / engine.plants à chaque
synchronisation. Garantit qu'on peut basculer la lecture du hot path sur
les np.ndarray sans changement de comportement.
"""
import numpy as np

from ecosim.engine.engine import SimulationEngine
from ecosim.engine.state_arrays import StateArrays
from ecosim.world.grid import Grid


def _make_grid(width=40, height=40) -> Grid:
    g = Grid(width, height)
    g.soil_type[:] = "clay"
    g.temperature[:] = 20.0
    g.humidity[:] = 0.5
    g.altitude[:] = 0.5
    return g


_HERBE = {
    "name": "Herbe", "type": "plant",
    "color": (0.2, 0.8, 0.1),
    "temp_min": 5.0, "temp_max": 28.0,
    "humidity_min": 0.25, "humidity_max": 1.0,
    "altitude_min": 0.0, "altitude_max": 1.0,
    "reproduction_rate": 0.8,   "reproduction_rate_std": 0.0,
    "max_age": 876_000,         "max_age_std": 0,
    "max_population": 10_000,
    "energy_start": 100.0,      "energy_start_std": 0.0,
    "energy_consumption": 0.0,  "energy_consumption_std": 0.0,
    "energy_from_food": 0.0,    "energy_from_food_std": 0.0,
    "speed": 0.0,               "speed_std": 0.0,
    "perception_radius": 0.0,   "perception_radius_std": 0.0,
    "food_sources": [],
    "growth_rate": 3e-5,        "growth_rate_std": 0.0,
    "dispersal_radius": 6,
    "activity_pattern": "diurnal",
    "can_swim": False,
    "reproduction_cooldown_length": 1200, "reproduction_cooldown_length_std": 0,
    "litter_size_min": 1, "litter_size_max": 4,
    "sexual_maturity_ticks": 0,  "sexual_maturity_ticks_std": 0,
    "gestation_ticks": 0,         "gestation_ticks_std": 0,
    "juvenile_mortality_rate": 0.0, "juvenile_mortality_rate_std": 0.0,
    "fear_factor": 0.0,             "fear_factor_std": 0.0,
}

_LAPIN = {
    "name": "Lapin", "type": "herbivore",
    "color": (0.9, 0.9, 0.8),
    "temp_min": 0.0, "temp_max": 40.0,
    "humidity_min": 0.0, "humidity_max": 1.0,
    "altitude_min": 0.0, "altitude_max": 1.0,
    "reproduction_rate": 0.9,   "reproduction_rate_std": 0.0,
    "max_age": 1_314_000,       "max_age_std": 0,
    "max_population": 200,
    "energy_start": 100.0,      "energy_start_std": 0.0,
    "energy_consumption": 0.05, "energy_consumption_std": 0.0,
    "energy_from_food": 65.0,   "energy_from_food_std": 0.0,
    "speed": 1.2,               "speed_std": 0.0,
    "perception_radius": 12.0,  "perception_radius_std": 0.0,
    "food_sources": ["Herbe"],
    "growth_rate": 0.0,         "growth_rate_std": 0.0,
    "dispersal_radius": 0,
    "activity_pattern": "crepuscular",
    "can_swim": False,
    "reproduction_cooldown_length": 61_200, "reproduction_cooldown_length_std": 0,
    "litter_size_min": 3, "litter_size_max": 8,
    "sexual_maturity_ticks": 10_000,  "sexual_maturity_ticks_std": 0,
    "gestation_ticks": 1_000,          "gestation_ticks_std": 0,
    "juvenile_mortality_rate": 1.28e-5, "juvenile_mortality_rate_std": 0.0,
    "fear_factor": 3.0,                 "fear_factor_std": 0.0,
}


class TestStateArrays:

    def test_empty_state_arrays(self):
        arr = StateArrays()
        assert arr.ind_x.size == 0
        assert arr.plant_x.size == 0
        assert arr.species_ids == {}

    def test_sync_after_spawn(self):
        """Après add_species, la SoA reflète positions et énergies initiales."""
        eng = SimulationEngine(_make_grid(), seed=42)
        eng.add_species(_HERBE, count=20)
        eng.add_species(_LAPIN, count=10)
        arr = StateArrays()
        arr.sync_from(eng.individuals, eng.plants)
        arr.assert_matches(eng.individuals, eng.plants)
        assert arr.plant_x.size == len(eng.plants)
        assert arr.ind_x.size == len(eng.individuals)
        assert {"Herbe", "Lapin"} <= set(arr.species_ids)

    def test_invariant_after_100_ticks(self):
        """Invariant clé du plan : SoA == listes après 100 ticks (seed=42)."""
        eng = SimulationEngine(_make_grid(), seed=42)
        eng.add_species(_HERBE, count=20)
        eng.add_species(_LAPIN, count=10)
        arr = StateArrays()
        for _ in range(100):
            eng.tick()
        arr.sync_from(eng.individuals, eng.plants)
        arr.assert_matches(eng.individuals, eng.plants)

    def test_resync_handles_birth_and_death(self):
        """Naissances et morts : la SoA reconstruite reste cohérente."""
        eng = SimulationEngine(_make_grid(), seed=42)
        eng.add_species(_HERBE, count=20)
        eng.add_species(_LAPIN, count=10)
        arr = StateArrays()
        for tick_idx in range(1, 51):
            eng.tick()
            if tick_idx % 10 == 0:
                arr.sync_from(eng.individuals, eng.plants)
                arr.assert_matches(eng.individuals, eng.plants)

    def test_species_id_stable_across_sync(self):
        """species_id_for renvoie le même id d'un appel à l'autre."""
        arr = StateArrays()
        a = arr.species_id_for("Herbe")
        b = arr.species_id_for("Lapin")
        c = arr.species_id_for("Herbe")
        assert a == c
        assert a != b

    def test_dtypes(self):
        """Les dtypes annoncés (float64/int32/bool) sont respectés."""
        eng = SimulationEngine(_make_grid(), seed=42)
        eng.add_species(_HERBE, count=5)
        eng.add_species(_LAPIN, count=3)
        arr = StateArrays()
        arr.sync_from(eng.individuals, eng.plants)
        assert arr.ind_x.dtype == np.float64
        assert arr.ind_age.dtype == np.int32
        assert arr.ind_alive.dtype == bool
        assert arr.ind_species_id.dtype == np.int32
        assert arr.plant_x.dtype == np.float64
        assert arr.plant_alive.dtype == bool
