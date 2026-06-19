"""
Smoke tests pour la couche web : assemblage de l'app aiohttp et helpers
synchrones de routes_analyse contre un .db SQLite minimal.

Pas de test end-to-end HTTP (aiohttp.test_utils nécessite asyncio + event
loop). On vérifie que :
  - `_build_app()` enregistre les routes attendues sans erreur.
  - `read_timeseries`, `_read_stats`, `_read_epidemic` retournent des
    structures cohérentes face à un .db connu (tables vides + tables
    pleines).
"""
import gzip
import json
import sqlite3

import pytest


def _create_minimal_db(path) -> None:
    """Crée un .db SQLite avec les tables que routes_analyse sait lire."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE counts(tick INTEGER PRIMARY KEY, data TEXT, eco_metrics TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY, tick INTEGER, kind TEXT,
                            entity_id INTEGER, payload TEXT);
        CREATE TABLE keyframes(tick INTEGER PRIMARY KEY, data_blob BLOB);
    """)
    conn.executemany(
        "INSERT INTO counts(tick, data, eco_metrics) VALUES (?, ?, ?)",
        [
            (0,   json.dumps({"Lapin": 10, "Renard": 2}), None),
            (100, json.dumps({"Lapin": 12, "Renard": 3}), json.dumps({"H": 0.9})),
            (200, json.dumps({"Lapin": 15, "Renard": 1}), None),
        ],
    )
    conn.executemany(
        "INSERT INTO events(tick, kind, entity_id, payload) VALUES (?, ?, ?, ?)",
        [
            (50,  "birth", 1, json.dumps({"species": "Lapin", "parent_id": 0})),
            (75,  "birth", 2, json.dumps({"species": "Lapin", "parent_id": 0})),
            (150, "birth", 3, json.dumps({"species": "Renard", "parent_id": 0})),
            (180, "disease_infection", 1, json.dumps({
                "disease_name": "myxo", "species": "Lapin", "source_uid": -1
            })),
        ],
    )
    # Keyframe sentinelle pour le fallback de read_timeseries
    payload = json.dumps({"species_counts": {"Lapin": 10}}).encode("utf-8")
    conn.execute("INSERT INTO keyframes(tick, data_blob) VALUES (?, ?)",
                 (0, gzip.compress(payload)))
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path):
    p = tmp_path / "fixture.db"
    _create_minimal_db(p)
    return str(p)


def test_build_app_registers_all_routes():
    """L'app aiohttp doit avoir toutes les routes attendues."""
    from web.server import _build_app
    app = _build_app()
    paths = {r.canonical for r in app.router.resources()}
    # Quelques routes critiques
    assert "/" in paths
    assert "/api/sim/start" in paths
    assert "/api/sim/cancel" in paths
    assert "/api/analyse/timeseries" in paths
    assert "/api/analyse/epidemic" in paths
    assert "/api/replay/genetics" in paths
    assert "/api/replay/heatmap" in paths
    assert "/ws" in paths


def test_read_timeseries_returns_counts_in_order(fixture_db):
    """read_timeseries reconstruit la table counts en ordre tick croissant."""
    from web.routes_analyse import read_timeseries
    rows = read_timeseries(fixture_db)
    assert len(rows) == 3
    assert [r["tick"] for r in rows] == [0, 100, 200]
    assert rows[0]["counts"] == {"Lapin": 10, "Renard": 2}
    # eco_metrics quand présent
    assert rows[1]["eco"]["H"] == 0.9


def test_read_stats_aggregates_births_and_max_pops(fixture_db):
    from web.routes_analyse import _read_stats
    s = _read_stats(fixture_db)
    assert s["births_by_species"]["Lapin"] == 2
    assert s["births_by_species"]["Renard"] == 1
    assert s["max_populations"]["Lapin"] == 15
    assert s["max_populations"]["Renard"] == 3


def test_read_epidemic_counts_infections(fixture_db):
    from web.routes_analyse import _read_epidemic
    epi = _read_epidemic(fixture_db)
    assert epi["total_infections"] == 1
    assert epi["diseases"] == ["myxo"]
    assert epi["cumulative"]["myxo"] == 1


def test_read_timeseries_on_empty_db_returns_keyframes_fallback(tmp_path):
    """Quand la table counts est vide, read_timeseries fallback sur keyframes."""
    p = tmp_path / "empty_counts.db"
    _create_minimal_db(p)
    conn = sqlite3.connect(p)
    conn.execute("DELETE FROM counts")
    conn.commit()
    conn.close()
    from web.routes_analyse import read_timeseries
    rows = read_timeseries(str(p))
    assert len(rows) == 1
    assert rows[0]["tick"] == 0
    assert rows[0]["counts"] == {"Lapin": 10}
