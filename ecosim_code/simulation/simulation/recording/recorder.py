"""
Tâche 2.2 — Recorder SQLite avec keyframes.

Stratégie :
  - Keyframe (WorldSnapshot complet) tous les keyframe_every ticks.
  - Events (naissance/mort) entre deux keyframes.
  - Format : SQLite avec JSON+gzip pour les blobs.

Tables :
  meta(key TEXT, value TEXT)
  keyframes(tick INTEGER PRIMARY KEY, data_blob BLOB)
  events(id INTEGER PRIMARY KEY, tick INTEGER, kind TEXT,
         entity_id INTEGER, payload TEXT)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from simulation.recording.schema import EntitySnapshot, WorldSnapshot, Event

if TYPE_CHECKING:
    from simulation.engine import SimulationEngine


import math as _math


def _compute_eco_metrics(engine) -> dict:
    """Shannon H', Simpson D, biomasse totale, sex ratio, âge moyen."""
    inds = engine.individuals
    if not inds:
        return {"H": 0.0, "D": 0.0, "biomass": 0.0, "sex_ratio": None, "mean_age": 0.0}
    counts = {}
    total_energy = 0.0
    total_age = 0
    n_male = 0
    n_female = 0
    for ind in inds:
        sp = ind.species.name
        counts[sp] = counts.get(sp, 0) + 1
        total_energy += ind.energy
        total_age += ind.age
        sex = getattr(ind, 'sex', '?')
        if sex == 'male':
            n_male += 1
        elif sex == 'female':
            n_female += 1
    total = len(inds)
    H = 0.0
    D_sum = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            H -= p * _math.log(p)
            D_sum += p * p
    sex_ratio = round(n_male / (n_male + n_female), 3) if (n_male + n_female) > 0 else None
    return {
        "H":         round(H, 4),
        "D":         round(1.0 - D_sum, 4),
        "biomass":   round(total_energy, 2),
        "sex_ratio": sex_ratio,
        "mean_age":  round(total_age / total, 1),
        "n_species": len(counts),
    }


