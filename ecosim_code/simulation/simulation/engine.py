import random
import threading
import numpy as np
from world.grid import Grid
from world.spatial_grid import SpatialGrid
from entities.species import Species, sample_params
from entities.animal import Individual
from entities.plant import Plant
from monitoring.report import SimulationReport
from monitoring.logger import SimulationLogger
from monitoring.death_log import DeathLogger
from simulation.utils.counting import count_by_species

DAY_LENGTH = 1_200        # ticks par jour simulé  (20 ticks/s × 60 s = 1 min réelle)
SIM_YEAR   = 438_000     # ticks par an (365 × 1 200)

class SimulationEngine:
    def __init__(self, grid: Grid):
        self.grid = grid
        self.running  = False
        self.tick_count = DAY_LENGTH // 2
        self.speed    = 1
        self.individuals  = []
        self.plants       = []
        self.species_list = []
        self.report    = SimulationReport()
        self.logger    = SimulationLogger()
        self.death_log = DeathLogger()
        self._extinct              = set()
        self._default_counts       = {}
        self._population_overrides = {}
        self._species_raw_params   = {}   # raw params (avec *_std) par nom d'espèce
        self._species_counts       = {}   # {name: int} nb entités vivantes — mis à jour incrémentalement
        self._max_perception       = 10.0 # mis à jour dans add_species / reset
        self._non_water_cells: np.ndarray | None = None  # calculé à la génération du terrain
        self._all_cells:       np.ndarray | None = None
        self.lock = threading.Lock()      # protège individuals/plants contre les accès concurrents
        # Grilles spatiales réutilisées chaque tick (évite de réallouer les dicts internes)
        self._ind_grid   = SpatialGrid(1.0)
        self._plant_grid = SpatialGrid(1.0)

    def _rebuild_valid_cells(self) -> None:
        """Pré-calcule les indices de cellules non-eau (utilisé par add_species)."""
        self._non_water_cells = np.argwhere(self.grid.soil_type != "water")  # shape (N, 2) [y, x]
        self._all_cells       = np.array([[y, x]
                                          for y in range(self.grid.height)
                                          for x in range(self.grid.width)])

    # ── Lecture seule ─────────────────────────────────────────────────────────

    @property
    def species_counts(self) -> dict[str, int]:
        """Nombre d'entités vivantes par nom d'espèce (copie en lecture seule)."""
        return dict(self._species_counts)

    # ── Configuration ────────────────────────────────────────────────────────

    def set_population_overrides(self, counts: dict) -> None:
        self._population_overrides = {k: max(0, int(v)) for k, v in counts.items()}

    def add_species(self, species_data: dict, count: int = 20):
        # Template (un tirage pour l'identité dans species_list)
        sp_template = Species(**sample_params(species_data))
        self._default_counts[sp_template.name] = count
        self._species_raw_params[sp_template.name] = species_data
        self.species_list.append(sp_template)

        # Spawn exactement `count` entités sur des cellules valides.
        # Les cellules sont pré-calculées une seule fois (évite 250 000 tuples par appel).
        if self._non_water_cells is None:
            self._rebuild_valid_cells()

        can_swim = sp_template.can_swim or sp_template.is_flying()
        pool = self._all_cells if can_swim else self._non_water_cells

        if pool is None or len(pool) == 0:
            return  # aucune cellule valide (terrain entièrement eau)

        rng = np.random.default_rng()
        choices = rng.integers(0, len(pool), size=count)

        spawned = 0
        while spawned < count:
            idx = choices[spawned] if spawned < len(choices) else rng.integers(0, len(pool))
            y, x = pool[idx]
            if sp_template.is_plant():
                self.plants.append(Plant(species=sp_template, x=x, y=y))
            else:
                sp_ind = Species(**sample_params(species_data))
                self.individuals.append(Individual(
                    species=sp_ind, x=x, y=y,
                    energy=sp_ind.energy_start * random.uniform(0.5, 1.0),
                    sex=random.choice(["male", "female"]),
                    age=random.randint(0, sp_ind.max_age // 2),
                    home_x=float(x), home_y=float(y),
                ))
            spawned += 1
        self._species_counts[sp_template.name] = self._species_counts.get(sp_template.name, 0) + spawned
        self._max_perception = max(
            (sp.perception_radius for sp in self.species_list if not sp.is_plant()),
            default=10.0,
        )

    # ── Boucle de simulation ─────────────────────────────────────────────────

    def tick(self):
        self.tick_count += 1

        # ── Plantes (1 tick sur 10) ───────────────────────────────────────────
        # Les plantes poussent sur des centaines de ticks : inutile de les
        # évaluer 20×/s. growth_rate dans les JSON est compensé (×10).
        if self.tick_count % 10 == 0:
            plant_count = len(self.plants)
            new_plants  = []
            for plant in self.plants:
                # On passe le total courant (existants + déjà nés ce tick) pour
                # éviter que toutes les plantes se reproduisent dans le même tick
                babies = plant.tick(self.grid, plant_count + len(new_plants))
                new_plants.extend(babies)
            # Filtrer les plantes mortes + mettre à jour le compteur d'espèces
            surviving_plants = []
            for p in self.plants:
                if p.alive:
                    surviving_plants.append(p)
                else:
                    self._species_counts[p.species.name] = self._species_counts.get(p.species.name, 0) - 1
            self.plants = surviving_plants
            # Hard cap : par sécurité, respecter max_population même si plant.py laisse passer
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
                self._species_counts[p.species.name] = self._species_counts.get(p.species.name, 0) + 1
            self.plants.extend(new_plants)

        # ── Grilles spatiales (construites une fois par tick) ─────────────────
        # cell_size = max perception radius → densité optimale
        self._ind_grid.cell_size   = max(self._max_perception, 1.0)
        self._plant_grid.cell_size = max(self._max_perception, 1.0)
        self._ind_grid.clear()
        self._plant_grid.clear()
        for ind   in self.individuals: self._ind_grid.insert(ind)
        for plant in self.plants:      self._plant_grid.insert(plant)
        ind_grid   = self._ind_grid
        plant_grid = self._plant_grid

        # ── Centroïdes de troupeau (une passe O(n) pour toutes les espèces) ─────
        # Évite que chaque animal en état wander reboucle sur ses voisins (O(n²)).
        _hc_acc: dict = {}  # name → [sx, sy, count]
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
        # Rayons :
        #   r_perc  = perception_radius → prédateurs, nourriture
        #   r_repro = 3 × perception_radius → partenaire (reproduction._try_reproduce)
        time_of_day     = (self.tick_count % DAY_LENGTH) / DAY_LENGTH
        new_individuals = []
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

        # Enregistrement des morts + mise à jour compteur d'espèces
        surviving_inds = []
        for ind in self.individuals:
            if ind.alive:
                surviving_inds.append(ind)
            else:
                self._species_counts[ind.species.name] = self._species_counts.get(ind.species.name, 0) - 1
                if hasattr(ind, "death_cause"):
                    self.death_log.record(ind, self.tick_count)
        self.individuals = surviving_inds

        # Respecter max_population par espèce (bug fix : sans ça la pop explose)
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
            self._species_counts[baby.species.name] = self._species_counts.get(baby.species.name, 0) + 1
        self.individuals.extend(new_individuals)

        # ── Détection d'extinction ────────────────────────────────────────────
        # Compteur incrémental — pas de parcours O(n) des listes à chaque tick.
        for sp in self.species_list:
            if self._species_counts.get(sp.name, 0) <= 0 and sp.name not in self._extinct:
                self._extinct.add(sp.name)
                self.logger.log_event(self.tick_count, f"EXTINCTION de {sp.name}")
                self.report.record_event(self.tick_count, "extinction", sp.name)
                print(f"[EXTINCTION] {sp.name} au tick {self.tick_count}")

        # ── Log + rapport toutes les 500 ticks (~10 s réels à x1) ────────────
        if self.tick_count % 500 == 0:
            self.report.record(self.tick_count, self.plants, self.individuals)
            self.logger.log(self.tick_count, self.plants, self.individuals)
            print(f"Tick {self.tick_count} — {self.species_counts}")

    # ── Génération de rapport ─────────────────────────────────────────────────

    def generate_report(self):
        return self.report.generate(
            self.tick_count, self.plants, self.individuals,
            self.grid.width, self.grid.height,
        )

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
        self._extinct    = set()
        self._species_counts = {}
        self._max_perception = 10.0

        saved_defaults  = dict(self._default_counts)
        saved_overrides = dict(self._population_overrides)
        saved_raw       = dict(self._species_raw_params)
        self.species_list        = []
        self._default_counts     = {}
        self._species_raw_params = {}

        for name, raw in saved_raw.items():
            count = saved_overrides.get(name, saved_defaults.get(name, 20))
            self.add_species(raw, count=count)

        self._population_overrides = saved_overrides
        print("Simulation reinitialisee")

    # ── Snapshots WebSocket ───────────────────────────────────────────────────

    def get_terrain_snapshot(self) -> dict:
        import numpy as np
        return {
            "type":    "terrain",
            "width":   self.grid.width,
            "height":  self.grid.height,
            "altitude": np.round(self.grid.altitude, 2).tolist(),
            "species": [
                {
                    "name":  sp.name,
                    "color": list(sp.color),
                    "count": self._population_overrides.get(
                        sp.name, self._default_counts.get(sp.name, 0)
                    ),
                }
                for sp in self.species_list
            ],
        }

    def get_state_snapshot(self) -> dict:
        time_of_day = (self.tick_count % DAY_LENGTH) / DAY_LENGTH
        sim_day     = (self.tick_count // DAY_LENGTH) % 365
        sim_year    = self.tick_count // SIM_YEAR + 1
        return {
            "type":        "world_update",
            "tick":        self.tick_count,
            "time_of_day": round(time_of_day, 3),
            "sim_day":     sim_day,
            "sim_year":    sim_year,
            "entities": [
                {
                    "x":       round(p.x, 1),
                    "y":       round(p.y, 1),
                    "type":    "plant",
                    "species": p.species.name,
                    "color":   list(p.species.color),
                    "growth":  round(p.growth, 2),
                } for p in self.plants
            ] + [
                {
                    "x":       round(i.x, 1),
                    "y":       round(i.y, 1),
                    "type":    i.species.type,
                    "species": i.species.name,
                    "color":   list(i.species.color),
                    "state":   i.state,
                } for i in self.individuals
            ],
        }
