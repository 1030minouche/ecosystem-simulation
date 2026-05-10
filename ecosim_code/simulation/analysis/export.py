"""
Export tabulaire depuis un fichier .db EcoSim vers CSV (ou Parquet si disponible).

Fonctions disponibles :
    export_all(db_path, out_dir)         — tout exporter en une commande
    export_populations(db_path, out_dir) — counts tick par tick
    export_life_history(db_path, out_dir)
    export_genetics(db_path, out_dir)    — génomes + métriques par tick
    export_events(db_path, out_dir)
    export_displacement(db_path, out_dir)
    export_spatial(db_path, out_dir)     — positions individus par keyframe
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _write_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        out_path.write_text("")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _try_parquet(rows: list[dict], out_path: Path) -> bool:
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        df.to_parquet(out_path.with_suffix(".parquet"), index=False)
        return True
    except ImportError:
        return False


def export_populations(db_path: Path, out_dir: Path) -> Path:
    """Exporte counts tick par tick avec métriques écologiques."""
    conn = _connect(db_path)
    rows = []
    for row in conn.execute("SELECT tick, data, season_metrics, eco_metrics FROM counts ORDER BY tick"):
        counts = json.loads(row["data"] or "{}")
        season_m = json.loads(row["season_metrics"] or "{}") if row["season_metrics"] else {}
        eco_m    = json.loads(row["eco_metrics"]    or "{}") if row["eco_metrics"]    else {}
        entry = {"tick": row["tick"]}
        entry.update(counts)
        entry.update(season_m)
        entry.update(eco_m)
        rows.append(entry)
    conn.close()
    out = out_dir / "populations.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_life_history(db_path: Path, out_dir: Path) -> Path:
    """Exporte la table life_history complète."""
    conn = _connect(db_path)
    rows = [dict(r) for r in conn.execute(
        "SELECT uid, species, born_tick, death_tick, death_cause, "
        "n_offspring, lifetime_energy_avg, sex FROM life_history ORDER BY uid"
    )]
    conn.close()
    out = out_dir / "life_history.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_genetics(db_path: Path, out_dir: Path) -> Path:
    """Exporte les génomes depuis life_history + métriques He, π agrégées."""
    conn = _connect(db_path)
    rows = []
    for row in conn.execute(
        "SELECT uid, species, sex, born_tick, death_tick, genome_json FROM life_history WHERE genome_json != '' ORDER BY uid"
    ):
        try:
            genome_data = json.loads(row["genome_json"])
        except Exception:
            continue
        genes = genome_data.get("g", []) if isinstance(genome_data, dict) else genome_data
        entry = {
            "uid":        row["uid"],
            "species":    row["species"],
            "sex":        row["sex"],
            "born_tick":  row["born_tick"],
            "death_tick": row["death_tick"],
        }
        for i, g in enumerate(genes):
            entry[f"gene_{i}"] = round(g, 5)
        rows.append(entry)
    conn.close()
    out = out_dir / "genetics.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_events(db_path: Path, out_dir: Path) -> Path:
    """Exporte la table events (naissances, morts, maladies)."""
    conn = _connect(db_path)
    rows = []
    for row in conn.execute(
        "SELECT tick, kind, entity_id, payload FROM events ORDER BY tick, id"
    ):
        payload = json.loads(row["payload"] or "{}") if row["payload"] else {}
        entry = {"tick": row["tick"], "kind": row["kind"], "entity_id": row["entity_id"]}
        entry.update(payload)
        rows.append(entry)
    conn.close()
    out = out_dir / "events.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_displacement(db_path: Path, out_dir: Path) -> Path:
    """Exporte les déplacements cumulés par individu."""
    conn = _connect(db_path)
    # Prend la dernière position connue de chaque individu (déplacement total)
    rows = [dict(r) for r in conn.execute(
        "SELECT d.uid, lh.species, d.tick, d.x, d.y, d.cumulative_distance "
        "FROM displacement d LEFT JOIN life_history lh ON d.uid = lh.uid "
        "ORDER BY d.uid, d.tick"
    )]
    conn.close()
    out = out_dir / "displacement.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_spatial(db_path: Path, out_dir: Path) -> Path:
    """Exporte les positions de tous les individus pour chaque keyframe."""
    conn = _connect(db_path)
    rows = []
    for row in conn.execute("SELECT tick, data_blob FROM keyframes ORDER BY tick"):
        import gzip
        try:
            data = json.loads(gzip.decompress(row["data_blob"]))
        except Exception:
            continue
        for ind in data.get("individuals", []):
            rows.append({
                "tick":    row["tick"],
                "species": ind.get("species"),
                "x":       ind.get("x"),
                "y":       ind.get("y"),
                "energy":  ind.get("energy"),
                "age":     ind.get("age"),
                "sex":     ind.get("sex", "?"),
                "alive":   ind.get("alive"),
            })
    conn.close()
    out = out_dir / "spatial.csv"
    _write_csv(rows, out)
    _try_parquet(rows, out)
    return out


def export_all(db_path: Path | str, out_dir: Path | str | None = None) -> dict[str, Path]:
    """Exporte toutes les tables disponibles. Retourne un dict nom→chemin."""
    db_path = Path(db_path)
    if out_dir is None:
        out_dir = db_path.parent / (db_path.stem + "_export")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    exporters = [
        ("populations",  export_populations),
        ("life_history", export_life_history),
        ("genetics",     export_genetics),
        ("events",       export_events),
        ("displacement", export_displacement),
        ("spatial",      export_spatial),
    ]
    for name, fn in exporters:
        try:
            results[name] = fn(db_path, out_dir)
        except Exception as e:
            print(f"[export] {name} ignoré : {e}")
    return results
