import random
from world.grid import Grid
from world.spatial_grid import SpatialGrid
from entities.species import Species, sample_params
from entities.animal import Individual
from entities.plant import Plant
from monitoring.report import SimulationReport
from monitoring.logger import SimulationLogger
from monitoring.death_log import DeathLogger

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

    # ── Configuration ────────────────────────────────────────────────────────

    def set_population_overrides(self, counts: dict) -> None:
        self._population_overrides = {k: max(0, int(v)) for k, v in counts.items()}

    def add_species(self, species_data: dict, count: int = 20):
        # Template (un tirage pour l'identité dans species_list)
        sp_template = Species(**sample_params(species_data))
        self._default_counts[sp_template.name] = count
        self._species_raw_params[sp_template.name] = species_data
        self.species_list.append(sp_template)

        # Spawn exactement `count` entités sur des cellules non-eau.
        # Chaque animal reçoit son propre tirage de paramètres individuels.
        # Les plantes partagent le template (pas de reproduction sexuée).
        spawned   = 0
        attempts  = 0
        max_tries = count * 20
        while spawned < count and attempts < max_tries:
            x = random.randint(0, self.grid.width  - 1)
            y = random.randint(0, self.grid.height - 1)
            attempts += 1
            if self.grid.cells[y][x].soil_type == "water":
                continue
            if sp_template.type == "plant":
                self.plants.append(Plant(species=sp_template, x=x, y=y))
            else:
                sp_ind = Species(**sample_params(species_data))
                self.individuals.append(Individual(
                    species=sp_ind, x=x, y=y,
                    energy=sp_ind.energy_start * random.uniform(0.5, 1.0),
                    sex=random.choice(["male", "female"]),
                    age=random.randint(0, sp_ind.max_age // 2),
                ))
            spawned += 1

    # ── Boucle de simulation ─────────────────────────────────────────────────

    def tick(self):
        self.tick_count += 1

        # ── Plantes ──────────────────────────────────────────────────────────
        plant_count = len(self.plants)
        new_plants  = []
        for plant in self.plants:
            # On passe le total courant (existants + déjà nés ce tick) pour
            # éviter que toutes les plantes se reproduisent dans le même tick
            babies = plant.tick(self.grid, plant_count + len(new_plants))
            new_plants.extend(babies)
        self.plants = [p for p in self.plants if p.alive]
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
        self.plants.extend(new_plants)

        # ── Grilles spatiales (construites une fois par tick) ─────────────────
        # cell_size = max perception radius → densité optimale
        max_perception = max(
            (sp.perception_radius for sp in self.species_list if sp.type != "plant"),
            default=10.0,
        )
        ind_grid   = SpatialGrid(max_perception)
        plant_grid = SpatialGrid(max_perception)
        for ind   in self.individuals: ind_grid.insert(ind)
        for plant in self.plants:      plant_grid.insert(plant)

        # ── Animaux ──────────────────────────────────────────────────────────
        time_of_day     = (self.tick_count % DAY_LENGTH) / DAY_LENGTH
        new_individuals = []
        for ind in self.individuals:
            # Rayon de requête = 3× perception (couvre reproduction 3× + nourriture 1×)
            r = ind.species.perception_radius * 3.0
            nearby_inds   = ind_grid.query(ind.x, ind.y, r)
            nearby_plants = plant_grid.query(ind.x, ind.y, r)
            babies = ind.tick(self.grid, nearby_plants, nearby_inds, time_of_day)
            new_individuals.extend(babies)

        # Enregistrement des morts avant purge
        for ind in self.individuals:
            if not ind.alive and hasattr(ind, "death_cause"):
                self.death_log.record(ind, self.tick_count)

        self.individuals = [i for i in self.individuals if i.alive]

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

        self.individuals.extend(new_individuals)

        # ── Détection d'extinction ────────────────────────────────────────────
        current_names = {p.species.name for p in self.plants} | \
                        {i.species.name for i in self.individuals}
        for sp in self.species_list:
            if sp.name not in current_names and sp.name not in self._extinct:
                self._extinct.add(sp.name)
                self.logger.log_event(self.tick_count, f"EXTINCTION de {sp.name}")
                print(f"[EXTINCTION] {sp.name} au tick {self.tick_count}")

        # ── Log + rapport toutes les 500 ticks (~10 s réels à x1) ────────────
        if self.tick_count % 500 == 0:
            self.report.record(self.tick_count, self.plants, self.individuals)
            self.logger.log(self.tick_count, self.plants, self.individuals)
            counts = {}
            for p in self.plants:
                counts[p.species.name] = counts.get(p.species.name, 0) + 1
            for i in self.individuals:
                counts[i.species.name] = counts.get(i.species.name, 0) + 1
            print(f"Tick {self.tick_count} — {counts}")

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
