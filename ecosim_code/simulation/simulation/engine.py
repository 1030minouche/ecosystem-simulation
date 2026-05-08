"""
SimulationEngine — façade qui agrège EngineCore, SpeciesRegistry et Snapshotter.

Toutes les méthodes publiques historiques restent disponibles pour la
compatibilité ascendante. Les implémentations vivent dans :
  - simulation/species_registry.py  (spawn, comptage, extinction)
  - simulation/snapshotter.py       (snapshots WebSocket, rapport)
"""

import threading
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


class SimulationEngine:
    def __init__(self, grid: Grid, seed: int | None = None):
        _entity_rng_module.rng.reset(seed)
        self.seed       = seed
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
        self._ind_grid   = SpatialGrid(1.0)
        self._plant_grid = SpatialGrid(1.0)

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

    def tick(self):
        self.tick_count += 1
        reg = self._registry

        # ── Plantes (1 tick sur 3) ───────────────────────────────────────────
        if self.tick_count % 3 == 0:
            plant_count = len(self.plants)
            new_plants  = []
            for plant in self.plants:
                babies = plant.tick(self.grid, plant_count + len(new_plants))
                new_plants.extend(babies)
            surviving_plants = []
            for p in self.plants:
                if p.alive:
                    surviving_plants.append(p)
                else:
                    reg._species_counts[p.species.name] = max(0, reg._species_counts.get(p.species.name, 0) - 1)
            self.plants = surviving_plants
            if new_plants:
                sp_pc = {}
                for p in self.plants:
                    sp_pc[p.species.name] = sp_pc.get(p.species.name, 0) + 1
                kept_p = []
                for baby in new_plants:
                    n = baby.species.name
                    c = sp_pc.get(n, 0)
                    if c < baby.species.max_population:
                        kept_p.append(baby)
                        sp_pc[n] = c + 1
                new_plants = kept_p
            for p in new_plants:
                reg._species_counts[p.species.name] = reg._species_counts.get(p.species.name, 0) + 1
            self.plants.extend(new_plants)

        # ── Grilles spatiales ─────────────────────────────────────────────────
        self._ind_grid.cell_size   = max(reg._max_perception, 1.0)
        self._plant_grid.cell_size = max(reg._max_perception, 1.0)
        self._ind_grid.clear()
        self._plant_grid.clear()
        for ind   in self.individuals: self._ind_grid.insert(ind)
        for plant in self.plants:      self._plant_grid.insert(plant)
        ind_grid   = self._ind_grid
        plant_grid = self._plant_grid

        # ── Centroïdes de troupeau ────────────────────────────────────────────
        _hc_acc: dict = {}
        for ind in self.individuals:
            if ind.species.herd_cohesion > 0:
                name = ind.species.name
                if name not in _hc_acc:
                    _hc_acc[name] = [0.0, 0.0, 0]
                _hc_acc[name][0] += ind.x
                _hc_acc[name][1] += ind.y
                _hc_acc[name][2] += 1
        herd_centroids = {
            name: (acc[0] / acc[2], acc[1] / acc[2])
            for name, acc in _hc_acc.items()
        }

        # ── Animaux ──────────────────────────────────────────────────────────
        time_of_day     = (self.tick_count % DAY_LENGTH) / DAY_LENGTH
        new_individuals = []
        self._last_newborns: list = []
        for ind in self.individuals:
            r_perc  = ind.species.perception_radius
            r_repro = r_perc * 3.0
            nearby_inds   = ind_grid.query(ind.x, ind.y, r_perc)
            nearby_plants = plant_grid.query(ind.x, ind.y, r_perc)
            nearby_repro  = ind_grid.query(ind.x, ind.y, r_repro)
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
                if hasattr(ind, "death_cause"):
                    self.death_log.record(ind, self.tick_count)
        self.individuals = surviving_inds

        if new_individuals:
            sp_count = {}
            for i in self.individuals:
                sp_count[i.species.name] = sp_count.get(i.species.name, 0) + 1
            kept = []
            for baby in new_individuals:
                n = baby.species.name
                c = sp_count.get(n, 0)
                if c < baby.species.max_population:
                    kept.append(baby)
                    sp_count[n] = c + 1
            new_individuals = kept

        for baby in new_individuals:
            reg._species_counts[baby.species.name] = reg._species_counts.get(baby.species.name, 0) + 1
        self._last_newborns = new_individuals
        self.individuals.extend(new_individuals)

        self._tick_diseases()

        reg.detect_extinctions(self.tick_count)

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
                        try_infect(source, target, spec)

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
