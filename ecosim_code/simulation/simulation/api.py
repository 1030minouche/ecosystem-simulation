"""
API Python scriptée pour EcoSim — sans serveur HTTP.

Usage typique (notebook / script de recherche) :

    from simulation.api import Simulation, SimConfig

    cfg = SimConfig(seed=42, grid_size=200, ticks=10_000)
    sim = Simulation(cfg)
    sim.add_species_from_file("species/lapin.json")
    sim.run(5000)
    df = sim.populations_dataframe()
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class SimConfig:
    seed: int | None = None
    grid_size: int = 500
    terrain_preset: str = "temperate"
    out_path: Path | None = None
    keyframe_every: int = 500
    experiment_name: str = ""
    tags: list[str] = field(default_factory=list)


class Simulation:
    """Façade scriptée pour lancer et analyser une simulation EcoSim."""

    def __init__(self, config: SimConfig | None = None):
        self.config = config or SimConfig()
        self._engine = None
        self._recorder = None
        self._runner = None
        self._build()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        from world.grid import Grid
        from world.terrain import generate_terrain
        from simulation.engine import SimulationEngine

        cfg = self.config
        grid = Grid(cfg.grid_size, cfg.grid_size)
        generate_terrain(grid, seed=cfg.seed if cfg.seed is not None else 42)
        self._engine = SimulationEngine(grid, seed=cfg.seed)

        if cfg.out_path:
            from simulation.recording.recorder import Recorder
            Path(cfg.out_path).parent.mkdir(parents=True, exist_ok=True)
            self._recorder = Recorder(Path(cfg.out_path),
                                      keyframe_every=cfg.keyframe_every)
            self._recorder.write_engine_meta(self._engine)
            if cfg.experiment_name:
                self._recorder.write_meta("experiment_name", cfg.experiment_name)
            if cfg.tags:
                self._recorder.write_meta("tags", json.dumps(cfg.tags))

        from simulation.runner import EngineRunner
        self._runner = EngineRunner(self._engine, recorder=self._recorder)

    # ── Espèces ───────────────────────────────────────────────────────────────

    def add_species_from_file(self, path: str | Path) -> "Simulation":
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        params = spec.get("params", spec)
        if "color" in params:
            params["color"] = tuple(params["color"])
        self._engine.add_species(params, count=spec.get("count", 20))
        return self

    def add_species_from_dir(self, directory: str | Path) -> "Simulation":
        for p in sorted(Path(directory).glob("*.json")):
            self.add_species_from_file(p)
        return self

    def add_species(self, params: dict, count: int = 20) -> "Simulation":
        self._engine.add_species(params, count=count)
        return self

    # ── Exécution ─────────────────────────────────────────────────────────────

    def step(self) -> None:
        """Avance d'un seul tick."""
        self._engine.tick()
        if self._recorder is not None:
            self._recorder.on_tick_end(self._engine)

    def run(self, n_ticks: int,
            on_progress: Callable[[int, dict], None] | None = None) -> "RunSummary":
        """Lance n_ticks ticks et retourne un résumé."""
        from simulation.runner import RunSummary
        summary = self._runner.run(max_ticks=n_ticks, on_progress=on_progress)
        return summary

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── État courant ──────────────────────────────────────────────────────────

    @property
    def tick(self) -> int:
        return self._engine.tick_count

    @property
    def populations(self) -> dict[str, int]:
        return dict(self._engine.species_counts)

    @property
    def individuals(self) -> list:
        return list(self._engine.individuals)

    @property
    def plants(self) -> list:
        return list(self._engine.plants)

    @property
    def season(self) -> float:
        return getattr(self._engine, '_season', 0.0)

    # ── Export rapide ─────────────────────────────────────────────────────────

    def populations_dataframe(self):
        """Retourne un pandas DataFrame avec l'état courant des individus."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas requis pour populations_dataframe()")
        rows = []
        for ind in self._engine.individuals:
            rows.append({
                "uid":     getattr(ind, 'uid', None),
                "species": ind.species.name,
                "x":       round(ind.x, 2),
                "y":       round(ind.y, 2),
                "energy":  round(ind.energy, 2),
                "age":     ind.age,
                "sex":     getattr(ind, 'sex', '?'),
            })
        return pd.DataFrame(rows)
