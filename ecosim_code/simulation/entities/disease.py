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
    # Évolution du pathogène : taux de mutation à chaque transmission
    mutation_rate_pathogen: float = 0.0
    # Lignée (incrémentée à chaque mutation)
    lineage_id: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "DiseaseSpec":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def mutate(self) -> "DiseaseSpec":
        """Retourne une copie légèrement mutée du pathogène (si mutation_rate_pathogen > 0)."""
        from entities.rng import rng
        import copy
        mutant = copy.copy(self)
        mutant.lineage_id = self.lineage_id + 1
        mutant.name = self.name  # garde le même nom (même maladie, souche différente)
        if rng.random() < self.mutation_rate_pathogen:
            # Virulence (mortality_chance) peut augmenter ou diminuer
            mutant.mortality_chance = max(0.0, self.mortality_chance + rng.gauss(0.0, 0.0005))
            # Transmissibilité inversement corrélée à la virulence (compromis évolutif)
            delta = rng.gauss(0.0, 0.002)
            mutant.transmission_rate = max(0.0, min(1.0, self.transmission_rate + delta))
        return mutant


@dataclass
class DiseaseState:
    """État épidémiologique d'un individu pour une maladie donnée."""
    disease_name: str
    status: str = "susceptible"   # susceptible | exposed | infected | recovered
    ticks_in_state: int = 0
    source_id: int = -1
    # Vitesse originale sauvegardée lors de l'entrée en phase infectée
    original_max_speed: float = 0.0

    def tick(self, individual: "Individual", spec: DiseaseSpec) -> str:
        """Avance d'un tick. Retourne 'alive' ou 'dead'."""
        from entities.rng import rng
        self.ticks_in_state += 1

        if self.status == "exposed":
            if self.ticks_in_state >= spec.incubation_ticks:
                self.status = "infected"
                self.ticks_in_state = 0

        elif self.status == "infected":
            # Premier tick infecté : sauvegarder et appliquer la pénalité de vitesse
            if self.ticks_in_state == 1 and spec.speed_penalty < 1.0:
                self.original_max_speed = individual._effective_params.get(
                    "max_speed", individual.species.speed
                )
                individual._effective_params["max_speed"] = (
                    self.original_max_speed * spec.speed_penalty
                )
            resistance = individual._effective_params.get("disease_resistance", 0.5)
            individual.energy -= spec.energy_drain * (1.0 - resistance * 0.5)
            mort_chance = spec.mortality_chance * (1.0 - resistance)
            if rng.random() < mort_chance:
                return "dead"
            if self.ticks_in_state >= spec.infectious_ticks:
                # Restaurer la vitesse avant la transition
                if self.original_max_speed > 0.0:
                    individual._effective_params["max_speed"] = self.original_max_speed
                    self.original_max_speed = 0.0
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

    if spec.affects_species and target.species.name.lower() not in {a.lower() for a in spec.affects_species}:
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
        # Évolution du pathogène : muter la souche transmise
        transmitted_spec = spec.mutate() if spec.mutation_rate_pathogen > 0 else spec
        if transmitted_spec is not spec:
            # Mettre à jour le registre avec la nouvelle souche (remplace la précédente)
            DISEASE_REGISTRY[spec.name] = transmitted_spec
        state = DiseaseState(
            disease_name=spec.name,
            status="exposed",
            source_id=getattr(source, "uid", id(source)),
        )
        target.disease_states[spec.name] = state
        return True
    return False
