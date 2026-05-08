"""
Système de maladies épidémiques pour EcoSim.
Modèle SEIR simplifié : Susceptible → Exposed → Infected → Recovered (→ Susceptible)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# circular-import-guard: entities.animal imports entities.disease at runtime;
# disease.py references Individual only for type hints.
if TYPE_CHECKING:
    from entities.animal import Individual

DISEASE_REGISTRY: dict[str, "DiseaseSpec"] = {}


@dataclass
class DiseaseSpec:
    name: str
    transmission_rate: float
    transmission_radius: float
    incubation_ticks: int
    infectious_ticks: int
    energy_drain: float
    speed_penalty: float
    mortality_chance: float
    immunity_ticks: int
    affects_species: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "DiseaseSpec":
        return cls(**d)


@dataclass
class DiseaseState:
    """État épidémiologique d'un individu pour une maladie donnée."""
    disease_name: str
    status: str = "susceptible"   # susceptible | exposed | infected | recovered
    ticks_in_state: int = 0
    source_id: int = -1

    def tick(self, individual: "Individual", spec: DiseaseSpec) -> str:
        """Avance d'un tick. Retourne 'alive' ou 'dead'."""
        from entities.rng import rng
        self.ticks_in_state += 1

        if self.status == "exposed":
            if self.ticks_in_state >= spec.incubation_ticks:
                self.status = "infected"
                self.ticks_in_state = 0

        elif self.status == "infected":
            resistance = individual._effective_params.get("disease_resistance", 0.5)
            individual.energy -= spec.energy_drain * (1.0 - resistance * 0.5)
            mort_chance = spec.mortality_chance * (1.0 - resistance)
            if rng.random() < mort_chance:
                return "dead"
            if self.ticks_in_state >= spec.infectious_ticks:
                if spec.immunity_ticks > 0:
                    self.status = "recovered"
                else:
                    self.status = "susceptible"
                self.ticks_in_state = 0

        elif self.status == "recovered":
            if self.ticks_in_state >= spec.immunity_ticks:
                self.status = "susceptible"
                self.ticks_in_state = 0

        return "alive"


def try_infect(source: "Individual", target: "Individual",
               spec: DiseaseSpec) -> bool:
    """Tente une transmission de source à target. Retourne True si infection."""
    from entities.rng import rng

    if spec.affects_species and target.species.name not in spec.affects_species:
        return False
    existing = target.disease_states.get(spec.name)
    if existing and existing.status != "susceptible":
        return False
    dist = math.hypot(source.x - target.x, source.y - target.y)
    if dist > spec.transmission_radius:
        return False
    resistance = target._effective_params.get("disease_resistance", 0.5)
    effective_rate = spec.transmission_rate * (1.0 - resistance * 0.4)
    if rng.random() < effective_rate:
        state = DiseaseState(disease_name=spec.name,
                             status="exposed", source_id=id(source))
        target.disease_states[spec.name] = state
        return True
    return False
