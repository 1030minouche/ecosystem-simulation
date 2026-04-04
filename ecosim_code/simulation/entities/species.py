from dataclasses import dataclass, field
from typing import List

@dataclass
class Species:
    # Identité
    name: str
    type: str                    # "plant" | "herbivore" | "carnivore" | "omnivore"
    color: tuple = (1.0, 1.0, 1.0)  # RGB entre 0.0 et 1.0

    # Conditions de survie
    temp_min: float = 0.0
    temp_max: float = 40.0
    humidity_min: float = 0.0
    humidity_max: float = 1.0
    altitude_min: float = 0.0
    altitude_max: float = 1.0

    # Reproduction de base
    reproduction_rate: float = 0.1   # probabilité de succès à chaque tentative
    max_age: int = 100               # en ticks
    max_population: int = 200        # limite globale de l'espèce

    # Énergie
    energy_start: float = 100.0
    energy_consumption: float = 1.0  # par tick
    energy_from_food: float = 50.0

    # Comportement (animaux)
    speed: float = 1.0
    perception_radius: float = 5.0
    food_sources: List[str] = field(default_factory=list)

    # Végétaux
    growth_rate: float = 0.05
    dispersal_radius: int = 3

    # Rythme d'activité
    # "diurnal"    : actif le jour (0.18-0.82), dort la nuit
    # "nocturnal"  : actif la nuit (0.82-0.18), dort le jour
    # "crepuscular": actif à l'aube (0.18-0.38) et au crépuscule (0.62-0.82),
    #               repos en pleine nuit et en pleine journée
    activity_pattern: str = "diurnal"

    # Compat. ascendante : nocturnal est dérivé de activity_pattern
    @property
    def nocturnal(self) -> bool:
        return self.activity_pattern == "nocturnal"

    # Capacités physiques
    can_swim: bool = False

    # Reproduction avancée (biologie réaliste)
    reproduction_cooldown_length: int = 15   # ticks de repos après la naissance
    litter_size_min: int = 1                 # nb minimum de petits par portée
    litter_size_max: int = 1                 # nb maximum de petits par portée
    sexual_maturity_ticks: int = 0           # âge avant lequel la reproduction est impossible
    gestation_ticks: int = 0                 # délai entre fécondation et naissance (0 = instant)
    juvenile_mortality_rate: float = 0.0     # probabilité de mort/tick pour les juvéniles
    fear_factor: float = 0.0                 # réduction du taux de reprod. par prédateur proche
                                             # formule : rate / (1 + fear_factor × n_predateurs)
