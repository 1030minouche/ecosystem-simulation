"""
Objets mock partagés entre les fichiers de tests.
"""
import numpy as np
from entities.species import Species


def make_animal_species(**kwargs) -> Species:
    """Species herbivore minimal avec toutes les valeurs par défaut raisonnables."""
    defaults = dict(
        name="TestAnimal",
        type="herbivore",
        speed=1.0,
        perception_radius=10.0,
        reproduction_rate=0.8,
        max_age=10_000,
        energy_start=100.0,
        energy_consumption=1.0,
        energy_from_food=50.0,
        growth_rate=0.0,
        juvenile_mortality_rate=0.0,
        fear_factor=0.0,
        reproduction_cooldown_length=100,
        litter_size_min=1,
        litter_size_max=2,
        sexual_maturity_ticks=0,
        gestation_ticks=0,
        activity_pattern="diurnal",
        can_swim=False,
        temp_min=0.0,
        temp_max=40.0,
        humidity_min=0.0,
        humidity_max=1.0,
        altitude_min=0.0,
        altitude_max=1.0,
        max_population=200,
    )
    defaults.update(kwargs)
    return Species(**defaults)


def make_plant_species(**kwargs) -> Species:
    """Species plante minimale."""
    defaults = dict(
        name="TestPlante",
        type="plant",
        speed=0.0,
        perception_radius=0.0,
        reproduction_rate=1.0,
        max_age=100_000,
        energy_start=100.0,
        energy_consumption=0.0,
        energy_from_food=0.0,
        growth_rate=0.01,
        juvenile_mortality_rate=0.0,
        fear_factor=0.0,
        reproduction_cooldown_length=10,
        litter_size_min=1,
        litter_size_max=1,
        sexual_maturity_ticks=0,
        gestation_ticks=0,
        activity_pattern="diurnal",
        can_swim=False,
        dispersal_radius=5,
        temp_min=0.0,
        temp_max=40.0,
        humidity_min=0.0,
        humidity_max=1.0,
        altitude_min=0.0,
        altitude_max=1.0,
        max_population=10_000,
    )
    defaults.update(kwargs)
    return Species(**defaults)


class MockCell:
    """Cellule mock qui synchronise ses attributs vers les tableaux numpy du MockGrid parent."""

    def __init__(self, grid: "MockGrid", x: int, y: int):
        object.__setattr__(self, "_grid", grid)
        object.__setattr__(self, "_x", x)
        object.__setattr__(self, "_y", y)
        object.__setattr__(self, "altitude", 0.5)
        object.__setattr__(self, "vegetation", [])
        object.__setattr__(self, "animals", [])

    def __getattr__(self, name: str):
        g, x, y = object.__getattribute__(self, "_grid"), \
                  object.__getattribute__(self, "_x"), \
                  object.__getattribute__(self, "_y")
        if name == "soil_type":   return g.soil_type[y, x]
        if name == "temperature": return float(g.temperature[y, x])
        if name == "humidity":    return float(g.humidity[y, x])
        if name == "water_depth": return float(g.water_depth[y, x])
        raise AttributeError(name)

    def __setattr__(self, name: str, value):
        try:
            g = object.__getattribute__(self, "_grid")
            x = object.__getattribute__(self, "_x")
            y = object.__getattribute__(self, "_y")
        except AttributeError:
            object.__setattr__(self, name, value)
            return
        if name == "soil_type":   g.soil_type[y, x]   = value
        elif name == "temperature": g.temperature[y, x] = value
        elif name == "humidity":    g.humidity[y, x]    = value
        elif name == "water_depth": g.water_depth[y, x] = value
        else:                       object.__setattr__(self, name, value)


class MockGrid:
    def __init__(self, width=50, height=50):
        self.width = width
        self.height = height
        # Tableaux numpy — source de vérité
        self.soil_type   = np.full((height, width), "clay", dtype=object)
        self.temperature = np.full((height, width), 20.0)
        self.humidity    = np.full((height, width), 0.5)
        self.altitude    = np.full((height, width), 0.5)
        self.water_depth = np.zeros((height, width))
        # Cellules mock synchronisées
        self.cells = [
            [MockCell(self, x, y) for x in range(width)]
            for y in range(height)
        ]

    def get_cell(self, x: int, y: int) -> MockCell:
        return self.cells[y][x]

    def nearest_non_water(self, cx: int, cy: int, max_radius: int):
        for dy in range(-max_radius, max_radius + 1):
            for dx in range(-max_radius, max_radius + 1):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if self.soil_type[ny, nx] != "water":
                        return (nx, ny)
        return None
