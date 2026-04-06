from dataclasses import dataclass


@dataclass
class Cell:
    # Position dans la grille
    x: int
    y: int

    # Terrain
    altitude: float = 0.0        # 0.0 = mer, 1.0 = sommet
    soil_type: str = "clay"      # "sand" | "clay" | "rock" | "water"

    # Conditions environnementales (synchronisées depuis grid.py via terrain.py)
    temperature: float = 15.0    # en °C
    humidity: float = 0.5        # 0.0 à 1.0
    water_depth: float = 0.0     # 0 si terre sèche, > 0 si eau
