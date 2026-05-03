"""
Entité animale (Individual).

La classe Individual hérite de trois mixins qui séparent les responsabilités :
  - MovementMixin     (entities/movement.py)     : déplacement
  - FeedingMixin      (entities/feeding.py)       : alimentation
  - ReproductionMixin (entities/reproduction.py)  : reproduction & gestation

Ce fichier conserve :
  - la définition du dataclass Individual
  - la boucle de vie principale (tick)
  - la machine à états (_update_state)
  - la gestion de l'environnement et de la mort

Les fonctions _is_resting et _is_pre_rest sont ré-exportées depuis
entities.activity pour rester importables depuis ce module (compatibilité
avec les tests existants).
"""

from dataclasses import dataclass, field
from entities.base import Entity
from entities.activity import _is_resting, _is_pre_rest  # noqa: F401 — ré-export
from entities.movement import MovementMixin
from entities.feeding import FeedingMixin
from entities.reproduction import ReproductionMixin
from entities.death import mark_dead
from entities.rng import rng


@dataclass
class Individual(MovementMixin, FeedingMixin, ReproductionMixin, Entity):
    state: str = "wander"
    sex: str = "male"
    wander_angle: float = 0.0
    explore_x: float = -1.0
    explore_y: float = -1.0

    # Gestation : ticks restants avant la naissance + nombre de petits attendus
    gestation_timer: int = 0
    gestation_count: int = 0
    gestation_species: object = None  # Species pré-calculé au moment de la fécondation

    # Territoire natal (-1 = non défini)
    home_x: float = -1.0
    home_y: float = -1.0

    # Généalogie : ID Python de la mère (-1 = fondateur, spawn initial)
    parent_id: int = -1

    # ── Boucle de vie ─────────────────────────────────────────────────────────

    def tick(self, grid, all_plants, all_individuals, time_of_day: float = 0.5,
             herd_centroids: dict = None, all_individuals_repro: list | None = None):
        if not self.alive:
            return []

        self.age += 1
        if self.reproduction_cooldown > 0:
            self.reproduction_cooldown -= 1

        newborns = []

        # ── Gestation : décompte + naissance à terme ────────────────────────
        if self.gestation_timer > 0:
            self.gestation_timer -= 1
            if self.gestation_timer == 0 and self.gestation_count > 0:
                newborns.extend(self._deliver(grid))
                self.reproduction_cooldown = self.species.reproduction_cooldown_length

        # ── Mortalité juvénile ───────────────────────────────────────────────
        if (self.species.juvenile_mortality_rate > 0
                and self.species.sexual_maturity_ticks > 0
                and self.age < self.species.sexual_maturity_ticks):
            if rng.random() < self.species.juvenile_mortality_rate:
                mark_dead(self, "juvenile_mortality", grid, time_of_day,
                          is_night=_is_resting(time_of_day, self.species.activity_pattern))
                return newborns

        resting = _is_resting(time_of_day, self.species.activity_pattern)

        # ── Consommation d'énergie ───────────────────────────────────────────
        if resting:
            self.energy -= self.species.energy_consumption * 0.3
        else:
            self.energy -= self.species.energy_consumption

        if self.age >= self.species.max_age or self.energy <= 0:
            self._annotate_death(grid, resting, time_of_day)
            return newborns

        self._check_environment(grid, resting)

        if self.energy <= 0:
            self._annotate_death(grid, resting, time_of_day)
            return newborns

        predator, n_predators = self._nearest_predator(all_individuals, time_of_day)

        if resting and predator is None:
            self.state = "au_sol" if self.species.is_flying() else "sleep"
            self._wander(grid, speed_factor=0.25)
            self.x = max(0, min(grid.width  - 1, self.x))
            self.y = max(0, min(grid.height - 1, self.y))
            return newborns

        if predator is None and _is_pre_rest(time_of_day, self.species.activity_pattern):
            self._seek_shelter(grid)
            self.x = max(0, min(grid.width  - 1, self.x))
            self.y = max(0, min(grid.height - 1, self.y))
            return newborns

        self._update_state(predator)

        if self.state == "seek_food":
            self._seek_food(grid, all_plants, all_individuals, time_of_day)
        elif self.state == "flee":
            self._flee(predator)
        elif self.state == "reproduce":
            repro_list = all_individuals_repro if all_individuals_repro is not None else all_individuals
            newborns.extend(self._try_reproduce(repro_list, grid, n_predators=n_predators))
        else:  # "wander", "en_vol"
            centroid = herd_centroids.get(self.species.name) if herd_centroids else None
            self._wander(grid, herd_centroid=centroid)

        self.x = max(0, min(grid.width  - 1, self.x))
        self.y = max(0, min(grid.height - 1, self.y))

        # Les volants en vol ne sont pas bloqués par l'eau
        if not self.species.can_swim and not self.species.is_flying():
            self._avoid_water(grid)

        return newborns

    # ── Machine à états ───────────────────────────────────────────────────────

    def _update_state(self, predator):
        if predator is not None:
            self.state = "flee"
            return
        if self.energy < self.species.energy_start * 0.60:
            self.state = "seek_food"
            return
        mature = (self.species.sexual_maturity_ticks == 0
                  or self.age >= self.species.sexual_maturity_ticks)
        if (mature
                and self.gestation_timer == 0
                and self.energy > self.species.energy_start * 0.75
                and self.reproduction_cooldown == 0):
            self.state = "reproduce"
            return
        # Volants : en vol quand ils errent, au sol quand ils dorment
        self.state = "en_vol" if self.species.is_flying() else "wander"

    # ── Environnement ─────────────────────────────────────────────────────────

    def _check_environment(self, grid, resting: bool = False):
        cx, cy = int(self.x), int(self.y)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return
        dmg  = self.species.energy_consumption * 12.5 * (0.3 if resting else 1.0)
        temp = float(grid.temperature[cy, cx])
        if not (self.species.temp_min <= temp <= self.species.temp_max):
            self.energy -= dmg
        if grid.soil_type[cy, cx] == "water" and not self.species.can_swim:
            self.energy -= dmg
        if (self.species.altitude_min != 0.0 or self.species.altitude_max != 1.0):
            alt = float(grid.altitude[cy, cx])
            if not (self.species.altitude_min <= alt <= self.species.altitude_max):
                self.energy -= dmg
        humidity = float(grid.humidity[cy, cx])
        if not (self.species.humidity_min <= humidity <= self.species.humidity_max):
            self.energy -= dmg * 0.5

    # ── Prédateur le plus proche ──────────────────────────────────────────────

    def _nearest_predator(self, all_individuals, time_of_day: float) -> tuple:
        """Retourne (prédateur_le_plus_proche | None, nombre_de_prédateurs_perçus)."""
        nearest       = None
        nearest_dist2 = self.species.perception_radius ** 2
        r2            = nearest_dist2
        count         = 0
        for other in all_individuals:
            if not other.alive or other is self:
                continue
            if _is_resting(time_of_day, other.species.activity_pattern):
                continue
            if self.species.name not in other.species.food_sources:
                continue
            dx    = other.x - self.x
            dy    = other.y - self.y
            dist2 = dx*dx + dy*dy
            if dist2 < r2:
                count += 1
                if dist2 < nearest_dist2:
                    nearest_dist2 = dist2
                    nearest = other
        return nearest, count

    # ── Mort ─────────────────────────────────────────────────────────────────

    def _annotate_death(self, grid, resting: bool, time_of_day: float) -> None:
        cx, cy   = int(self.x), int(self.y)
        on_water = (0 <= cx < grid.width and 0 <= cy < grid.height
                    and grid.soil_type[cy, cx] == "water")
        if self.age >= self.species.max_age:
            cause = "vieillesse"
        elif on_water and resting:
            cause = "eau_nuit"
        elif on_water:
            cause = "eau_jour"
        elif resting:
            cause = "famine_nuit"
        else:
            cause = "famine_jour"
        mark_dead(self, cause, grid, time_of_day, is_night=resting)
