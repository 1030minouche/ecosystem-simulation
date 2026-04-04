from dataclasses import dataclass
from entities.species import Species
import random
import math

@dataclass
class Plant:
    species: Species
    x: int
    y: int
    age: int = 0
    energy: float = 100.0
    alive: bool = True
    growth: float = 0.1
    reproduction_cooldown: int = 0   # ticks restants avant la prochaine reproduction 

    def tick(self, grid, plant_count: int):
        """
        plant_count : nombre total de plantes vivantes (pour limiter max_population).
        Passer un int évite de passer toute la liste juste pour un len().
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

        cell = grid.cells[cy][cx]

        if (self.species.temp_min <= cell.temperature <= self.species.temp_max and
                self.species.humidity_min <= cell.humidity <= self.species.humidity_max and
                cell.soil_type != "water"):
            self.growth = min(1.0, self.growth + self.species.growth_rate)
            self.energy += 0.05
        else:
            self.growth = max(0.0, self.growth - 0.000060)
            self.energy -= 0.025

        if self.growth <= 0.0 or self.age >= self.species.max_age or self.energy <= 0:
            self.alive = False
            return []

        if (self.growth > 0.8
                and self.reproduction_cooldown == 0
                and random.random() < self.species.reproduction_rate
                and plant_count < self.species.max_population):
            angle  = random.uniform(0, 2 * math.pi)
            radius = random.uniform(1, self.species.dispersal_radius)
            nx = int(self.x + math.cos(angle) * radius)
            ny = int(self.y + math.sin(angle) * radius)

            if (0 <= nx < grid.width and 0 <= ny < grid.height
                    and grid.cells[ny][nx].soil_type != "water"):
                newborns.append(Plant(species=self.species, x=nx, y=ny))
                self.reproduction_cooldown = self.species.reproduction_cooldown_length

        return newborns
