"""
Mode headless : boucle synchrone sans GUI, aussi vite que possible.

Utilisé par `python -m simulation.main --headless --ticks N [--seed S]
[--config path] [--out path] [--progress]`.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.runner import RunSummary


def run_headless(
    ticks: int,
    seed: int | None,
    config_path: str | None,
    out_path: str | None,
    progress: bool,
) -> "RunSummary":
    """Lance la simulation en mode headless et retourne un RunSummary."""
    from world.grid import Grid
    from world.terrain import generate_terrain
    from simulation.engine import SimulationEngine
    from simulation.runner import EngineRunner

    # ── Terrain ──────────────────────────────────────────────────────────────
    grid = Grid(width=500, height=500)
    generate_terrain(grid, seed=seed if seed is not None else 42)

    # ── Moteur ───────────────────────────────────────────────────────────────
    engine = SimulationEngine(grid, seed=seed)
    effective_seed = seed if seed is not None else engine.seed
    print(f"[headless] seed={effective_seed}  ticks={ticks}", flush=True)

    # ── Espèces ───────────────────────────────────────────────────────────────
    if config_path:
        _load_species_from_dir(engine, config_path)
    else:
        _load_default_species(engine)

    # ── Recorder (optionnel, Phase 2) ─────────────────────────────────────────
    recorder = None
    if out_path:
        try:
            from simulation.recording.recorder import Recorder
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            recorder = Recorder(Path(out_path))
            print(f"[headless] enregistrement -> {out_path}", flush=True)
            recorder.write_engine_meta(engine)
        except ImportError:
            print("[headless] WARNING: module recording non disponible, --out ignoré",
                  flush=True)

    # ── Barre de progression ──────────────────────────────────────────────────
    def on_progress(tick: int, species_counts: dict) -> None:
        if not progress:
            return
        elapsed  = time.monotonic() - _t0
        done     = tick - _start_tick
        pct      = done / ticks * 100
        alive    = sum(species_counts.values())
        print(
            f"  {done:>7}/{ticks} ticks  ({pct:5.1f}%)  "
            f"entites={alive}  t={elapsed:.1f}s",
            flush=True,
        )

    _t0         = time.monotonic()
    _start_tick = engine.tick_count

    runner = EngineRunner(engine, recorder=recorder)
    summary = runner.run(max_ticks=ticks, on_progress=on_progress)

    if recorder is not None:
        recorder.close()

    # ── Résumé final ──────────────────────────────────────────────────────────
    _print_summary(summary)
    return summary


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_default_species(engine) -> None:
    species_dir = os.path.join(os.path.dirname(__file__), "..", "species")
    for path in sorted(glob.glob(os.path.join(species_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        params = spec["params"]
        params["color"] = tuple(params["color"])
        engine.add_species(params, count=spec["count"])


def _load_species_from_dir(engine, path: str) -> None:
    if os.path.isdir(path):
        for fpath in sorted(glob.glob(os.path.join(path, "*.json"))):
            with open(fpath, encoding="utf-8") as f:
                spec = json.load(f)
            params = spec["params"]
            params["color"] = tuple(params["color"])
            engine.add_species(params, count=spec["count"])
    else:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        params = spec.get("params", spec)
        if "color" in params:
            params["color"] = tuple(params["color"])
        engine.add_species(params, count=spec.get("count", 20))


def _print_summary(summary: "RunSummary") -> None:
    print("\n" + "=" * 55)
    print(f"  Simulation terminée")
    print(f"  Ticks simulés  : {summary.ticks_done}")
    print(f"  Durée réelle   : {summary.elapsed_s:.2f} s")
    if summary.elapsed_s > 0:
        print(f"  Ticks/s        : {summary.ticks_done / summary.elapsed_s:.0f}")
    print(f"\n  Populations finales :")
    for sp, n in sorted(summary.final_populations.items()):
        print(f"    {sp:<25} {n}")
    if summary.death_causes:
        print(f"\n  Causes de mort :")
        for cause, n in sorted(summary.death_causes.items(), key=lambda x: -x[1]):
            print(f"    {cause:<25} {n}")
    print("=" * 55 + "\n")
