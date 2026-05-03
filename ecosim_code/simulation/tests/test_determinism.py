"""
Tests de déterminisme : deux simulations avec le même seed doivent produire
exactement les mêmes résultats ; des seeds différents doivent diverger.
"""
from simulation.engine import SimulationEngine
from world.grid import Grid


def _make_grid(width=40, height=40) -> Grid:
    g = Grid(width, height)
    for row in g.cells:
        for cell in row:
            cell.soil_type = "clay"
            cell.temperature = 20.0
            cell.humidity = 0.5
            cell.altitude = 0.5
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


def _run_sim(seed, ticks=100):
    eng = SimulationEngine(_make_grid(), seed=seed)
    eng.add_species(_HERBE, count=20)
    eng.add_species(_LAPIN, count=10)
    for _ in range(ticks):
        eng.tick()
    positions = [(round(i.x, 3), round(i.y, 3)) for i in eng.individuals]
    return dict(eng.species_counts), positions


def _get_spawn_positions(seed):
    eng = SimulationEngine(_make_grid(), seed=seed)
    eng.add_species(_HERBE, count=5)
    eng.add_species(_LAPIN, count=5)
    plants = [(round(p.x, 4), round(p.y, 4)) for p in eng.plants]
    inds   = [(round(i.x, 4), round(i.y, 4)) for i in eng.individuals]
    return plants, inds


class TestDeterminism:

    def test_same_seed_same_populations(self):
        """Deux simulations avec le même seed produisent les mêmes compteurs et positions."""
        counts_a, pos_a = _run_sim(seed=42, ticks=100)
        counts_b, pos_b = _run_sim(seed=42, ticks=100)
        assert counts_a == counts_b
        assert pos_a == pos_b

    def test_different_seeds_different_state(self):
        """Deux simulations avec des seeds différents produisent des états différents."""
        _counts_a, pos_a = _run_sim(seed=1, ticks=100)
        _counts_b, pos_b = _run_sim(seed=999, ticks=100)
        assert pos_a != pos_b

    def test_same_seed_same_spawn_positions(self):
        """Les positions de spawn initiales sont identiques à seed identique."""
        pos_a = _get_spawn_positions(seed=7)
        pos_b = _get_spawn_positions(seed=7)
        assert pos_a == pos_b
