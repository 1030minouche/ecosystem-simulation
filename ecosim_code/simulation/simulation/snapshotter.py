"""
Snapshotter : génération de snapshots WebSocket et de rapports.
"""

import numpy as np
from simulation.engine_const import DAY_LENGTH, SIM_YEAR


class Snapshotter:
    def __init__(self, core, registry):
        self._core     = core
        self._registry = registry

    def get_terrain_snapshot(self) -> dict:
        core     = self._core
        registry = self._registry
        return {
            "type":    "terrain",
            "width":   core.grid.width,
            "height":  core.grid.height,
            "altitude": np.round(core.grid.altitude, 2).tolist(),
            "species": [
                {
                    "name":  sp.name,
                    "color": list(sp.color),
                    "count": registry._population_overrides.get(
                        sp.name, registry._default_counts.get(sp.name, 0)
                    ),
                }
                for sp in registry.species_list
            ],
        }

    def get_state_snapshot(self) -> dict:
        core = self._core
        with core.lock:
            plants = list(core.plants)
            indivs = list(core.individuals)
            tick   = core.tick_count
        time_of_day = (tick % DAY_LENGTH) / DAY_LENGTH
        sim_day     = (tick // DAY_LENGTH) % 365
        sim_year    = tick // SIM_YEAR + 1
        return {
            "type":        "world_update",
            "tick":        tick,
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
                } for p in plants
            ] + [
                {
                    "x":       round(i.x, 1),
                    "y":       round(i.y, 1),
                    "type":    i.species.type,
                    "species": i.species.name,
                    "color":   list(i.species.color),
                    "state":   i.state,
                } for i in indivs
            ],
        }

    def generate_report(self) -> str:
        core = self._core
        return core.report.generate(
            core.tick_count, core.plants, core.individuals,
            core.grid.width, core.grid.height,
        )
