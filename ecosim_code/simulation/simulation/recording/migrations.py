"""
Migrations du schéma SQLite EcoSim.

Chaque version introduit les tables/colonnes manquantes de façon idempotente.
Appelé automatiquement par ReplayReader et Recorder au chargement d'un .db.
"""
from __future__ import annotations
import sqlite3


CURRENT_SCHEMA_VERSION = 3


def _get_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 1
    except Exception:
        return 1


def migrate(conn: sqlite3.Connection) -> None:
    """Applique toutes les migrations nécessaires jusqu'à CURRENT_SCHEMA_VERSION."""
    v = _get_version(conn)
    if v < 2:
        _migrate_v1_to_v2(conn)
    if v < 3:
        _migrate_v2_to_v3(conn)
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('schema_version',?)",
                 (str(CURRENT_SCHEMA_VERSION),))
    conn.commit()


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2 : ajout des tables individuals, life_history, pedigree."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS individuals (
            uid          INTEGER PRIMARY KEY,
            species      TEXT,
            born_tick    INTEGER,
            parent_a_uid INTEGER DEFAULT -1,
            parent_b_uid INTEGER DEFAULT -1,
            sex          TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_history (
            uid                 INTEGER PRIMARY KEY,
            species             TEXT,
            born_tick           INTEGER,
            death_tick          INTEGER,
            death_cause         TEXT,
            n_offspring         INTEGER DEFAULT 0,
            lifetime_energy_avg REAL,
            sex                 TEXT,
            genome_json         TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pedigree (
            uid          INTEGER PRIMARY KEY,
            parent_a_uid INTEGER DEFAULT -1,
            parent_b_uid INTEGER DEFAULT -1
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_individuals_species ON individuals(species)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_life_history_species ON life_history(species)")
    # Ajouter colonne counts.season si elle n'existe pas
    try:
        conn.execute("ALTER TABLE counts ADD COLUMN season_metrics TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """v2 → v3 : eco_metrics dans counts + table displacement."""
    try:
        conn.execute("ALTER TABLE counts ADD COLUMN eco_metrics TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS displacement (
            uid                INTEGER,
            tick               INTEGER,
            x                  REAL,
            y                  REAL,
            cumulative_distance REAL,
            PRIMARY KEY (uid, tick)
        )""")
