"""
Tests pour entities/animal.py
  - Rythmes d'activité (_is_resting, _is_pre_rest)
  - Cycle de vie (énergie, âge, mortalité)
  - Gestation et naissance
  - Contraintes de position
"""
import random

import pytest
from entities.animal import Individual, _is_resting, _is_pre_rest
from helpers import MockGrid, make_animal_species


# ── Rythmes d'activité ───────────────────────────────────────────────────────

class TestActivityPatterns:

    # Diurne : actif 0.18–0.82, dort sinon
    def test_diurnal_active_at_noon(self):
        assert not _is_resting(0.50, "diurnal")

    def test_diurnal_active_at_dawn(self):
        assert not _is_resting(0.20, "diurnal")

    def test_diurnal_rests_at_midnight(self):
        assert _is_resting(0.05, "diurnal")

    def test_diurnal_rests_deep_night(self):
        assert _is_resting(0.90, "diurnal")

    # Nocturne : actif 0.82–0.18, dort sinon
    def test_nocturnal_active_at_midnight(self):
        assert not _is_resting(0.05, "nocturnal")

    def test_nocturnal_rests_at_noon(self):
        assert _is_resting(0.50, "nocturnal")

    def test_nocturnal_rests_at_dawn(self):
        assert _is_resting(0.25, "nocturnal")

    # Crépusculaire : actif aube (0.18–0.38) + crépuscule (0.62–0.82)
    def test_crepuscular_active_at_dawn(self):
        assert not _is_resting(0.25, "crepuscular")

    def test_crepuscular_active_at_dusk(self):
        assert not _is_resting(0.70, "crepuscular")

    def test_crepuscular_rests_at_noon(self):
        assert _is_resting(0.50, "crepuscular")

    def test_crepuscular_rests_at_midnight(self):
        assert _is_resting(0.05, "crepuscular")

    # Pre-rest
    def test_pre_rest_diurnal_just_before_sunset(self):
        assert _is_pre_rest(0.78, "diurnal")

    def test_pre_rest_diurnal_not_at_noon(self):
        assert not _is_pre_rest(0.50, "diurnal")

    def test_pre_rest_nocturnal_just_before_sunrise(self):
        assert _is_pre_rest(0.14, "nocturnal")

    def test_pre_rest_nocturnal_not_at_midnight(self):
        assert not _is_pre_rest(0.05, "nocturnal")


# ── Énergie ──────────────────────────────────────────────────────────────────

class TestEnergy:

    def test_energy_decreases_each_tick(self):
        sp = make_animal_species(energy_consumption=1.0)
        ind = Individual(species=sp, x=25, y=25, energy=100.0)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.energy < 100.0

    def test_energy_decreases_less_when_resting(self):
        sp = make_animal_species(energy_consumption=1.0, activity_pattern="diurnal")
        grid = MockGrid()

        ind_active = Individual(species=sp, x=25, y=25, energy=100.0)
        ind_active.tick(grid, [], [], time_of_day=0.5)   # midi = actif

        ind_rest = Individual(species=sp, x=25, y=25, energy=100.0)
        ind_rest.tick(grid, [], [], time_of_day=0.05)   # minuit = repos

        assert ind_rest.energy > ind_active.energy

    def test_animal_dies_at_zero_energy(self):
        sp = make_animal_species(energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=0.0)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert not ind.alive

    def test_dead_animal_tick_returns_empty(self):
        sp = make_animal_species()
        ind = Individual(species=sp, x=25, y=25, energy=0.0, alive=False)
        result = ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert result == []


# ── Âge et mort naturelle ────────────────────────────────────────────────────

class TestAgeDeath:

    def test_animal_dies_at_max_age(self):
        sp = make_animal_species(max_age=10)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=10)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert not ind.alive

    def test_animal_alive_before_max_age(self):
        sp = make_animal_species(max_age=10_000, energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=5)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.alive

    def test_age_increments_each_tick(self):
        sp = make_animal_species(energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=0)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.age == 1


# ── Mortalité juvénile ───────────────────────────────────────────────────────

