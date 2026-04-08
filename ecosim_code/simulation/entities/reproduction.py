"""
Mixin de reproduction pour Individual.

Gère la recherche d'un partenaire, la fécondation, la gestation
et la mise bas (_try_reproduce, _deliver).

Note : les nouveau-nés sont créés via type(self)(...) pour éviter
un import circulaire avec entities.animal.
"""

import math
import random

from entities.activity import TICKS_PER_SECOND
from entities.species import blend_species


class ReproductionMixin:

    # ── Délivrance des petits (fin de gestation) ──────────────────────────────

    def _deliver(self, grid) -> list:
        baby_sp = self.gestation_species or self.species
        babies = []
        for _ in range(self.gestation_count):
            bx = self.x + random.uniform(-2, 2)
            by = self.y + random.uniform(-2, 2)
            if not self.species.can_swim:
                ibx, iby = int(bx), int(by)
                if (0 <= ibx < grid.width and 0 <= iby < grid.height
                        and grid.cells[iby][ibx].soil_type == "water"):
                    bx, by = self.x, self.y
            babies.append(type(self)(
                species=baby_sp,
                x=bx, y=by,
                energy=baby_sp.energy_start * 0.5,
                sex=random.choice(["male", "female"]),
                wander_angle=random.uniform(0, 2 * math.pi),
                home_x=bx, home_y=by,
            ))
        self.gestation_count   = 0
        self.gestation_species = None
        return babies

    # ── Tentative de reproduction ─────────────────────────────────────────────

    def _try_reproduce(self, all_individuals, grid) -> list:
        nearest_partner = None
        min_dist2 = (self.species.perception_radius * 3.0) ** 2

        for other in all_individuals:
            if not other.alive or other is self:
                continue
            if other.species.name != self.species.name:
                continue
            if other.sex == self.sex:
                continue
            if other.reproduction_cooldown > 0 or other.gestation_timer > 0:
                continue
            # Le partenaire doit aussi être mature
            if (self.species.sexual_maturity_ticks > 0
                    and other.age < self.species.sexual_maturity_ticks):
                continue
            dx = other.x - self.x
            dy = other.y - self.y
            d2 = dx*dx + dy*dy
            if d2 < min_dist2:
                min_dist2 = d2
                nearest_partner = other

        if nearest_partner is None:
            self._wander(grid)
            return []

        # Se déplacer vers le partenaire
        dx   = nearest_partner.x - self.x
        dy   = nearest_partner.y - self.y
        dist = max(math.hypot(dx, dy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step

        if dist >= self.species.perception_radius * 1.5:
            return []

        # ── Effet de peur sur la reproduction ──────────────────────────────
        effective_rate = self.species.reproduction_rate
        if self.species.fear_factor > 0:
            r2 = self.species.perception_radius ** 2
            n_pred = sum(
                1 for other in all_individuals
                if other.alive
                and self.species.name in other.species.food_sources
                and (other.x - self.x) ** 2 + (other.y - self.y) ** 2 < r2
            )
            if n_pred > 0:
                effective_rate /= (1.0 + self.species.fear_factor * n_pred)

        if random.random() >= effective_rate:
            return []

        # ── Fécondation ────────────────────────────────────────────────────
        litter = random.randint(self.species.litter_size_min,
                                self.species.litter_size_max)

        # Coût énergétique pour les deux parents
        cost = self.species.energy_start * 0.20
        self.energy              -= cost
        nearest_partner.energy   -= cost

        # Params du bébé = moyenne des deux parents + légère mutation
        baby_sp = blend_species(self.species, nearest_partner.species,
                                mutation_rate=self.species.mutation_rate)

        if self.species.gestation_ticks > 0:
            # Gestation différée : les bébés naîtront plus tard
            self.gestation_timer   = self.species.gestation_ticks
            self.gestation_count   = litter
            self.gestation_species = baby_sp
            nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
            return []
        else:
            # Naissance instantanée
            newborns = []
            for _ in range(litter):
                bx = self.x + random.uniform(-1, 1)
                by = self.y + random.uniform(-1, 1)
                if not self.species.can_swim:
                    ibx, iby = int(bx), int(by)
                    if (0 <= ibx < grid.width and 0 <= iby < grid.height
                            and grid.cells[iby][ibx].soil_type == "water"):
                        bx, by = self.x, self.y
                newborns.append(type(self)(
                    species=baby_sp,
                    x=bx, y=by,
                    energy=baby_sp.energy_start * 0.6,
                    sex=random.choice(["male", "female"]),
                    wander_angle=random.uniform(0, 2 * math.pi),
                    home_x=bx, home_y=by,
                ))
            self.reproduction_cooldown            = self.species.reproduction_cooldown_length
            nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
            return newborns
