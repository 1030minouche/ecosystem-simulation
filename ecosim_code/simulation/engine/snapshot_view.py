"""
SimulationSnapshot : vue immuable de l'état de simulation pour le viewer.
"""

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class EntityView:
    x:      float
    y:      float
    species_name: str
    energy: float
    alive:  bool
    # Attributs spécifiques aux animaux (None pour les plantes)
    state:  str | None = None
    sex:    str | None = None
    gestation_timer: int | None = None
    age:    int | None = None
    # Attribut spécifique aux plantes
    growth: float | None = None


@dataclass(frozen=True)
class SimulationSnapshot:
    tick:           int
    plants:         tuple[EntityView, ...]
    individuals:    tuple[EntityView, ...]
    species_counts: dict[str, int]
    terrain_altitude: object  # np.ndarray en lecture seule (view)
