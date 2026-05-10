from dataclasses import dataclass
from entities.base import Entity
from entities.rng import rng
import math

@dataclass
class Plant(Entity):
    growth: float = 0.1   # taux de croissance courant [0, 1]

    def tick(self, grid, plant_count: int, season: float = 0.0):
        """
        plant_count : nombre total de plantes vivantes (pour limiter max_population).
        season      : facteur saisonnier [-1, 1] (été > 0, hiver < 0).
        """
        if not self.alive:
            return []

        self.age += 1
        if self.reproduction_cooldown > 0:
            self.reproduction_cooldown -= 1
        cx, cy = int(self.x), int(self.y)
        newborns = []

        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            self.alive = False
            return []

        temp     = float(grid.temperature[cy, cx])
        humidity = float(grid.humidity[cy, cx])
        stype    = grid.soil_type[cy, cx]

        # Saisonnalité : la croissance est boostée en été (+30%), freinée en hiver (-30%)
        seasonal_growth = self.species.growth_rate * (1.0 + 0.30 * season)
        nutrient = float(grid.nutrients[cy, cx]) if hasattr(grid, "nutrients") else 1.0
        if (self.species.temp_min <= temp <= self.species.temp_max and
                self.species.humidity_min <= humidity <= self.species.humidity_max and
                stype != "water"):
            # Nutriments : limitent la croissance et sont consommés
            nut_factor = 0.5 + 0.5 * nutrient
            self.growth = min(1.0, self.growth + max(0.0, seasonal_growth * nut_factor))
            self.energy += 0.05 * (1.0 + 0.20 * season) * nut_factor
            if hasattr(grid, "nutrients"):
                grid.nutrients[cy, cx] = max(0.0, nutrient - 0.00005)
        else:
            self.growth = max(0.0, self.growth - 0.000060)
            self.energy -= 0.025

        if self.growth <= 0.0 or self.age >= self.species.max_age or self.energy <= 0:
            # La plante morte enrichit le sol en nutriments (décomposition)
            if hasattr(grid, "nutrients"):
                grid.nutrients[cy, cx] = min(1.0, nutrient + 0.002)
            self.alive = False
            return []

        if (self.growth > 0.8
                and self.reproduction_cooldown == 0
                and rng.random() < self.species.reproduction_rate
                and plant_count < self.species.max_population):
            angle  = rng.uniform(0, 2 * math.pi)
            radius = rng.uniform(1, self.species.dispersal_radius)
            nx = int(self.x + math.cos(angle) * radius)
            ny = int(self.y + math.sin(angle) * radius)

            if (0 <= nx < grid.width and 0 <= ny < grid.height
                    and grid.soil_type[ny, nx] != "water"):
                newborns.append(Plant(species=self.species, x=nx, y=ny))
                self.reproduction_cooldown = self.species.reproduction_cooldown_length

        return newborns
