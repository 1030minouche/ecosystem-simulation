"""
Mixin d'alimentation pour Individual.

Gère la recherche et la consommation de nourriture (_seek_food).
Fonctionne pour les herbivores (cibles : plantes), les carnivores
(cibles : autres individus) et les omnivores (les deux).
"""

import math
import random

from entities.activity import TICKS_PER_SECOND, _is_resting
from entities.death import mark_dead


class FeedingMixin:

    def _seek_food(self, grid, all_plants, all_individuals, time_of_day: float = 0.5):
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

        if self.species.type in ("carnivore", "omnivore", "volant"):
            for other in all_individuals:
                if not other.alive or other is self:
                    continue
                if other.species.name not in self.species.food_sources:
                    continue
                # Un volant en vol ne peut être attrapé que par un autre volant
                if other.species.type == "volant" and other.state == "en_vol":
                    if self.species.type != "volant":
                        continue
                dx = other.x - self.x
                dy = other.y - self.y
                d2 = dx*dx + dy*dy
                if d2 < min_dist2:
                    min_dist2 = d2
                    target = other

        if target is None:
            self._wander(grid)
            return

        dx = target.x - self.x
        dy = target.y - self.y
        dist = max(math.hypot(dx, dy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step

        if dist >= 1.5:
            return

        # ── Protection territoriale ────────────────────────────────────────────
        caught = True
        if (hasattr(target, "home_x") and target.home_x >= 0
                and target.species.territory_radius > 0
                and target.species.home_protection > 0):
            dhx = target.x - target.home_x
            dhy = target.y - target.home_y
            if dhx * dhx + dhy * dhy <= target.species.territory_radius ** 2:
                if random.random() < target.species.home_protection:
                    caught = False

        if not caught:
            return

        # ── Mort de la proie — métadonnées pour le DeathLogger ────────────────
        mark_dead(target, "predation", grid, time_of_day,
                  is_night=_is_resting(time_of_day, target.species.activity_pattern))

        self.energy = min(self.species.energy_start,
                          self.energy + self.species.energy_from_food)
