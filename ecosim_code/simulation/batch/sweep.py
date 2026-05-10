"""
Mode batch avec parameter sweep pour EcoSim.

Permet de lancer automatiquement plusieurs simulations en faisant varier
un ou plusieurs paramètres, avec réplicats statistiques.

Usage :
    from batch.sweep import ParameterSweep, SweepParam

    sweep = ParameterSweep(
        base_species_dir="species/",
        out_dir="runs/sweep_speed",
        params=[SweepParam("speed", [0.5, 1.0, 2.0])],
        n_ticks=10_000,
        n_replicates=5,
    )
    results = sweep.run()
    df = sweep.summary_dataframe()
"""
from __future__ import annotations

import copy
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SweepParam:
    """Paramètre à faire varier dans le sweep."""
    name:   str
    values: list


@dataclass
class SweepResult:
    param_values: dict
    replicate:    int
    seed:         int
    ticks_done:   int
    elapsed_s:    float
    final_populations: dict[str, int]
    death_causes:      dict[str, int]
    db_path:      Path | None = None


class ParameterSweep:
    """Lance une grille de simulations headless avec variations paramétriques."""

    def __init__(
        self,
        base_species_dir: str | Path,
        out_dir: str | Path,
        params: list[SweepParam],
        n_ticks: int = 10_000,
        n_replicates: int = 3,
        grid_size: int = 200,
        base_seed: int = 0,
        save_db: bool = True,
    ):
        self.base_species_dir = Path(base_species_dir)
        self.out_dir          = Path(out_dir)
        self.params           = params
        self.n_ticks          = n_ticks
        self.n_replicates     = n_replicates
        self.grid_size        = grid_size
        self.base_seed        = base_seed
        self.save_db          = save_db
        self.results: list[SweepResult] = []

    def _load_species(self) -> list[dict]:
        specs = []
        for p in sorted(self.base_species_dir.glob("*.json")):
            with open(p, encoding="utf-8") as f:
                specs.append(json.load(f))
        return specs

    def _apply_param(self, species_list: list[dict], name: str, value) -> list[dict]:
        """Applique la valeur d'un paramètre à tous les specs qui l'ont."""
        modified = copy.deepcopy(species_list)
        for spec in modified:
            params = spec.get("params", spec)
            if name in params:
                params[name] = value
        return modified

    def run(self, verbose: bool = True) -> list[SweepResult]:
        from world.grid import Grid
        from world.terrain import generate_terrain
        from simulation.engine import SimulationEngine
        from simulation.runner import EngineRunner

        self.out_dir.mkdir(parents=True, exist_ok=True)
        base_specs = self._load_species()

        param_names  = [p.name for p in self.params]
        param_values = [p.values for p in self.params]
        grid_combos  = list(itertools.product(*param_values))

        run_idx = 0
        for combo in grid_combos:
            combo_dict = dict(zip(param_names, combo))
            specs = base_specs
            for name, value in combo_dict.items():
                specs = self._apply_param(specs, name, value)

            for rep in range(self.n_replicates):
                seed = self.base_seed + run_idx * 137
                run_idx += 1

                db_path = None
                if self.save_db:
                    combo_str = "_".join(f"{k}={v}" for k, v in combo_dict.items())
                    db_path = self.out_dir / f"{combo_str}_rep{rep:02d}.db"

                if verbose:
                    print(f"[sweep] {combo_dict}  rep={rep}  seed={seed}", flush=True)

                t0 = time.monotonic()
                grid = Grid(self.grid_size, self.grid_size)
                generate_terrain(grid, seed=seed)
                engine = SimulationEngine(grid, seed=seed)

                for spec in specs:
                    params = spec.get("params", dict(spec))
                    if "color" in params:
                        params["color"] = tuple(params["color"])
                    engine.add_species(params, count=spec.get("count", 20))

                recorder = None
                if db_path:
                    from simulation.recording.recorder import Recorder
                    recorder = Recorder(db_path)
                    recorder.write_engine_meta(engine)
                    recorder.write_meta("sweep_params", json.dumps(combo_dict))
                    recorder.write_meta("replicate",    str(rep))

                runner  = EngineRunner(engine, recorder=recorder)
                summary = runner.run(max_ticks=self.n_ticks)

                if recorder:
                    recorder.close()

                result = SweepResult(
                    param_values=combo_dict,
                    replicate=rep,
                    seed=seed,
                    ticks_done=summary.ticks_done,
                    elapsed_s=round(time.monotonic() - t0, 2),
                    final_populations=summary.final_populations,
                    death_causes=summary.death_causes,
                    db_path=db_path,
                )
                self.results.append(result)
                if verbose:
                    print(f"  → {summary.final_populations}  t={result.elapsed_s}s",
                          flush=True)

        return self.results

    def summary_dataframe(self):
        """Retourne un pandas DataFrame résumant toutes les runs."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas requis pour summary_dataframe()")
        rows = []
        for r in self.results:
            row = dict(r.param_values)
            row["replicate"] = r.replicate
            row["seed"]      = r.seed
            row["ticks_done"] = r.ticks_done
            row["elapsed_s"] = r.elapsed_s
            row.update({f"pop_{k}": v for k, v in r.final_populations.items()})
            row.update({f"death_{k}": v for k, v in r.death_causes.items()})
            rows.append(row)
        return pd.DataFrame(rows)

    def save_summary(self, path: Path | str | None = None) -> Path:
        """Sauvegarde le résumé en CSV."""
        if path is None:
            path = self.out_dir / "sweep_summary.csv"
        path = Path(path)
        df = self.summary_dataframe()
        df.to_csv(path, index=False)
        return path
