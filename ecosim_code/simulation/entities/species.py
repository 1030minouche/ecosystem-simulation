from dataclasses import dataclass, field, fields as dc_fields
from typing import List
import random

# Paramètres dont la valeur est tirée selon N(µ, σ) au démarrage de chaque simulation
_VARIABLE_FLOAT = {
    "reproduction_rate", "energy_start", "energy_consumption", "energy_from_food",
    "speed", "perception_radius", "growth_rate", "juvenile_mortality_rate", "fear_factor",
}
_VARIABLE_INT = {
    "max_age", "reproduction_cooldown_length", "sexual_maturity_ticks", "gestation_ticks",
}


def sample_params(params: dict) -> dict:
    """
    Tire les paramètres de l'espèce selon N(µ, σ) une seule fois par simulation.
    Les clés «*_std» du dict définissent l'écart-type (0 = valeur fixe).
    Retourne un dict propre (sans clés _std) prêt pour Species(**...).
    """
    result = {}
    for key, val in params.items():
        if key.endswith("_std"):
            continue
        std = params.get(f"{key}_std", 0.0) or 0.0
        if std > 0 and key in _VARIABLE_FLOAT:
            result[key] = max(0.0, random.gauss(val, std))
        elif std > 0 and key in _VARIABLE_INT:
            result[key] = max(0, round(random.gauss(val, std)))
        else:
            result[key] = val
    return result

def blend_species(s1: "Species", s2: "Species", mutation_rate: float = 0.0) -> "Species":
    """Crée un Species dont les params variables sont la moyenne de s1 et s2,
    puis applique une petite perturbation gaussienne selon mutation_rate
    (écart-type = mutation_rate × valeur moyenne, 0 = pas de mutation).
    Les params non-variables (conditions, couleur, etc.) sont hérités de s1.
    """
    kwargs = {}
    for f in dc_fields(s1):
        v1 = getattr(s1, f.name)
        v2 = getattr(s2, f.name)
        if f.name in _VARIABLE_FLOAT:
            mean = (v1 + v2) / 2.0
            if mutation_rate > 0:
                mean = max(0.0, random.gauss(mean, abs(mean) * mutation_rate))
            kwargs[f.name] = mean
        elif f.name in _VARIABLE_INT:
            mean = (v1 + v2) / 2.0
            if mutation_rate > 0:
                mean = max(0.0, random.gauss(mean, abs(mean) * mutation_rate))
            kwargs[f.name] = max(0, round(mean))
        else:
            kwargs[f.name] = v1
    return Species(**kwargs)


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

    # Comportement de troupeau
    herd_cohesion: float = 0.0               # 0 = solitaire, 1 = colle au groupe

    # Génétique
    mutation_rate: float = 0.0               # écart-type relatif appliqué à chaque param
                                             # variable lors de la reproduction
                                             # (ex: 0.05 → ±5% de chaque valeur moyenne)
                                             # lors du wander, biaise la cible vers le centroïde
                                             # des congénères proches (rayon = 2.5 × perception)

    # Territoire / habitat
    territory_radius: float = 0.0            # rayon du territoire autour du lieu de naissance
                                             # (0 = pas de territoire)
    home_protection: float = 0.0             # probabilité d'échapper à un prédateur quand
                                             # l'animal est dans son territoire (0-1)
