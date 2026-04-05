"""
Objets mock partagés entre les fichiers de tests.
"""
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
    def __init__(self, soil_type="clay", temperature=20.0, humidity=0.5):
        self.soil_type = soil_type
        self.temperature = temperature
        self.humidity = humidity
        self.altitude = 0.5
        self.vegetation = []
        self.animals = []


class MockGrid:
    def __init__(self, width=50, height=50):
        self.width = width
        self.height = height
        self.cells = [
            [MockCell() for _ in range(width)]
            for _ in range(height)
        ]

    def get_cell(self, x: int, y: int) -> MockCell:
        return self.cells[y][x]
