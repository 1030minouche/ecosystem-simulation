"""
Mixin de déplacement pour Individual.

Regroupe toutes les méthodes liées au mouvement :
  - _wander       : exploration aléatoire avec cible
  - _avoid_water  : correction de position hors eau
  - _flee         : fuite face à un prédateur
  - _seek_shelter : recherche d'abri avant le repos
"""

import math
import random

from entities.activity import TICKS_PER_SECOND


class MovementMixin:

    # ── Exploration ───────────────────────────────────────────────────────────

    def _wander(self, grid, speed_factor: float = 1.0, herd_centroid=None):
        dx = self.explore_x - self.x
        dy = self.explore_y - self.y

        flies = self.species.type == "volant"

        need_new = self.explore_x < 0 or (dx*dx + dy*dy) < 4.0
        if not need_new and not self.species.can_swim and not flies:
            tx, ty = int(self.explore_x), int(self.explore_y)
            if (0 <= tx < grid.width and 0 <= ty < grid.height
                    and grid.cells[ty][tx].soil_type == "water"):
                need_new = True

        if need_new:
            if self.species.can_swim or flies:
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

        # ── Cohésion de troupeau ──────────────────────────────────────────────
        # Biaise la cible d'exploration vers le centroïde pré-calculé par le moteur.
        if herd_centroid is not None and self.species.herd_cohesion > 0:
            c = self.species.herd_cohesion
            self.explore_x = (1.0 - c) * self.explore_x + c * herd_centroid[0]
            self.explore_y = (1.0 - c) * self.explore_y + c * herd_centroid[1]

        dx = self.explore_x - self.x
        dy = self.explore_y - self.y
        target_angle = math.atan2(dy, dx)
        angle_diff = (target_angle - self.wander_angle + math.pi) % (2 * math.pi) - math.pi
        self.wander_angle += angle_diff * 0.3 + random.uniform(-0.15, 0.15)
        # Les volants en vol bénéficient d'un bonus de vitesse (+40%)
        air_bonus = 1.4 if self.species.type == "volant" and self.state == "en_vol" else 1.0
        step = self.species.speed / TICKS_PER_SECOND * speed_factor * air_bonus
        self.x += math.cos(self.wander_angle) * step
        self.y += math.sin(self.wander_angle) * step

    # ── Évitement de l'eau ────────────────────────────────────────────────────

    def _avoid_water(self, grid):
        cx, cy = int(self.x), int(self.y)
        if not (0 <= cx < grid.width and 0 <= cy < grid.height):
            return
        if grid.cells[cy][cx].soil_type != "water":
            return
        result = grid.nearest_non_water(cx, cy, 12)
        if result is None:
            return
        best_x, best_y = result
        ddx = best_x - self.x
        ddy = best_y - self.y
        dist = max(math.hypot(ddx, ddy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND * 2.0
        self.x += (ddx / dist) * step
        self.y += (ddy / dist) * step
        self.explore_x = -1.0

    # ── Fuite ─────────────────────────────────────────────────────────────────

    def _flee(self, predator):
        dx = self.x - predator.x
        dy = self.y - predator.y
        dist = max(math.hypot(dx, dy), 0.01)
        step = self.species.speed / TICKS_PER_SECOND * 1.2
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step

    # ── Recherche d'abri ──────────────────────────────────────────────────────

    def _seek_shelter(self, grid):
        self.state = "seek_shelter"
        cx, cy = int(self.x), int(self.y)
        if (0 <= cx < grid.width and 0 <= cy < grid.height
                and grid.cells[cy][cx].soil_type != "water"):
            return
        result = grid.nearest_non_water(cx, cy, 8)
        if result is not None:
            best_x, best_y = result
            ddx = best_x - self.x
            ddy = best_y - self.y
            dist = max(math.hypot(ddx, ddy), 0.01)
            step = self.species.speed / TICKS_PER_SECOND
            self.x += (ddx / dist) * step
            self.y += (ddy / dist) * step
