from dataclasses import dataclass, field
from typing import List

@dataclass
class Cell:
    # Position dans la grille
    x: int
    y: int

    # Terrain
    altitude: float = 0.0        # 0.0 = mer, 1.0 = sommet
    soil_type: str = "clay"      # "sand" | "clay" | "rock" | "water"

    # Conditions environnementales
    temperature: float = 15.0    # en °C
    humidity: float = 0.5        # 0.0 à 1.0
    water_depth: float = 0.0     # 0 si terre sèche, > 0 si lac/rivière
    sunlight: float = 1.0        # 0.0 nuit/ombre, 1.0 plein soleil
    nutrient_level: float = 0.5  # fertilité du sol

    # Physique des fluides (rempli plus tard en Phase 4)
    wind_vx: float = 0.0
    wind_vy: float = 0.0
    water_vx: float = 0.0
    water_vy: float = 0.0

    # Entités vivantes présentes dans cette cellule
    vegetation: List = field(default_factory=list)
    animals: List = field(default_factory=list)