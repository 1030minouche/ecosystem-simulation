"""
Tests pour simulation/engine.py
  - Ajout d'espèces et spawn
  - Avancement des ticks
  - Variabilité inter-simulation (sample_params intégré)
  - Un seul objet Species partagé par tous les individus d'une simulation
"""
import pytest
from simulation.engine import SimulationEngine, DAY_LENGTH
from world.grid import Grid


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_grid(width=40, height=40) -> Grid:
    import numpy as np
    g = Grid(width, height)
    g.soil_type[:] = "clay"
    g.temperature[:] = 20.0
    g.humidity[:] = 0.5
    g.altitude[:] = 0.5
    return g


# Params complets pour un lapin (std = 0 → fixe)
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


# ── Construction et spawn ─────────────────────────────────────────────────────

class TestAddSpecies:

    def test_species_registered_in_list(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=10)
        assert len(eng.species_list) == 1
        assert eng.species_list[0].name == "Lapin"

    def test_correct_number_of_individuals_spawned(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=10)
        assert len(eng.individuals) == 10

    def test_plants_spawned_for_plant_species(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_HERBE, count=20)
        assert len(eng.plants) == 20
        assert len(eng.individuals) == 0

    def test_two_species_both_registered(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_HERBE, count=20)
        eng.add_species(_LAPIN, count=10)
        assert len(eng.species_list) == 2

    def test_default_counts_stored(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=15)
        assert eng._default_counts["Lapin"] == 15


# ── Tick ─────────────────────────────────────────────────────────────────────

class TestTick:

    def test_initial_tick_count(self):
        eng = SimulationEngine(_make_grid())
        assert eng.tick_count == DAY_LENGTH // 2

    def test_tick_increments_counter(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=5)
        before = eng.tick_count
        eng.tick()
        assert eng.tick_count == before + 1

    def test_multiple_ticks_do_not_crash(self):
        eng = SimulationEngine(_make_grid())
        eng.add_species(_HERBE, count=10)
        eng.add_species(_LAPIN, count=5)
        for _ in range(200):
            eng.tick()

    def test_individuals_can_die_over_time(self):
        """Avec énergie quasi nulle, certains individus doivent mourir."""
        params = _LAPIN.copy()
        params["energy_start"] = 0.001
        eng = SimulationEngine(_make_grid())
        eng.add_species(params, count=20)
        for _ in range(5):
            eng.tick()
        # Au moins quelques individus morts
        dead = [i for i in eng.individuals if not i.alive]
        assert len(dead) > 0 or len(eng.individuals) < 20


# ── Variabilité inter-simulation ─────────────────────────────────────────────

class TestInterSimulationVariability:

    def test_std_zero_same_speed_every_simulation(self):
        """Avec std=0, chaque simulation doit avoir la même valeur."""
        speeds = set()
        for seed in range(10):
            eng = SimulationEngine(_make_grid(), seed=seed)
            eng.add_species(_LAPIN, count=1)
            speeds.add(round(eng.species_list[0].speed, 8))
        assert len(speeds) == 1, "std=0 doit donner la même vitesse partout"

    def test_nonzero_std_different_values_across_simulations(self):
        """Avec std>0, les simulations doivent avoir des valeurs différentes."""
        params = _LAPIN.copy()
        params["speed_std"] = 0.5

        speeds = set()
        for seed in range(20):
            eng = SimulationEngine(_make_grid(), seed=seed)
            eng.add_species(params, count=1)
            speeds.add(round(eng.species_list[0].speed, 4))

        assert len(speeds) > 1, "std>0 doit produire des vitesses différentes"

    def test_sampled_value_never_negative(self):
        """Même avec un σ très grand, la valeur échantillonnée reste ≥ 0."""
        params = _LAPIN.copy()
        params["speed"] = 0.1
        params["speed_std"] = 100.0   # σ énorme

        for seed in range(50):
            eng = SimulationEngine(_make_grid(), seed=seed)
            eng.add_species(params, count=1)
            assert eng.species_list[0].speed >= 0.0


# ── Individualisation des Species ────────────────────────────────────────────

class TestSpeciesSharing:

    def test_individuals_have_own_species_objects(self):
        """Chaque animal a son propre objet Species (individualisation)."""
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=20)
        sp_objects = [id(ind.species) for ind in eng.individuals]
        # Tous doivent être des objets distincts
        assert len(set(sp_objects)) == len(eng.individuals)

    def test_individuals_same_species_name(self):
        """Chaque animal a le bon nom d'espèce."""
        eng = SimulationEngine(_make_grid())
        eng.add_species(_LAPIN, count=10)
        assert all(ind.species.name == "Lapin" for ind in eng.individuals)

    def test_all_plants_share_same_species_object(self):
        """Les plantes partagent toujours le même objet Species (pas de reprod. sexuée)."""
        eng = SimulationEngine(_make_grid())
        eng.add_species(_HERBE, count=15)
        sp = eng.species_list[0]
        assert all(p.species is sp for p in eng.plants)


# ── Population overrides ──────────────────────────────────────────────────────

class TestPopulationOverrides:

    def test_override_stored(self):
        eng = SimulationEngine(_make_grid())
        eng.set_population_overrides({"Lapin": 42})
        assert eng._population_overrides["Lapin"] == 42

    def test_negative_override_clamped_to_zero(self):
        eng = SimulationEngine(_make_grid())
        eng.set_population_overrides({"Lapin": -5})
        assert eng._population_overrides["Lapin"] == 0

    def test_float_override_converted_to_int(self):
        eng = SimulationEngine(_make_grid())
        eng.set_population_overrides({"Lapin": 7.9})
        assert isinstance(eng._population_overrides["Lapin"], int)
