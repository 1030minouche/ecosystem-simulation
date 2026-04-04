from dataclasses import dataclass, field
from entities.species import Species
import random
import math

TICKS_PER_SECOND = 50   # cadence cible pour le calcul de déplacement (inchangé)

# ── Rythme d'activité ──────────────────────────────────────────────────────────
# tod (time_of_day) ∈ [0, 1)
#   0.00 = minuit  |  0.25 = aube  |  0.50 = midi  |  0.75 = crépuscule

_PRE_REST_BUFFER = 0.06   # fenêtre de "recherche d'abri" avant le repos

def _is_resting(tod: float, pattern: str) -> bool:
    """True si l'individu devrait se reposer selon son rythme d'activité."""
    if pattern == "nocturnal":
        return 0.18 <= tod < 0.82          # dort le jour
    elif pattern == "crepuscular":
        # Actif à l'aube (0.18-0.38) et au crépuscule (0.62-0.82)
        # Repos en pleine nuit et en pleine journée
        return not ((0.18 <= tod < 0.38) or (0.62 <= tod < 0.82))
    else:  # diurnal
        return tod >= 0.82 or tod < 0.18   # dort la nuit

def _is_pre_rest(tod: float, pattern: str) -> bool:
    """True si l'individu entre dans sa phase de recherche d'abri."""
    if pattern == "diurnal":
        return (0.82 - _PRE_REST_BUFFER) <= tod < 0.82
    elif pattern == "nocturnal":
        return (0.18 - _PRE_REST_BUFFER) <= tod < 0.18
    elif pattern == "crepuscular":
        # Avant le repos de pleine journée et avant le repos de pleine nuit
        return ((0.38 - _PRE_REST_BUFFER) <= tod < 0.38 or
                (0.82 - _PRE_REST_BUFFER) <= tod < 0.82)
    return False


