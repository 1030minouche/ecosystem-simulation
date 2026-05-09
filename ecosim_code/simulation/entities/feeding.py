"""
Mixin d'alimentation pour Individual.

Gère la recherche et la consommation de nourriture (_seek_food).
Fonctionne pour les herbivores (cibles : plantes), les carnivores
(cibles : autres individus) et les omnivores (les deux).
"""

import math

from entities.activity import TICKS_PER_SECOND, _is_resting
from entities.rng import rng
from entities.death import mark_dead


def _maybe_food_disease(individual) -> None:
    """Tente une contamination par voie alimentaire après un repas réussi."""
    chance = getattr(individual.species, "food_disease_chance", 0.0)
    if not chance:
        return
    from entities.disease import DISEASE_REGISTRY, DiseaseState
    if not DISEASE_REGISTRY:
        return
    if rng.random() >= chance:
        return
    name_lower = individual.species.name.lower()
    candidates = [
        s for s in DISEASE_REGISTRY.values()
        if not s.affects_species or name_lower in {a.lower() for a in s.affects_species}
    ]
    if not candidates:
        return
    spec = candidates[rng.randint(0, len(candidates) - 1)]
    existing = individual.disease_states.get(spec.name)
    if existing and existing.status != "susceptible":
        return
    individual.disease_states[spec.name] = DiseaseState(
        disease_name=spec.name,
        status="exposed",
        source_id=-1,
    )


class FeedingMixin:

    def _seek_food(self, grid, all_plants, all_individuals, time_of_day: float = 0.5):
        target    = None
        min_dist2 = self.species.perception_radius ** 2

        if self.species.can_eat_plants():
            for plant in all_plants:
                if not plant.alive or plant.species.name not in self.species.food_sources:
                    continue
                dx = plant.x - self.x
                dy = plant.y - self.y
                d2 = dx*dx + dy*dy
                if d2 < min_dist2:
                    min_dist2 = d2
                    target = plant

        if self.species.can_eat_animals():
            for other in all_individuals:
                if not other.alive or other is self:
                    continue
                if other.species.name not in self.species.food_sources:
                    continue
                # Un volant en vol ne peut être attrapé que par un autre volant
                if other.species.is_flying() and other.state == "en_vol":
                    if not self.species.is_flying():
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
                if rng.random() < target.species.home_protection:
                    caught = False

        if not caught:
            return

        # ── Consommation incrémentale ─────────────────────────────────────────
        # Une morsure prélève bite_size × energy_start de la cible.
        # La cible peut survivre et nourrir plusieurs prédateurs.
        tgt_start = max(target.species.energy_start, 1e-6)
        bite = min(target.energy, self.species.bite_size * tgt_start)
        gain = bite * (self.species.energy_from_food / tgt_start)
        target.energy -= bite
        self.energy = min(self.species.energy_start, self.energy + gain)
        if target.energy <= 0:
            mark_dead(target, "predation", grid, time_of_day,
                      is_night=_is_resting(time_of_day, target.species.activity_pattern))

        # Contamination alimentaire : chance d'attraper une maladie en mangeant
        _maybe_food_disease(self)
