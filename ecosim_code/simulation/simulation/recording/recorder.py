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
from pathlib import Path
from typing import TYPE_CHECKING

from simulation.recording.schema import EntitySnapshot, WorldSnapshot, Event

if TYPE_CHECKING:
    from simulation.engine import SimulationEngine


class Recorder:
    def __init__(self, path: Path, keyframe_every: int = 500,
                 frame_renderer=None) -> None:
        """
        frame_renderer : callable(engine, tick) -> bytes | None
            Si fourni, appelé après chaque keyframe pour stocker un PNG pré-rendu.
        """
        self.path            = path
        self.keyframe_every  = keyframe_every
        self._frame_renderer = frame_renderer
        self._last_keyframe  = -1
        self._conn           = sqlite3.connect(str(path))
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

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_tick_end(self, engine: "SimulationEngine") -> None:
        tick = engine.tick_count
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
