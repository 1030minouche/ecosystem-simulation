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


def _spawn_offspring(parent, grid, species, energy_factor: float = 0.5,
                     spread: float = 2.0) -> object:
    """Crée un nouveau-né près du parent avec fallback hors eau."""
    bx = parent.x + random.uniform(-spread, spread)
    by = parent.y + random.uniform(-spread, spread)
    if not parent.species.can_swim:
        ibx, iby = int(bx), int(by)
        if (0 <= ibx < grid.width and 0 <= iby < grid.height
                and grid.soil_type[iby, ibx] == "water"):
            bx, by = parent.x, parent.y
    return type(parent)(
        species=species,
        x=bx, y=by,
        energy=species.energy_start * energy_factor,
        sex=random.choice(["male", "female"]),
        wander_angle=random.uniform(0, 2 * math.pi),
        home_x=bx, home_y=by,
        parent_id=id(parent),
    )


class ReproductionMixin:

    # ── Délivrance des petits (fin de gestation) ──────────────────────────────

    def _deliver(self, grid) -> list:
        baby_sp = self.gestation_species or self.species
        babies = [_spawn_offspring(self, grid, baby_sp, energy_factor=0.5, spread=2.0)
                  for _ in range(self.gestation_count)]
        self.gestation_count   = 0
        self.gestation_species = None
        return babies

    # ── Tentative de reproduction ─────────────────────────────────────────────

    def _try_reproduce(self, all_individuals, grid, n_predators: int = 0) -> list:
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
        # n_predators est fourni par _nearest_predator pour éviter un double parcours.
        effective_rate = self.species.reproduction_rate
        if self.species.fear_factor > 0 and n_predators > 0:
            effective_rate /= (1.0 + self.species.fear_factor * n_predators)

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
            newborns = [_spawn_offspring(self, grid, baby_sp, energy_factor=0.6, spread=1.0)
                        for _ in range(litter)]
            self.reproduction_cooldown            = self.species.reproduction_cooldown_length
            nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
            return newborns
