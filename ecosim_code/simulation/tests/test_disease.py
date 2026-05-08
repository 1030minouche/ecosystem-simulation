"""
Tests pour entities/disease.py
"""
import pytest
from entities.disease import DiseaseSpec, DiseaseState, DISEASE_REGISTRY, try_infect
from entities.genetics import Genome
from entities.rng import rng
from helpers import make_animal_species, MockGrid


def _make_individual(x=0.0, y=0.0, disease_resistance=0.5, species_name="test"):
    from entities.animal import Individual
    sp = make_animal_species(name=species_name, disease_resistance=disease_resistance)
    ind = Individual(species=sp, x=x, y=y)
    ind._effective_params["disease_resistance"] = disease_resistance
    return ind


def _make_spec(**kwargs) -> DiseaseSpec:
    defaults = dict(
        name="test_disease",
        transmission_rate=1.0,
        transmission_radius=5.0,
        incubation_ticks=10,
        infectious_ticks=20,
        energy_drain=1.0,
        speed_penalty=0.5,
        mortality_chance=0.0,
        immunity_ticks=50,
        affects_species=[],
    )
    defaults.update(kwargs)
    return DiseaseSpec(**defaults)


class TestDiseaseState:

    def test_exposed_transitions_to_infected_after_incubation(self):
        spec = _make_spec(incubation_ticks=5)
        ind = _make_individual()
        ds = DiseaseState(disease_name="test_disease", status="exposed")
        for _ in range(5):
            ds.tick(ind, spec)
        assert ds.status == "infected"

    def test_not_infected_before_incubation(self):
        spec = _make_spec(incubation_ticks=10)
        ind = _make_individual()
        ds = DiseaseState(disease_name="test_disease", status="exposed")
        for _ in range(5):
            ds.tick(ind, spec)
        assert ds.status == "exposed"

    def test_infected_drains_energy(self):
        spec = _make_spec(energy_drain=5.0, mortality_chance=0.0, infectious_ticks=100)
        ind = _make_individual(disease_resistance=0.0)
        ind.energy = 200.0
        ind._effective_params["disease_resistance"] = 0.0
        ds = DiseaseState(disease_name="test_disease", status="infected")
        ds.tick(ind, spec)
        assert ind.energy < 200.0

    def test_infected_with_high_resistance_drains_less_energy(self):
        spec = _make_spec(energy_drain=10.0, mortality_chance=0.0, infectious_ticks=100)
        ind_low  = _make_individual(disease_resistance=0.0)
        ind_high = _make_individual(disease_resistance=1.0)
        ind_low.energy  = 200.0
        ind_high.energy = 200.0
        ind_low._effective_params["disease_resistance"]  = 0.0
        ind_high._effective_params["disease_resistance"] = 1.0
        ds_low  = DiseaseState(disease_name="test_disease", status="infected")
        ds_high = DiseaseState(disease_name="test_disease", status="infected")
        ds_low.tick(ind_low, spec)
        ds_high.tick(ind_high, spec)
        assert ind_high.energy > ind_low.energy

    def test_recovered_returns_to_susceptible_after_immunity(self):
        spec = _make_spec(immunity_ticks=5)
        ind = _make_individual()
        ds = DiseaseState(disease_name="test_disease", status="recovered")
        for _ in range(5):
            ds.tick(ind, spec)
        assert ds.status == "susceptible"

    def test_no_reinfection_during_recovered(self):
        spec = _make_spec()
        ind = _make_individual()
        ds = DiseaseState(disease_name="test_disease", status="recovered")
        ind.disease_states["test_disease"] = ds
        source = _make_individual(x=0.0, y=0.0)
        source.disease_states["test_disease"] = DiseaseState(
            disease_name="test_disease", status="infected"
        )
        result = try_infect(source, ind, spec)
        assert result is False


class TestTryInfect:

    def test_infect_within_radius(self):
        rng.reset(1)
        spec = _make_spec(transmission_rate=1.0, transmission_radius=10.0)
        source = _make_individual(x=0.0, y=0.0)
        target = _make_individual(x=3.0, y=4.0)  # distance=5
        source.disease_states["test_disease"] = DiseaseState(
            disease_name="test_disease", status="infected"
        )
        result = try_infect(source, target, spec)
        assert result is True
        assert "test_disease" in target.disease_states

    def test_no_infect_outside_radius(self):
        rng.reset(2)
        spec = _make_spec(transmission_rate=1.0, transmission_radius=3.0)
        source = _make_individual(x=0.0, y=0.0)
        target = _make_individual(x=10.0, y=10.0)
        result = try_infect(source, target, spec)
        assert result is False

    def test_infect_respects_affects_species(self):
        rng.reset(3)
        spec = _make_spec(transmission_rate=1.0, affects_species=["wolf"])
        source = _make_individual(x=0.0, y=0.0, species_name="wolf")
        target = _make_individual(x=0.0, y=0.0, species_name="rabbit")
        result = try_infect(source, target, spec)
        assert result is False


class TestDiseaseSpecDeserialization:

    def test_from_dict(self):
        d = {
            "name": "flu",
            "transmission_rate": 0.1,
            "transmission_radius": 2.0,
            "incubation_ticks": 100,
            "infectious_ticks": 200,
            "energy_drain": 0.5,
            "speed_penalty": 0.8,
            "mortality_chance": 0.001,
            "immunity_ticks": 500,
            "affects_species": ["lapin"],
        }
        spec = DiseaseSpec.from_dict(d)
        assert spec.name == "flu"
        assert spec.transmission_rate == 0.1
        assert spec.affects_species == ["lapin"]
