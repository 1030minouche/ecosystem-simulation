"""
Registre des espèces : spawn, comptage, extinction, pré-calcul des cellules valides.
"""

import numpy as np
from entities.rng import rng as _ent_rng
from entities.species import Species, sample_params
from entities.animal import Individual
from entities.plant import Plant


class SpeciesRegistry:
    def __init__(self, core):
        self._core = core          # référence à EngineCore (grid, individuals, plants, logger, report)
        self.species_list: list[Species] = []
        self._default_counts:       dict[str, int]    = {}
        self._population_overrides: dict[str, int]    = {}
        self._species_raw_params:   dict[str, dict]   = {}
        self._species_counts:       dict[str, int]    = {}
        self._extinct:              set[str]          = set()
        self._max_perception:       float             = 10.0
        self._non_water_cells:      np.ndarray | None = None
        self._all_cells:            np.ndarray | None = None

    # ── Lecture seule ─────────────────────────────────────────────────────────

    @property
    def species_counts(self) -> dict[str, int]:
        return dict(self._species_counts)

    # ── Cellules valides ──────────────────────────────────────────────────────

    def rebuild_valid_cells(self) -> None:
        grid = self._core.grid
        self._non_water_cells = np.argwhere(grid.soil_type != "water")
        self._all_cells       = np.array([[y, x]
                                          for y in range(grid.height)
                                          for x in range(grid.width)])

    # ── Ajout d'espèce ────────────────────────────────────────────────────────

    def add_species(self, species_data: dict, count: int = 20) -> None:
        core = self._core
        sp_template = Species(**sample_params(species_data))
        self._default_counts[sp_template.name] = count
        self._species_raw_params[sp_template.name] = species_data
        self.species_list.append(sp_template)

        if self._non_water_cells is None:
            self.rebuild_valid_cells()

        can_swim = sp_template.can_swim or sp_template.is_flying()
        pool = self._all_cells if can_swim else self._non_water_cells

        if pool is None or len(pool) == 0:
            return

        choices = _ent_rng.generator.integers(0, len(pool), size=count)
        spawned = 0
        while spawned < count:
            idx  = choices[spawned] if spawned < len(choices) else _ent_rng.generator.integers(0, len(pool))
            y, x = pool[idx]
            if sp_template.is_plant():
                core.plants.append(Plant(species=sp_template, x=int(x), y=int(y)))
            else:
                sp_ind = Species(**sample_params(species_data))
                core.individuals.append(Individual(
                    species=sp_ind, x=float(x), y=float(y),
                    energy=sp_ind.energy_start * _ent_rng.uniform(0.5, 1.0),
                    sex=_ent_rng.choice(["male", "female"]),
                    age=_ent_rng.randint(0, sp_ind.max_age // 2),
                    home_x=float(x), home_y=float(y),
                ))
            spawned += 1

        self._species_counts[sp_template.name] = (
            self._species_counts.get(sp_template.name, 0) + spawned
        )
        self._max_perception = max(
            (sp.perception_radius for sp in self.species_list if not sp.is_plant()),
            default=10.0,
        )

    def set_population_overrides(self, counts: dict) -> None:
        self._population_overrides = {k: max(0, int(v)) for k, v in counts.items()}

    def reset(self) -> None:
        saved_defaults  = dict(self._default_counts)
        saved_overrides = dict(self._population_overrides)
        saved_raw       = dict(self._species_raw_params)

        self.species_list        = []
        self._default_counts     = {}
        self._species_raw_params = {}
        self._species_counts     = {}
        self._extinct            = set()
        self._max_perception     = 10.0
        self._non_water_cells    = None
        self._all_cells          = None

        for name, raw in saved_raw.items():
            cnt = saved_overrides.get(name, saved_defaults.get(name, 20))
            self.add_species(raw, count=cnt)

        self._population_overrides = saved_overrides

    def detect_extinctions(self, tick_count: int) -> None:
        core = self._core
        for sp in self.species_list:
            if self._species_counts.get(sp.name, 0) <= 0 and sp.name not in self._extinct:
                self._extinct.add(sp.name)
                core.logger.log_event(tick_count, f"EXTINCTION de {sp.name}")
                core.report.record_event(tick_count, "extinction", sp.name)
                print(f"[EXTINCTION] {sp.name} au tick {tick_count}")
