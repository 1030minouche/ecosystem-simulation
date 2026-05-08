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
                tick INTEGER PRIMARY KEY,
                data TEXT
            )""")
        if not c.execute("SELECT 1 FROM meta WHERE key='run_id'").fetchone():
            c.execute("INSERT INTO meta(key, value) VALUES ('run_id', ?)",
                      (uuid.uuid4().hex[:8],))
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
        # Enregistre les naissances (généalogie)
        for baby in getattr(engine, '_last_newborns', []):
            self._conn.execute(
                "INSERT INTO events(tick, kind, entity_id, payload) VALUES (?,?,?,?)",
                (tick, 'birth', id(baby), json.dumps({
                    'parent_id': getattr(baby, 'parent_id', -1),
                    'species':   baby.species.name,
                    'x':         round(baby.x, 2),
                    'y':         round(baby.y, 2),
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
        self._conn.execute(
            "INSERT OR REPLACE INTO counts(tick, data) VALUES (?,?)",
            (tick, json.dumps(snap.species_counts, separators=(',', ':'))),
        )

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