@dataclass
class Individual:
    species: Species
    x: float
    y: float
    age: int   = 0
    energy: float = 100.0
    alive: bool = True
    state: str = "wander"
    sex: str = "male"
    reproduction_cooldown: int = 0
    wander_angle: float = 0.0
    explore_x: float = -1.0
    explore_y: float = -1.0

    # Gestation : ticks restants avant la naissance + nombre de petits attendus
    gestation_timer: int = 0
    gestation_count: int = 0

    def tick(self, grid, all_plants, all_individuals, time_of_day: float = 0.5):
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
                # Cooldown de reproduction démarre après la mise bas
                self.reproduction_cooldown = self.species.reproduction_cooldown_length

        # ── Mortalité juvénile ───────────────────────────────────────────────
        if (self.species.juvenile_mortality_rate > 0
                and self.species.sexual_maturity_ticks > 0
                and self.age < self.species.sexual_maturity_ticks):
            if random.random() < self.species.juvenile_mortality_rate:
                self.death_cause    = "juvenile_mortality"
                self.death_tod      = time_of_day
                self.death_is_night = _is_resting(time_of_day, self.species.activity_pattern)
                self.death_on_water = False
                self.death_state    = self.state
                self.alive = False
                self.state = "dead"
                return newborns   # les bébés déjà nés ce tick sont quand même comptés

        resting = _is_resting(time_of_day, self.species.activity_pattern)

        # ── Consommation d'énergie ───────────────────────────────────────────
        if resting:
            self.energy -= self.species.energy_consumption * 0.3
        else:
            self.energy -= self.species.energy_consumption

        if self.age >= self.species.max_age or self.energy <= 0:
            self._annotate_death(grid, resting, time_of_day)
            self.alive = False
            self.state = "dead"
            return newborns

        self._check_environment(grid, resting)

        if self.energy <= 0:
            self._annotate_death(grid, resting, time_of_day)
            self.alive = False
            self.state = "dead"
            return newborns

        predator = self._nearest_predator(all_individuals, time_of_day)

        if resting and predator is None:
            self.state = "sleep"
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
            self._seek_food(grid, all_plants, all_individuals)
        elif self.state == "flee":
            self._flee(predator)
        elif self.state == "reproduce":
            newborns.extend(self._try_reproduce(all_individuals, grid))
        else:
            self._wander(grid)

        self.x = max(0, min(grid.width  - 1, self.x))
        self.y = max(0, min(grid.height - 1, self.y))

        if not self.species.can_swim:
            self._avoid_water(grid)

        return newborns

    # ── Délivrance des petits (fin de gestation) ──────────────────────────────

    def _deliver(self, grid) -> list:
        babies = []
        for _ in range(self.gestation_count):
            bx = self.x + random.uniform(-2, 2)
            by = self.y + random.uniform(-2, 2)
            if not self.species.can_swim:
                ibx, iby = int(bx), int(by)
                if (0 <= ibx < grid.width and 0 <= iby < grid.height
                        and grid.cells[iby][ibx].soil_type == "water"):
                    bx, by = self.x, self.y
            babies.append(Individual(
                species=self.species,
                x=bx, y=by,
                energy=self.species.energy_start * 0.5,
                sex=random.choice(["male", "female"]),
                wander_angle=random.uniform(0, 2 * math.pi),
            ))
        self.gestation_count = 0
        return babies

    # ── Environnement ─────────────────────────────────────────────────────────

    def _check_environment(self, grid, resting: bool = False):
        cx, cy = int(self.x), int(self.y)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return
        cell = grid.cells[cy][cx]
        dmg = self.species.energy_consumption * 12.5 * (0.3 if resting else 1.0)
        if not (self.species.temp_min <= cell.temperature <= self.species.temp_max):
            self.energy -= dmg
        if cell.soil_type == "water" and not self.species.can_swim:
            self.energy -= dmg

    # ── Machine à états ───────────────────────────────────────────────────────

    def _update_state(self, predator):
        if predator is not None:
            self.state = "flee"
            return
        if self.energy < self.species.energy_start * 0.60:
            self.state = "seek_food"
            return
        # Reproduction impossible si immature ou en gestation
        mature = (self.species.sexual_maturity_ticks == 0
                  or self.age >= self.species.sexual_maturity_ticks)
        if (mature
                and self.gestation_timer == 0
                and self.energy > self.species.energy_start * 0.75
                and self.reproduction_cooldown == 0):
            self.state = "reproduce"
            return
        self.state = "wander"

    # ── Déplacement ───────────────────────────────────────────────────────────

    def _wander(self, grid, speed_factor: float = 1.0):
        dx = self.explore_x - self.x
        dy = self.explore_y - self.y

        need_new = self.explore_x < 0 or (dx*dx + dy*dy) < 4.0
        if not need_new and not self.species.can_swim:
            tx, ty = int(self.explore_x), int(self.explore_y)
            if (0 <= tx < grid.width and 0 <= ty < grid.height
                    and grid.cells[ty][tx].soil_type == "water"):
                need_new = True

        if need_new:
            if self.species.can_swim:
                self.explore_x = random.uniform(2, grid.width  - 3)
                self.explore_y = random.uniform(2, grid.height - 3)
            else:
                for _ in range(15):
                    ex = random.uniform(2, grid.width  - 3)
                    ey = random.uniform(2, grid.height - 3)
                    if grid.cells[int(ey)][int(ex)].soil_type != "water":
                        self.explore_x, self.explore_y = ex, ey
                        break
                else:
                    self.explore_x = random.uniform(2, grid.width  - 3)
                    self.explore_y = random.uniform(2, grid.height - 3)
            dx = self.explore_x - self.x
            dy = self.explore_y - self.y

        target_angle = math.atan2(dy, dx)
        angle_diff = (target_angle - self.wander_angle + math.pi) % (2 * math.pi) - math.pi
        self.wander_angle += angle_diff * 0.3 + random.uniform(-0.15, 0.15)
        step = self.species.speed / TICKS_PER_SECOND * speed_factor
        self.x += math.cos(self.wander_angle) * step
        self.y += math.sin(self.wander_angle) * step

    def _avoid_water(self, grid):
        cx, cy = int(self.x), int(self.y)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return
        if grid.cells[cy][cx].soil_type != "water":
            return
        best_x, best_y, best_d2 = -1, -1, float("inf")
        for dy in range(-12, 13):
            for dx in range(-12, 13):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < grid.width and 0 <= ny < grid.height):
                    continue
                if grid.cells[ny][nx].soil_type == "water":
                    continue
                d2 = dx*dx + dy*dy
                if d2 < best_d2:
                    best_d2 = d2
                    best_x, best_y = nx, ny
        if best_x < 0:
            return
        ddx = best_x - self.x
        ddy = best_y - self.y
        dist = max(math.hypot(ddx, ddy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND * 2.0
        self.x += (ddx / dist) * step
        self.y += (ddy / dist) * step
        self.explore_x = -1.0

    # ── Mort ─────────────────────────────────────────────────────────────────

    def _annotate_death(self, grid, resting: bool, time_of_day: float) -> None:
        cx, cy   = int(self.x), int(self.y)
        on_water = (0 <= cx < grid.width and 0 <= cy < grid.height
                    and grid.cells[cy][cx].soil_type == "water")
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
        self.death_cause    = cause
        self.death_tod      = time_of_day
        self.death_is_night = resting
        self.death_on_water = on_water
        self.death_state    = self.state

    # ── Abri ─────────────────────────────────────────────────────────────────

    def _seek_shelter(self, grid):
        self.state = "seek_shelter"
        cx, cy = int(self.x), int(self.y)
        if (0 <= cx < grid.width and 0 <= cy < grid.height
                and grid.cells[cy][cx].soil_type != "water"):
            return
        best_x, best_y, best_dist2 = -1, -1, float("inf")
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < grid.width and 0 <= ny < grid.height):
                    continue
                if grid.cells[ny][nx].soil_type == "water":
                    continue
                d2 = dx*dx + dy*dy
                if d2 < best_dist2:
                    best_dist2 = d2
                    best_x, best_y = nx, ny
        if best_x >= 0:
            ddx = best_x - self.x
            ddy = best_y - self.y
            dist = max(math.hypot(ddx, ddy), 0.01)
            step = self.species.speed / TICKS_PER_SECOND
            self.x += (ddx / dist) * step
            self.y += (ddy / dist) * step

    # ── Prédateur le plus proche ──────────────────────────────────────────────

    def _nearest_predator(self, all_individuals, time_of_day: float):
        nearest       = None
        nearest_dist2 = self.species.perception_radius ** 2
        for other in all_individuals:
            if not other.alive or other is self:
                continue
            if _is_resting(time_of_day, other.species.activity_pattern):
                continue
            if self.species.name not in other.species.food_sources:
                continue
            dx = other.x - self.x
            dy = other.y - self.y
            dist2 = dx*dx + dy*dy
            if dist2 < nearest_dist2:
                nearest_dist2 = dist2
                nearest = other
        return nearest

    # ── Fuite ─────────────────────────────────────────────────────────────────

    def _flee(self, predator):
        dx = self.x - predator.x
        dy = self.y - predator.y
        dist = max(math.hypot(dx, dy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND * 1.2
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step

    # ── Alimentation ─────────────────────────────────────────────────────────

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

    # ── Reproduction ──────────────────────────────────────────────────────────

    def _try_reproduce(self, all_individuals, grid) -> list:
        # Trouver un partenaire compatible
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
            # Partenaire doit aussi être mature
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
            n_pred = sum(
                1 for other in all_individuals
                if other.alive
                and self.species.name in other.species.food_sources
                and math.hypot(other.x - self.x, other.y - self.y) < self.species.perception_radius
            )
            if n_pred > 0:
                effective_rate /= (1.0 + self.species.fear_factor * n_pred)

        if random.random() >= effective_rate:
            return []

        # ── Fécondation ────────────────────────────────────────────────────
        litter = random.randint(self.species.litter_size_min,
                                self.species.litter_size_max)

        # Coût énergétique de la reproduction pour les deux parents
        cost = self.species.energy_start * 0.20
        self.energy          -= cost
        nearest_partner.energy -= cost

        if self.species.gestation_ticks > 0:
            # Gestation : les bébés naîtront plus tard
            # (seul l'individu qui déclenche _try_reproduce porte la gestation)
            self.gestation_timer = self.species.gestation_ticks
            self.gestation_count = litter
            # Le partenaire a un cooldown immédiat pour éviter double-fécondation
            nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
            return []
        else:
            # Naissance instantanée (plantes, espèces sans gestation)
            newborns = []
            for _ in range(litter):
                bx = self.x + random.uniform(-1, 1)
                by = self.y + random.uniform(-1, 1)
                if not self.species.can_swim:
                    ibx, iby = int(bx), int(by)
                    if (0 <= ibx < grid.width and 0 <= iby < grid.height
                            and grid.cells[iby][ibx].soil_type == "water"):
                        bx, by = self.x, self.y
                newborns.append(Individual(
                    species=self.species,
                    x=bx, y=by,
                    energy=self.species.energy_start * 0.6,
                    sex=random.choice(["male", "female"]),
                    wander_angle=random.uniform(0, 2 * math.pi),
                ))
            self.reproduction_cooldown          = self.species.reproduction_cooldown_length
            nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
            return newborns
