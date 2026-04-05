"""
Mixin d'alimentation pour Individual.

Gère la recherche et la consommation de nourriture (_seek_food).
Fonctionne pour les herbivores (cibles : plantes), les carnivores
(cibles : autres individus) et les omnivores (les deux).
"""

import math

from entities.activity import TICKS_PER_SECOND


class FeedingMixin:

    def _seek_food(self, grid, all_plants, all_individuals):
        target    = None
        min_dist2 = self.species.perception_radius ** 2

        if self.species.type in ("herbivore", "omnivore"):
            for plant in all_plants:
                if not plant.alive or plant.species.name not in self.species.food_sources:
                    continue
                dx = plant.x - self.x
                dy = plant.y - self.y
                d2 = dx*dx + dy*dy
                if d2 < min_dist2:
                    min_dist2 = d2
                    target = plant

        if self.species.type in ("carnivore", "omnivore"):
            for other in all_individuals:
                if not other.alive or other is self:
                    continue
                if other.species.name not in self.species.food_sources:
                    continue
                dx = other.x - self.x
                dy = other.y - self.y
                d2 = dx*dx + dy*dy
                if d2 < min_dist2:
                    min_dist2 = d2
                    target = other

        if target is not None:
            dx = target.x - self.x
            dy = target.y - self.y
            dist = max(math.hypot(dx, dy), 0.01)
            step = self.species.speed / TICKS_PER_SECOND
            self.x += (dx / dist) * step
            self.y += (dy / dist) * step
            if dist < 1.5:
                target.alive = False
                self.energy = min(self.species.energy_start,
                                  self.energy + self.species.energy_from_food)
        else:
            self._wander(grid)
