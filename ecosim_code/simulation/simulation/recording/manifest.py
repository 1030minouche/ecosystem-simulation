"""
Manifeste d'expérience EcoSim.

Regroupe tout ce qu'il faut pour reproduire une simulation exactement :
version du code, seed, paramètres terrain, espèces, maladies.
Stocké en JSON dans la table meta sous la clé 'experiment_manifest'.
"""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
            cwd=Path(__file__).parent,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _python_version() -> str:
    return platform.python_version()


def build_manifest(
    seed: int | None,
    grid_size: int,
    terrain_preset: str,
    terrain_params: dict,
    ticks: int,
    species_list: list,
    diseases: list | None = None,
    experiment_name: str = "",
    hypothesis: str = "",
    protocol: str = "",
    tags: list[str] | None = None,
) -> dict:
    """Construit le dictionnaire manifeste de l'expérience."""
    try:
        from version import __version__ as ecosim_version
    except ImportError:
        ecosim_version = "unknown"

    species_data = []
    for sp in species_list:
        import dataclasses
        d = dataclasses.asdict(sp)
        if "food_sources" in d and isinstance(d["food_sources"], (set, frozenset)):
            d["food_sources"] = list(d["food_sources"])
        species_data.append(d)

    return {
        "ecosim_version":  ecosim_version,
        "git_hash":        _git_hash(),
        "python_version":  _python_version(),
        "created_at":      datetime.now(timezone.utc).isoformat(),
        "seed":            seed,
        "grid_size":       grid_size,
        "terrain_preset":  terrain_preset,
        "terrain_params":  terrain_params,
        "ticks":           ticks,
        "species":         species_data,
        "diseases":        diseases or [],
        # Métadonnées de recherche
        "experiment_name": experiment_name,
        "hypothesis":      hypothesis,
        "protocol":        protocol,
        "tags":            tags or [],
    }


def write_manifest(recorder, manifest: dict) -> None:
    """Sérialise et stocke le manifeste dans la table meta du recorder."""
    recorder.write_meta("experiment_manifest", json.dumps(manifest, separators=(",", ":")))


def read_manifest(db_path: Path) -> dict | None:
    """Lit le manifeste depuis un fichier .db existant."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        row  = conn.execute(
            "SELECT value FROM meta WHERE key='experiment_manifest'"
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception:
        return None
