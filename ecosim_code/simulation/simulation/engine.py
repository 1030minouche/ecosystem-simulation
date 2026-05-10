"""
SimulationEngine — façade qui agrège EngineCore, SpeciesRegistry et Snapshotter.

Toutes les méthodes publiques historiques restent disponibles pour la
compatibilité ascendante. Les implémentations vivent dans :
  - simulation/species_registry.py  (spawn, comptage, extinction)
  - simulation/snapshotter.py       (snapshots WebSocket, rapport)
"""

import threading
import time as _time
from world.grid import Grid
from world.spatial_grid import SpatialGrid
from monitoring.report import SimulationReport
from monitoring.logger import SimulationLogger
from monitoring.death_log import DeathLogger
from simulation.utils.counting import count_by_species
from simulation.species_registry import SpeciesRegistry
from simulation.snapshotter import Snapshotter
from simulation.snapshot_view import SimulationSnapshot, EntityView
from simulation.engine_const import DAY_LENGTH, SIM_YEAR
import entities.rng as _entity_rng_module
import math as _math


class SimulationEngine:
    def __init__(self, grid: Grid, seed: int | None = None):
        _entity_rng_module.rng.reset(seed)
        self.seed       = seed
        # Réinitialise le compteur UID pour que chaque simulation commence à 1
        from entities.animal import Individual
        Individual._uid_counter = 0
        self.grid       = grid
        self.running    = False
        self.tick_count = DAY_LENGTH // 2
        self.speed      = 1
        self.individuals: list = []
        self.plants:      list = []

        self.report    = SimulationReport()
        self.logger    = SimulationLogger()
        self.death_log = DeathLogger()

        self.lock = threading.Lock()
        # Profiling
        self.profiling: bool = False
        self._profile_times: dict[str, float] = {}
        self._profile_calls: dict[str, int] = {}
        # cell_size fixe : ~1/5 de la perception max, compromis entre
        # précision des requêtes et nombre de cellules parcourues.
        # Ne PAS utiliser max_perception directement — cela crée des cellules
        # trop grandes et annule le bénéfice de la grille spatiale.
        _CELL = 8.0
        self._ind_grid   = SpatialGrid(_CELL)
        self._plant_grid = SpatialGrid(_CELL)

        # Composants extraits
        self._registry    = SpeciesRegistry(self)
        self._snapshotter = Snapshotter(self, self._registry)

    # ── Délégation SpeciesRegistry ───────────────────────────────────────────

    @property
    def species_list(self) -> list:
        return self._registry.species_list

    @species_list.setter
    def species_list(self, value: list) -> None:
        self._registry.species_list = value

    @property
    def species_counts(self) -> dict[str, int]:
        return self._registry.species_counts

    @property
    def _species_counts(self) -> dict[str, int]:
        return self._registry._species_counts

    @_species_counts.setter
    def _species_counts(self, value: dict) -> None:
        self._registry._species_counts = value

    @property
    def _max_perception(self) -> float:
        return self._registry._max_perception

    @_max_perception.setter
    def _max_perception(self, value: float) -> None:
        self._registry._max_perception = value

    @property
    def _default_counts(self) -> dict:
        return self._registry._default_counts

    @property
    def _population_overrides(self) -> dict:
        return self._registry._population_overrides

    @_population_overrides.setter
    def _population_overrides(self, value: dict) -> None:
        self._registry._population_overrides = value

    @property
    def _species_raw_params(self) -> dict:
        return self._registry._species_raw_params

    @property
    def _extinct(self) -> set:
        return self._registry._extinct

    def set_population_overrides(self, counts: dict) -> None:
        self._registry.set_population_overrides(counts)

    def add_species(self, species_data: dict, count: int = 20) -> None:
        self._registry.add_species(species_data, count=count)

    # ── Délégation Snapshotter ───────────────────────────────────────────────

    def get_terrain_snapshot(self) -> dict:
        return self._snapshotter.get_terrain_snapshot()

    def get_state_snapshot(self) -> dict:
        return self._snapshotter.get_state_snapshot()

    def generate_report(self) -> str:
        return self._snapshotter.generate_report()

    # ── Snapshot immuable pour le viewer ─────────────────────────────────────

    def snapshot_view(self) -> SimulationSnapshot:
        """Prend le verrou, copie l'état nécessaire, et retourne un snapshot immuable."""
        with self.lock:
            plants_views = tuple(
                EntityView(
                    x=p.x, y=p.y,
                    species_name=p.species.name,
                    energy=p.energy, alive=p.alive,
                    growth=p.growth, age=p.age,
                )
                for p in self.plants
            )
            inds_views = tuple(
                EntityView(
                    x=i.x, y=i.y,
                    species_name=i.species.name,
                    energy=i.energy, alive=i.alive,
                    state=i.state, sex=i.sex,
                    gestation_timer=i.gestation_timer,
                    age=i.age,
                )
                for i in self.individuals
            )
            return SimulationSnapshot(
                tick=self.tick_count,
                plants=plants_views,
                individuals=inds_views,
                species_counts=self.species_counts,
                terrain_altitude=self.grid.altitude,
            )

    # ── Boucle de simulation ─────────────────────────────────────────────────

    def enable_profiling(self) -> None:
        """Active le profiling embarqué (timing par section du tick)."""
        self.profiling = True
        self._profile_times = {}
        self._profile_calls = {}

    def get_profile_report(self) -> dict:
        """Retourne le résumé du profiling (temps total et moyen par section)."""
        report = {}
        for k, total in self._profile_times.items():
            calls = self._profile_calls.get(k, 1)
            report[k] = {"total_s": round(total, 4), "avg_ms": round(total / calls * 1000, 3)}
        return report

    def tick(self):
        self.tick_count += 1
        reg = self._registry
        _t_tick = _time.perf_counter() if self.profiling else 0.0

        # ── Saisonnalité : facteur sinusoïdal annuel [−1, 1] ─────────────────
        # season > 0 = été (croissance forte, temp élevée)
        # season < 0 = hiver (croissance réduite, temp basse)
        season = _math.sin(2 * _math.pi * self.tick_count / SIM_YEAR)
        self._season = season  # exposé pour les exports

        # ── Plantes (1 tick sur 3) ───────────────────────────────────────────
        if self.tick_count % 3 == 0:
            plant_count = len(self.plants)
            new_plants  = []
            for plant in self.plants:
                babies = plant.tick(self.grid, plant_count + len(new_plants), season=season)
                new_plants.extend(babies)
            surviving_plants = []
            for p in self.plants:
                if p.alive:
                    surviving_plants.append(p)
                else:
                    reg._species_counts[p.species.name] = max(0, reg._species_counts.get(p.species.name, 0) - 1)
            self.plants = surviving_plants
            if new_plants:
                # reg._species_counts reflète déjà les comptes courants
                # (plantes mortes déjà décrémentées) — évite le scan O(n_plants).
                sp_pc = dict(reg._species_counts)
                kept_p = []
                for baby in new_plants:
                    n    = baby.species.name
                    c    = sp_pc.get(n, 0)
                    mode = getattr(baby.species, "carrying_capacity_mode", "hard")
                    if mode == "hard" and c >= baby.species.max_population:
                        continue
                    kept_p.append(baby)
                    sp_pc[n] = c + 1
                new_plants = kept_p
            for p in new_plants:
                reg._species_counts[p.species.name] = reg._species_counts.get(p.species.name, 0) + 1
            self.plants.extend(new_plants)

        # ── Grilles spatiales ─────────────────────────────────────────────────
        # cell_size fixée dans __init__ — ne pas recalculer chaque tick.
        self._ind_grid.clear()
        self._plant_grid.clear()
        for ind   in self.individuals: self._ind_grid.insert(ind)
        for plant in self.plants:      self._plant_grid.insert(plant)
        ind_grid   = self._ind_grid
        plant_grid = self._plant_grid

        # ── Animaux ──────────────────────────────────────────────────────────
        # Le centroïde de troupeau est calculé localement (voisins dans r_repro)
        # pour éviter la convergence vers le centre de la carte causée par un
        # centroïde global.
        time_of_day     = (self.tick_count % DAY_LENGTH) / DAY_LENGTH
        new_individuals = []
        self._last_newborns: list = []
        self._last_disease_events: list = []
        self._last_dead: list = []
        for ind in self.individuals:
            _sp    = ind.species
            r_perc = _sp.perception_radius
            nearby_inds = ind_grid.query(ind.x, ind.y, r_perc)
            # Carnivores stricts (loup…) n'interrogent pas la grille des plantes
            nearby_plants = (
                plant_grid.query(ind.x, ind.y, r_perc)
                if _sp.can_eat_plants() else []
            )

            # Requête large (rayon 3×) uniquement si l'animal est éligible
            # à se reproduire ce tick — évite ~70 % des requêtes larges.
            _can_repro = (
                ind.energy > _sp.energy_start * 0.75
                and ind.reproduction_cooldown == 0
                and ind.gestation_timer == 0
                and (_sp.sexual_maturity_ticks == 0
                     or ind.age >= _sp.sexual_maturity_ticks)
            )
            nearby_repro = (
                ind_grid.query(ind.x, ind.y, r_perc * 3.0)
                if _can_repro else nearby_inds
            )

            # Centroïde depuis nearby_inds (r_perc déjà calculé) — élimine
            # la 3e requête spatiale pour les espèces à herd_cohesion > 0.
            local_centroid = None
            if _sp.herd_cohesion > 0:
                same = [o for o in nearby_inds
                        if o is not ind and o.species.name == _sp.name]
                if same:
                    local_centroid = (
                        sum(o.x for o in same) / len(same),
                        sum(o.y for o in same) / len(same),
                    )

            herd_centroids = (
                {_sp.name: local_centroid} if local_centroid else {}
            )
            babies = ind.tick(self.grid, nearby_plants, nearby_inds, time_of_day,
                              herd_centroids=herd_centroids,
                              all_individuals_repro=nearby_repro)
            new_individuals.extend(babies)

        surviving_inds = []
        for ind in self.individuals:
            if ind.alive:
                surviving_inds.append(ind)
            else:
                reg._species_counts[ind.species.name] = max(0, reg._species_counts.get(ind.species.name, 0) - 1)
                self._last_dead.append(ind)
                # Restitution de nutriments par les cadavres animaux (ODD §7.5)
                ix, iy = int(ind.x), int(ind.y)
                if (0 <= ix < self.grid.width and 0 <= iy < self.grid.height):
                    self.grid.nutrients[iy, ix] = min(
                        1.0, self.grid.nutrients[iy, ix] + 0.001
                    )
                if hasattr(ind, "death_cause"):
                    self.death_log.record(ind, self.tick_count)
                    if ind.death_cause == "disease":
                        disease_name = next(iter(ind.disease_states), "unknown") if ind.disease_states else "unknown"
                        self._last_disease_events.append({
                            "type": "disease_death",
                            "disease": disease_name,
                            "species": ind.species.name,
                            "x": round(ind.x, 2),
                            "y": round(ind.y, 2),
                        })
        self.individuals = surviving_inds

        if new_individuals:
            # reg._species_counts est à jour (morts décrémentés, nés pas encore ajoutés)
            sp_count = dict(reg._species_counts)
            kept = []
            for baby in new_individuals:
                n    = baby.species.name
                c    = sp_count.get(n, 0)
                mode = getattr(baby.species, "carrying_capacity_mode", "hard")
                if mode == "hard" and c >= baby.species.max_population:
                    continue  # plafond dur
                kept.append(baby)
                sp_count[n] = c + 1
            new_individuals = kept

        for baby in new_individuals:
            reg._species_counts[baby.species.name] = reg._species_counts.get(baby.species.name, 0) + 1
        self._last_newborns = new_individuals
        self.individuals.extend(new_individuals)

        self._tick_diseases()

        reg.detect_extinctions(self.tick_count)

        if self.profiling:
            dt = _time.perf_counter() - _t_tick
            self._profile_times["tick_total"] = self._profile_times.get("tick_total", 0.0) + dt
            self._profile_calls["tick_total"] = self._profile_calls.get("tick_total", 0) + 1

        if self.tick_count % 500 == 0:
            self.report.record(self.tick_count, self.plants, self.individuals)
            self.logger.log(self.tick_count, self.plants, self.individuals)
            print(f"Tick {self.tick_count} — {self.species_counts}")

    # ── Maladies ─────────────────────────────────────────────────────────────

    def _tick_diseases(self) -> None:
        """Propage les maladies entre individus proches."""
        from entities.disease import DISEASE_REGISTRY, try_infect
        if not DISEASE_REGISTRY:
            return
        infectious = [i for i in self.individuals if i.alive and i.is_infectious]
        if not infectious:
            return
        for source in infectious:
            for spec in DISEASE_REGISTRY.values():
                neighbors = self._ind_grid.query_radius(
                    source.x, source.y, spec.transmission_radius
                )
                for target in neighbors:
                    if target is not source and target.alive:
                        if try_infect(source, target, spec):
                            self._last_disease_events.append({
                                "type":       "disease_infection",
                                "disease":    spec.name,
                                "species":    target.species.name,
                                "x":          round(target.x, 2),
                                "y":          round(target.y, 2),
                                "source_uid": getattr(source, "uid", -1),
                                "target_uid": getattr(target, "uid", -1),
                            })

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self):
        self.logger.log_event(self.tick_count, "RESET de la simulation")
        self.logger.close()
        self.death_log.close()
        self.logger    = SimulationLogger()
        self.report    = SimulationReport()
        self.death_log = DeathLogger()
        self.tick_count = DAY_LENGTH // 2
        self.running    = False
        self.individuals = []
        self.plants      = []
        self._registry.reset()
        print("Simulation reinitialisee")

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self):
        self.logger.log_event(self.tick_count, "RESET de la simulation")
        self.logger.close()
        self.death_log.close()
        self.logger    = SimulationLogger()
        self.report    = SimulationReport()
        self.death_log = DeathLogger()
        self.tick_count = DAY_LENGTH // 2
        self.running    = False
        self.individuals = []
        self.plants      = []
        self._registry.reset()
        print("Simulation reinitialisee")
