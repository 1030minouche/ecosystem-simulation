"""
Métriques épidémiologiques pour EcoSim.

R₀ empirique : nombre moyen de nouvelles infections causées par un individu
infectieux pendant toute sa période contagieuse.

Usage :
    from analysis.epidemiology import compute_R0
    r0 = compute_R0("runs/sim.db", disease_name="grippe")
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def compute_R0(db_path: Path | str, disease_name: str | None = None,
               min_ticks: int = 0, max_ticks: int | None = None) -> dict:
    """Calcule R₀ empirique depuis un fichier .db enregistré.

    Méthode : pour chaque source_uid distinct, compte le nombre de cibles
    uniques infectées. R₀ = moyenne sur tous les infectieux primaires.

    Paramètres
    ----------
    db_path      : chemin vers le fichier .db
    disease_name : filtrer par maladie (None = toutes)
    min_ticks    : ignorer les ticks avant ce seuil
    max_ticks    : ignorer les ticks après ce seuil

    Retourne un dict avec R0, n_sources, n_infections, disease.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = "SELECT tick, payload FROM events WHERE kind='disease_infection'"
    params: list = []
    if min_ticks > 0:
        query += " AND tick >= ?"
        params.append(min_ticks)
    if max_ticks is not None:
        query += " AND tick <= ?"
        params.append(max_ticks)

    sources: dict[int, set[int]] = {}
    total = 0
    for row in conn.execute(query, params):
        try:
            payload = json.loads(row["payload"])
        except Exception:
            continue
        if disease_name and payload.get("disease_name") != disease_name:
            continue
        src  = payload.get("source_uid", -1)
        tgt  = payload.get("target_uid", -1)
        if src < 0 or tgt < 0:
            continue
        sources.setdefault(src, set()).add(tgt)
        total += 1

    conn.close()

    if not sources:
        return {
            "disease":      disease_name or "all",
            "R0":           None,
            "n_sources":    0,
            "n_infections": 0,
        }

    counts = [len(v) for v in sources.values()]
    r0 = sum(counts) / len(counts)

    return {
        "disease":      disease_name or "all",
        "R0":           round(r0, 4),
        "R0_median":    sorted(counts)[len(counts) // 2],
        "R0_max":       max(counts),
        "n_sources":    len(sources),
        "n_infections": total,
    }


def infection_timeseries(db_path: Path | str,
                          disease_name: str | None = None,
                          bin_size: int = 500) -> list[dict]:
    """Retourne le nombre de nouvelles infections par bin de ticks."""
    conn = sqlite3.connect(str(db_path))
    bins: dict[int, int] = {}
    for row in conn.execute(
        "SELECT tick, payload FROM events WHERE kind='disease_infection'"
    ):
        try:
            payload = json.loads(row["payload"])
        except Exception:
            continue
        if disease_name and payload.get("disease_name") != disease_name:
            continue
        b = (row["tick"] // bin_size) * bin_size
        bins[b] = bins.get(b, 0) + 1
    conn.close()
    return [{"tick": k, "new_infections": v} for k, v in sorted(bins.items())]
