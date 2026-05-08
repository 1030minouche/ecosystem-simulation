"""
Tâche 2.1 — Modèle de données pour le recorder.

Dataclasses sérialisables représentant l'état du monde à un instant T
et les événements discrets (naissance, mort, déplacement).
"""

from __future__ import annotations

import json
import gzip
from dataclasses import dataclass, asdict
from typing import Literal


@dataclass(frozen=True)
class EntitySnapshot:
    id: int
    species: str
    x: float
    y: float
    energy: float
    age: int
    alive: bool
    state: str
    sex: str = "?"
    genome_json: str = ""
    reproduction_cooldown: int = 0
    gestation_timer: int = 0


@dataclass(frozen=True)
class WorldSnapshot:
    tick: int
    plants: tuple[EntitySnapshot, ...]
    individuals: tuple[EntitySnapshot, ...]
    species_counts: dict[str, int]

    def to_blob(self) -> bytes:
        """Sérialise en JSON + gzip."""
        data = {
            "tick":           self.tick,
            "plants":         [asdict(e) for e in self.plants],
            "individuals":    [asdict(e) for e in self.individuals],
            "species_counts": self.species_counts,
        }
        return gzip.compress(json.dumps(data, separators=(",", ":")).encode())

    @classmethod
    def from_blob(cls, blob: bytes) -> "WorldSnapshot":
        data = json.loads(gzip.decompress(blob))

        def _es(d: dict) -> EntitySnapshot:
            return EntitySnapshot(
                id=d["id"], species=d["species"],
                x=d["x"], y=d["y"],
                energy=d["energy"], age=d["age"],
                alive=d["alive"], state=d["state"],
                sex=d.get("sex", "?"),
                genome_json=d.get("genome_json", ""),
                reproduction_cooldown=d.get("reproduction_cooldown", 0),
                gestation_timer=d.get("gestation_timer", 0),
            )

        return cls(
            tick=data["tick"],
            plants=tuple(_es(e) for e in data["plants"]),
            individuals=tuple(_es(e) for e in data["individuals"]),
            species_counts=data["species_counts"],
        )


@dataclass(frozen=True)
class Event:
    tick: int
    kind: Literal["birth", "death", "move"]
    entity_id: int
    payload: dict

    def to_json(self) -> str:
        return json.dumps({"tick": self.tick, "kind": self.kind,
                           "entity_id": self.entity_id, "payload": self.payload},
                          separators=(",", ":"))

    @classmethod
    def from_json(cls, s: str) -> "Event":
        d = json.loads(s)
        return cls(**d)
