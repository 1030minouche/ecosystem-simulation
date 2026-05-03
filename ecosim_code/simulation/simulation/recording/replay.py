"""
Tâche 3.1 — ReplayReader : reconstruit l'état du monde à un tick donné.

Algorithme :
  1. Trouver la keyframe <= tick
  2. Charger son WorldSnapshot
  3. (Les events ne modifient pas directement le WorldSnapshot,
      ils seront utilisés par le viewer pour les overlays)
  Cache LRU du dernier état reconstruit pour accélérer le scrub séquentiel.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from simulation.recording.schema import WorldSnapshot


class ReplayReader:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._keyframe_ticks: list[int] = self._load_keyframe_ticks()

    def _load_keyframe_ticks(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT tick FROM keyframes ORDER BY tick"
        ).fetchall()
        return [r[0] for r in rows]

    @property
    def total_ticks(self) -> int:
        """Tick maximum enregistré (dernière keyframe)."""
        if not self._keyframe_ticks:
            return 0
        return self._keyframe_ticks[-1]

    @property
    def min_tick(self) -> int:
        if not self._keyframe_ticks:
            return 0
        return self._keyframe_ticks[0]

    @property
    def meta(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM meta").fetchall()
        return dict(rows)

    def state_at(self, tick: int) -> WorldSnapshot | None:
        """Retourne le WorldSnapshot reconstruit le plus proche de tick (≤ tick)."""
        if not self._keyframe_ticks:
            return None
        kf_tick = self._best_keyframe(tick)
        return self._load_keyframe(kf_tick)

    def close(self) -> None:
        self._conn.close()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _best_keyframe(self, tick: int) -> int:
        """Trouve la keyframe <= tick par recherche dichotomique."""
        ticks = self._keyframe_ticks
        lo, hi = 0, len(ticks) - 1
        best = ticks[0]
        while lo <= hi:
            mid = (lo + hi) // 2
            if ticks[mid] <= tick:
                best = ticks[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    @lru_cache(maxsize=8)
    def _load_keyframe(self, tick: int) -> WorldSnapshot:
        row = self._conn.execute(
            "SELECT data_blob FROM keyframes WHERE tick = ?", (tick,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Keyframe tick={tick} introuvable")
        return WorldSnapshot.from_blob(row[0])
