"""
Tests pour entities/plant.py
  - Croissance et mort
  - Reproduction et dispersion
  - Respect de max_population
"""
import random

import pytest
from entities.plant import Plant
from helpers import MockGrid, make_plant_species


# ── Croissance ───────────────────────────────────────────────────────────────

class TestPlantGrowth:

    def test_growth_increases_in_good_conditions(self):
        sp = make_plant_species(growth_rate=0.05)
        grid = MockGrid()
        plant = Plant(species=sp, x=10, y=10, growth=0.5)
        plant.tick(grid, 100)
        assert plant.growth > 0.5

    def test_growth_capped_at_one(self):
        sp = make_plant_species(growth_rate=1.0)
        grid = MockGrid()
        plant = Plant(species=sp, x=10, y=10, growth=0.99)
        plant.tick(grid, 100)
        assert plant.growth <= 1.0

    def test_growth_decreases_in_bad_temperature(self):
        sp = make_plant_species(temp_min=10.0, temp_max=20.0, growth_rate=0.0)
        grid = MockGrid()
        grid.cells[10][10].temperature = 50.0   # hors plage
        plant = Plant(species=sp, x=10, y=10, growth=0.5)
        plant.tick(grid, 100)
        assert plant.growth < 0.5

    def test_age_increments_each_tick(self):
        sp = make_plant_species()
        grid = MockGrid()
        plant = Plant(species=sp, x=10, y=10, age=0)
        plant.tick(grid, 100)
        assert plant.age == 1


# ── Mort ─────────────────────────────────────────────────────────────────────

class TestPlantDeath:

    def test_plant_dies_at_max_age(self):
        sp = make_plant_species(max_age=5)
        plant = Plant(species=sp, x=10, y=10, age=5)
        plant.tick(MockGrid(), 0)
        assert not plant.alive

    def test_plant_dies_when_energy_zero(self):
        sp = make_plant_species(growth_rate=0.0)
        grid = MockGrid()
        grid.cells[10][10].temperature = 99.0   # hors plage → perd de l'énergie
        plant = Plant(species=sp, x=10, y=10, growth=0.01, energy=0.001)
        plant.tick(grid, 100)
        assert not plant.alive

    def test_plant_dies_in_water(self):
        sp = make_plant_species()
        grid = MockGrid()
        grid.cells[10][10].soil_type = "water"
        plant = Plant(species=sp, x=10, y=10, growth=0.1, energy=1.0)
        # Plusieurs ticks pour vider l'énergie
        for _ in range(500):
            plant.tick(grid, 100)
            if not plant.alive:
                break
        assert not plant.alive

    def test_plant_dead_tick_returns_empty_and_stays_dead(self):
        sp = make_plant_species()
        plant = Plant(species=sp, x=10, y=10, alive=False)
        result = plant.tick(MockGrid(), 0)
        assert result == []
        assert not plant.alive

    def test_plant_dies_when_out_of_grid(self):
        sp = make_plant_species()
        plant = Plant(species=sp, x=-1, y=-1)
        plant.tick(MockGrid(), 0)
        assert not plant.alive


# ── Reproduction ─────────────────────────────────────────────────────────────

class TestPlantReproduction:

    def test_plant_reproduces_when_conditions_met(self):
        random.seed(42)
        sp = make_plant_species(reproduction_rate=1.0, dispersal_radius=5)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=0)
        grid = MockGrid()
        children = plant.tick(grid, 0)
        assert len(children) == 1

    def test_no_reproduction_below_growth_threshold(self):
        sp = make_plant_species(reproduction_rate=1.0)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.5, reproduction_cooldown=0)
        children = plant.tick(MockGrid(), 0)
        assert len(children) == 0

    def test_no_reproduction_on_cooldown(self):
        sp = make_plant_species(reproduction_rate=1.0)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=99)
        children = plant.tick(MockGrid(), 0)
        assert len(children) == 0

    def test_no_reproduction_when_max_population_reached(self):
        sp = make_plant_species(reproduction_rate=1.0, max_population=10)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=0)
        children = plant.tick(MockGrid(), 10)   # pop déjà au max
        assert len(children) == 0

    def test_cooldown_set_after_reproduction(self):
        random.seed(42)
        sp = make_plant_species(reproduction_rate=1.0,
                                 reproduction_cooldown_length=50)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=0)
        plant.tick(MockGrid(), 0)
        assert plant.reproduction_cooldown == 50

    def test_cooldown_decrements_each_tick(self):
        sp = make_plant_species()
        plant = Plant(species=sp, x=25, y=25, reproduction_cooldown=30)
        plant.tick(MockGrid(), 100)
        assert plant.reproduction_cooldown == 29

    def test_child_plant_in_grid_bounds(self):
        random.seed(0)
        sp = make_plant_species(reproduction_rate=1.0, dispersal_radius=10)
        grid = MockGrid(width=50, height=50)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=0)
        for _ in range(20):
            plant.reproduction_cooldown = 0
            plant.growth = 0.95
            children = plant.tick(grid, 0)
            for child in children:
                assert 0 <= child.x < 50
                assert 0 <= child.y < 50

    def test_child_inherits_species(self):
        random.seed(42)
        sp = make_plant_species(reproduction_rate=1.0)
        plant = Plant(species=sp, x=25, y=25,
                      growth=0.95, reproduction_cooldown=0)
        children = plant.tick(MockGrid(), 0)
        assert all(c.species is sp for c in children)