class TestJuvenileMortality:

    def test_juvenile_always_dies_with_rate_one(self):
        random.seed(0)
        sp = make_animal_species(juvenile_mortality_rate=1.0,
                                  sexual_maturity_ticks=1_000)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=5)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert not ind.alive
        assert getattr(ind, "death_cause", "") == "juvenile_mortality"

    def test_mature_animal_immune_to_juvenile_mortality(self):
        random.seed(0)
        sp = make_animal_species(juvenile_mortality_rate=1.0,
                                  sexual_maturity_ticks=10,
                                  energy_consumption=0.0)
        # Individu bien au-delà de la maturité
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=500)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.alive

    def test_juvenile_mortality_zero_never_kills(self):
        random.seed(0)
        sp = make_animal_species(juvenile_mortality_rate=0.0,
                                  sexual_maturity_ticks=1_000,
                                  energy_consumption=0.0)
        for _ in range(100):
            ind = Individual(species=sp, x=25, y=25, energy=1_000.0, age=5)
            ind.tick(MockGrid(), [], [], time_of_day=0.5)
            assert ind.alive


# ── Machine à états ──────────────────────────────────────────────────────────

class TestStateMachine:

    def test_seek_food_when_energy_below_threshold(self):
        sp = make_animal_species()
        # Seuil seek_food = energy_start * 0.60 = 60
        ind = Individual(species=sp, x=25, y=25, energy=50.0)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.state in ("seek_food", "dead")

    def test_wander_when_energy_sufficient_no_partner(self):
        sp = make_animal_species(reproduction_cooldown_length=0)
        # Énergie entre 60% et 75% → wander (pas assez pour reproduire)
        ind = Individual(species=sp, x=25, y=25, energy=65.0,
                          reproduction_cooldown=0)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.state in ("wander", "seek_food", "dead", "sleep")

    def test_state_is_sleep_when_resting(self):
        sp = make_animal_species(activity_pattern="diurnal", energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0)
        ind.tick(MockGrid(), [], [], time_of_day=0.05)   # nuit
        assert ind.state == "sleep"


# ── Gestation ────────────────────────────────────────────────────────────────

class TestGestation:

    def test_delivery_at_end_of_gestation(self):
        sp = make_animal_species(gestation_ticks=5,
                                  litter_size_min=2, litter_size_max=2,
                                  energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          gestation_timer=1, gestation_count=2)
        babies = ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert len(babies) == 2

    def test_gestation_timer_decrements(self):
        sp = make_animal_species(gestation_ticks=10, energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          gestation_timer=5, gestation_count=1)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.gestation_timer == 4

    def test_no_delivery_during_gestation(self):
        sp = make_animal_species(gestation_ticks=10, energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          gestation_timer=3, gestation_count=2)
        babies = ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert len(babies) == 0

    def test_newborns_share_same_species(self):
        sp = make_animal_species(gestation_ticks=1,
                                  litter_size_min=3, litter_size_max=3,
                                  energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          gestation_timer=1, gestation_count=3)
        babies = ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert all(b.species is sp for b in babies)

    def test_gestation_count_reset_after_delivery(self):
        sp = make_animal_species(gestation_ticks=1,
                                  litter_size_min=2, litter_size_max=2,
                                  energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          gestation_timer=1, gestation_count=2)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.gestation_count == 0


# ── Position ─────────────────────────────────────────────────────────────────

class TestPosition:

    def test_position_stays_within_grid_bounds(self):
        sp = make_animal_species(speed=100.0, energy_consumption=0.0)
        grid = MockGrid(width=50, height=50)
        ind = Individual(species=sp, x=1, y=1, energy=10_000.0)
        for _ in range(30):
            if not ind.alive:
                break
            ind.tick(grid, [], [], time_of_day=0.5)
            assert 0 <= ind.x <= 49
            assert 0 <= ind.y <= 49

    def test_reproduction_cooldown_decrements(self):
        sp = make_animal_species(energy_consumption=0.0)
        ind = Individual(species=sp, x=25, y=25, energy=1_000.0,
                          reproduction_cooldown=10)
        ind.tick(MockGrid(), [], [], time_of_day=0.5)
        assert ind.reproduction_cooldown == 9
