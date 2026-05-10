"""
Agrégation statistique pour réplicats EcoSim.

Usage typique :
    from analysis.stats import aggregate_replicates, bootstrap_ci

    # Depuis plusieurs fichiers .db
    results = aggregate_replicates(["runs/rep0.db", "runs/rep1.db", ...])
    print(results)  # mean, std, ci95 par espèce et par tick
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path


def _read_counts(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    rows = []
    for row in conn.execute("SELECT tick, data, eco_metrics FROM counts ORDER BY tick"):
        entry = {"tick": row[0]}
        data_dict = json.loads(row[1] or "{}")
        eco_dict  = json.loads(row[2] or "{}") if row[2] else {}
        entry.update(data_dict)
        entry.update(eco_dict)
        rows.append(entry)
    conn.close()
    return rows


def _read_counts_v2(db_path: Path) -> list[dict]:
    """Version avec row_factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = []
    for row in conn.execute("SELECT tick, data, eco_metrics FROM counts ORDER BY tick"):
        entry = {"tick": row["tick"]}
        entry.update(json.loads(row["data"] or "{}"))
        if row["eco_metrics"]:
            entry.update(json.loads(row["eco_metrics"]))
        rows.append(entry)
    conn.close()
    return rows


def aggregate_replicates(db_paths: list[Path | str],
                          tick_step: int | None = None) -> list[dict]:
    """Agrège les séries temporelles de plusieurs réplicats.

    Retourne une liste de dicts : {tick, mean_X, std_X, ci95_X, ...}
    pour chaque variable numérique présente dans tous les réplicats.
    """
    all_series: list[list[dict]] = []
    for p in db_paths:
        try:
            series = _read_counts_v2(Path(p))
            if series:
                all_series.append(series)
        except Exception as e:
            print(f"[stats] impossible de lire {p} : {e}")

    if not all_series:
        return []

    # Aligner sur les ticks communs
    tick_sets = [set(r["tick"] for r in s) for s in all_series]
    common_ticks = sorted(tick_sets[0].intersection(*tick_sets[1:]))

    if tick_step:
        common_ticks = [t for t in common_ticks if t % tick_step == 0]

    # Index par tick
    indexed = [{r["tick"]: r for r in s} for s in all_series]

    # Collecter les clés numériques
    if not common_ticks:
        return []
    sample_row = indexed[0][common_ticks[0]]
    num_keys = [k for k, v in sample_row.items()
                if k != "tick" and isinstance(v, (int, float)) and v is not None]

    results = []
    for tick in common_ticks:
        entry: dict = {"tick": tick, "n_replicates": len(all_series)}
        for key in num_keys:
            vals = [idx[tick].get(key) for idx in indexed
                    if idx.get(tick) and idx[tick].get(key) is not None]
            if not vals:
                continue
            vals_f = [float(v) for v in vals]
            n = len(vals_f)
            mean = sum(vals_f) / n
            variance = sum((v - mean) ** 2 for v in vals_f) / n if n > 1 else 0.0
            std = math.sqrt(variance)
            sem = std / math.sqrt(n) if n > 0 else 0.0
            entry[f"{key}_mean"] = round(mean, 4)
            entry[f"{key}_std"]  = round(std, 4)
            entry[f"{key}_ci95"] = round(1.96 * sem, 4)
        results.append(entry)

    return results


def bootstrap_ci(values: list[float], n_bootstrap: int = 1000,
                 alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Intervalle de confiance bootstrap (1-alpha) sur la moyenne."""
    import random
    rnd = random.Random(seed)
    n = len(values)
    if n == 0:
        return (float("nan"), float("nan"))
    boot_means = []
    for _ in range(n_bootstrap):
        sample = [rnd.choice(values) for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo = boot_means[int(alpha / 2 * n_bootstrap)]
    hi = boot_means[int((1 - alpha / 2) * n_bootstrap)]
    return (round(lo, 4), round(hi, 4))


def compare_conditions(db_paths_a: list[Path | str],
                        db_paths_b: list[Path | str],
                        metric: str = "H",
                        tick: int | None = None) -> dict:
    """Test de Mann-Whitney U entre deux groupes de réplicats pour une métrique.

    Si tick est None, utilise le dernier tick disponible de chaque série.
    """
    def _get_vals(paths):
        vals = []
        for p in paths:
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            if tick is not None:
                row = conn.execute(
                    "SELECT eco_metrics, data FROM counts WHERE tick=?", (tick,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT eco_metrics, data FROM counts ORDER BY tick DESC LIMIT 1"
                ).fetchone()
            conn.close()
            if not row:
                continue
            eco = json.loads(row["eco_metrics"] or "{}") if row["eco_metrics"] else {}
            data = json.loads(row["data"] or "{}")
            v = eco.get(metric, data.get(metric))
            if v is not None:
                vals.append(float(v))
        return vals

    vals_a = _get_vals(db_paths_a)
    vals_b = _get_vals(db_paths_b)

    if not vals_a or not vals_b:
        return {"error": "données insuffisantes", "metric": metric}

    mean_a = sum(vals_a) / len(vals_a)
    mean_b = sum(vals_b) / len(vals_b)

    # U test simplifié (sans scipy)
    n_a, n_b = len(vals_a), len(vals_b)
    u = sum(1 for a in vals_a for b in vals_b if a > b) + \
        0.5 * sum(1 for a in vals_a for b in vals_b if a == b)
    u_max = n_a * n_b

    return {
        "metric":   metric,
        "mean_a":   round(mean_a, 4),
        "mean_b":   round(mean_b, 4),
        "n_a":      n_a,
        "n_b":      n_b,
        "U":        u,
        "U_norm":   round(u / u_max, 4) if u_max > 0 else None,
    }