class Recorder:
    def __init__(self, path: Path, keyframe_every: int = 500,
                 frame_renderer=None, append: bool = False) -> None:
        """
        frame_renderer : callable(engine, tick) -> bytes | None
            Si fourni, appelé après chaque keyframe pour stocker un PNG pré-rendu.
        append : si True, on ne recrée pas les tables et on repart du dernier tick connu.
        """
        self.path            = path
        self.keyframe_every  = keyframe_every
        self._frame_renderer = frame_renderer
        self._last_keyframe  = -1
        self._conn           = sqlite3.connect(str(path))
        if append:
            row = self._conn.execute(
                "SELECT MAX(tick) FROM keyframes"
            ).fetchone()
            self._last_keyframe = row[0] if row[0] is not None else -1
        else:
            self._init_db()

    # ── Init ─────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        c = self._conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS keyframes (
                tick      INTEGER PRIMARY KEY,
                data_blob BLOB
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tick      INTEGER,
                kind      TEXT,
                entity_id INTEGER,
                payload   TEXT
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_tick ON events(tick)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS renders (
                tick INTEGER PRIMARY KEY,
                png  BLOB
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS counts (
                tick           INTEGER PRIMARY KEY,
                data           TEXT,
                season_metrics TEXT,
                eco_metrics    TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS displacement (
                uid                INTEGER,
                tick               INTEGER,
                x                  REAL,
                y                  REAL,
                cumulative_distance REAL,
                PRIMARY KEY (uid, tick)
            )""")
        # ── Tables de recherche ────────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS individuals (
                uid          INTEGER PRIMARY KEY,
                species      TEXT,
                born_tick    INTEGER,
                parent_a_uid INTEGER DEFAULT -1,
                parent_b_uid INTEGER DEFAULT -1,
                sex          TEXT
            )""")
        c.execute("""
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS pedigree (
                uid          INTEGER PRIMARY KEY,
                parent_a_uid INTEGER DEFAULT -1,
                parent_b_uid INTEGER DEFAULT -1
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_individuals_species ON individuals(species)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_life_history_species ON life_history(species)")
        if not c.execute("SELECT 1 FROM meta WHERE key='run_id'").fetchone():
            c.execute("INSERT INTO meta(key, value) VALUES ('run_id', ?)",
                      (uuid.uuid4().hex[:8],))
        c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version','3')")
        c.commit()

    def write_engine_meta(self, engine: "SimulationEngine") -> None:
        """Écrit les métadonnées du moteur (seed, dimensions, version)."""
        from version import __version__
        self.write_meta("world_width",  str(engine.grid.width))
        self.write_meta("world_height", str(engine.grid.height))
        self.write_meta("seed",         str(getattr(engine, "seed", "?")))
        self.write_meta("engine_version", __version__)

    def write_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value)
        )
        self._conn.commit()

    def write_species_params(self, species_list) -> None:
        """Sérialise tous les paramètres d'espèces en JSON dans meta."""
        import dataclasses
        data = []
        for sp in species_list:
            d = dataclasses.asdict(sp)
            # frozenset n'est pas sérialisable
            if "food_sources" in d:
                d["food_sources"] = list(d["food_sources"])
            data.append(d)
        self.write_meta("species_params", json.dumps(data))

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_tick_end(self, engine: "SimulationEngine") -> None:
        tick = engine.tick_count
        # ── Naissances : events + individuals + pedigree ─────────────────────
        for baby in getattr(engine, '_last_newborns', []):
            uid      = getattr(baby, 'uid', -1)
            pa_uid   = getattr(baby, 'parent_id', -1)
            pb_uid   = getattr(baby, 'parent_b_id', -1)
            self._conn.execute(
                "INSERT OR IGNORE INTO events(tick, kind, entity_id, payload) VALUES (?,?,?,?)",
                (tick, 'birth', uid, json.dumps({
                    'parent_a_uid': pa_uid,
                    'parent_b_uid': pb_uid,
                    'species':      baby.species.name,
                    'x':            round(baby.x, 2),
                    'y':            round(baby.y, 2),
                }, separators=(',', ':')))
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO individuals(uid, species, born_tick, parent_a_uid, parent_b_uid, sex) VALUES (?,?,?,?,?,?)",
                (uid, baby.species.name, tick, pa_uid, pb_uid, getattr(baby, 'sex', '?'))
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO pedigree(uid, parent_a_uid, parent_b_uid) VALUES (?,?,?)",
                (uid, pa_uid, pb_uid)
            )
        # ── Morts : life_history ──────────────────────────────────────────────
        for ind in getattr(engine, '_last_dead', []):
            uid   = getattr(ind, 'uid', -1)
            n_tks = max(1, getattr(ind, '_energy_ticks', 1))
            avg_e = round(getattr(ind, '_energy_sum', ind.energy) / n_tks, 3)
            genome_j = (ind.genome.to_json()
                        if hasattr(ind, 'genome') else "")
            self._conn.execute(
                "INSERT OR REPLACE INTO life_history"
                "(uid, species, born_tick, death_tick, death_cause, n_offspring, lifetime_energy_avg, sex, genome_json)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, ind.species.name,
                 tick - ind.age,  # approximation du tick de naissance
                 tick,
                 getattr(ind, 'death_cause', 'unknown'),
                 getattr(ind, 'n_offspring', 0),
                 avg_e,
                 getattr(ind, 'sex', '?'),
                 genome_j)
            )
        # ── Événements maladie ────────────────────────────────────────────────
        for ev in getattr(engine, '_last_disease_events', []):
            entity_id = ev.get("target_uid", -1)
            self._conn.execute(
                "INSERT INTO events(tick, kind, entity_id, payload) VALUES (?,?,?,?)",
                (tick, ev["type"], entity_id, json.dumps({
                    'disease_name': ev.get("disease", ""),
                    'species':      ev.get("species", ""),
                    'x':            ev.get("x", 0),
                    'y':            ev.get("y", 0),
                    'source_uid':   ev.get("source_uid", -1),
                    'target_uid':   ev.get("target_uid", -1),
                }, separators=(',', ':')))
            )
        if tick - self._last_keyframe >= self.keyframe_every:
            self._write_keyframe(engine, tick)
            self._last_keyframe = tick

    def on_event(self, event: Event) -> None:
        self._conn.execute(
            "INSERT INTO events(tick, kind, entity_id, payload) VALUES (?, ?, ?, ?)",
            (event.tick, event.kind, event.entity_id, json.dumps(event.payload)),
        )

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _write_keyframe(self, engine: "SimulationEngine", tick: int) -> None:
        plants = tuple(
            EntitySnapshot(
                id=id(p), species=p.species.name,
                x=round(p.x, 2), y=round(p.y, 2),
                energy=round(p.energy, 2), age=p.age,
                alive=p.alive, state=getattr(p, "state", "idle"),
            )
            for p in engine.plants
        )
        individuals = tuple(
            EntitySnapshot(
                id=id(i), species=i.species.name,
                x=round(i.x, 2), y=round(i.y, 2),
                energy=round(i.energy, 2), age=i.age,
                alive=i.alive, state=getattr(i, "state", "wander"),
                sex=getattr(i, "sex", "?"),
                genome_json=getattr(i, "genome", None) and i.genome.to_json() or "",
                reproduction_cooldown=getattr(i, "reproduction_cooldown", 0),
                gestation_timer=getattr(i, "gestation_timer", 0),
                infected=bool(getattr(i, "disease_states", None)),
            )
            for i in engine.individuals
        )
        snap = WorldSnapshot(
            tick=tick,
            plants=plants,
            individuals=individuals,
            species_counts=dict(engine.species_counts),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO keyframes(tick, data_blob) VALUES (?, ?)",
            (tick, snap.to_blob()),
        )
        season_val = round(getattr(engine, '_season', 0.0), 4)
        eco = _compute_eco_metrics(engine)
        self._conn.execute(
            "INSERT OR REPLACE INTO counts(tick, data, season_metrics, eco_metrics) VALUES (?,?,?,?)",
            (tick,
             json.dumps(snap.species_counts, separators=(',', ':')),
             json.dumps({"season": season_val}, separators=(',', ':')),
             json.dumps(eco, separators=(',', ':'))),
        )
        # ── Displacement (métriques comportementales) ──────────────────────────
        prev = getattr(self, '_prev_positions', {})
        new_prev = {}
        for ind in engine.individuals:
            uid = getattr(ind, 'uid', None)
            if uid is None:
                continue
            px, py = prev.get(uid, (ind.x, ind.y))
            dist = getattr(ind, '_cumulative_distance', 0.0) + ((ind.x - px)**2 + (ind.y - py)**2)**0.5
            ind._cumulative_distance = dist
            new_prev[uid] = (ind.x, ind.y)
            self._conn.execute(
                "INSERT OR REPLACE INTO displacement(uid, tick, x, y, cumulative_distance) VALUES (?,?,?,?,?)",
                (uid, tick, round(ind.x, 2), round(ind.y, 2), round(dist, 3))
            )
        self._prev_positions = new_prev

        # PNG pré-rendu (si renderer fourni)
        if self._frame_renderer is not None:
            try:
                png = self._frame_renderer(engine, tick)
                if png:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO renders(tick, png) VALUES (?, ?)",
                        (tick, png),
                    )
            except Exception:
                pass  # ne jamais bloquer la simulation

        self._conn.commit()
