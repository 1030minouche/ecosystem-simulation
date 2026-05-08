"""
Module de reprise de simulation depuis un fichier .db existant.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.engine import SimulationEngine


def load_engine_from_db(db_path: Path) -> "SimulationEngine":
    """
    Reconstruit un SimulationEngine depuis la dernière keyframe d'un .db.
    Retourne le moteur prêt à tourner depuis le tick suivant.
    """
    import sqlite3
    from world.grid import Grid
    from world.terrain import generate_terrain
    from simulation.engine import SimulationEngine
    from entities.animal import Individual
    from entities.plant import Plant
    from entities.genetics import Genome
    from entities.species import Species

    conn = sqlite3.connect(str(db_path))
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())

    width  = int(meta.get("world_width", 500))
    height = int(meta.get("world_height", 500))
    seed   = int(meta.get("seed", 0))
    preset = meta.get("terrain_preset", "default")

    grid = Grid(width=width, height=height)
    generate_terrain(grid, seed=seed, preset=preset)

    engine = SimulationEngine(grid, seed=seed)

    # Reconstruire les espèces
    species_map: dict[str, Species] = {}
    species_json = meta.get("species_params", "[]")
    for sd in json.loads(species_json):
        valid = {k: v for k, v in sd.items()
                 if k in Species.__dataclass_fields__}
        if "food_sources" in valid:
            valid["food_sources"] = list(valid["food_sources"])
        if "color" in valid and isinstance(valid["color"], list):
            valid["color"] = tuple(valid["color"])
        sp = Species(**valid)
        species_map[sp.name] = sp
        engine._registry.species_list.append(sp)
        engine._registry._species_counts[sp.name] = 0

    # Charger la dernière keyframe
    row = conn.execute(
        "SELECT tick, data_blob FROM keyframes ORDER BY tick DESC LIMIT 1"
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"Aucune keyframe trouvée dans {db_path}")

    from simulation.recording.schema import WorldSnapshot
    snap = WorldSnapshot.from_blob(row[1])
    engine.tick_count = snap.tick

    # Reconstruire les plantes
    for es in snap.plants:
        sp = species_map.get(es.species)
        if sp and es.alive:
            p = Plant(species=sp, x=es.x, y=es.y)
            p.energy = es.energy
            p.age    = es.age
            engine.plants.append(p)
            engine._registry._species_counts[sp.name] = (
                engine._registry._species_counts.get(sp.name, 0) + 1
            )

    # Reconstruire les individus
    for es in snap.individuals:
        sp = species_map.get(es.species)
        if sp and es.alive:
            ind = Individual(species=sp, x=es.x, y=es.y)
            ind.energy = es.energy
            ind.age    = es.age
            ind.state  = es.state
            ind.sex    = getattr(es, "sex", "?")
            ind.reproduction_cooldown = getattr(es, "reproduction_cooldown", 0)
            ind.gestation_timer       = getattr(es, "gestation_timer", 0)
            gj = getattr(es, "genome_json", "")
            if gj:
                ind.genome = Genome.from_json(gj)
                ind._refresh_effective_params()
            engine.individuals.append(ind)
            engine._registry._species_counts[sp.name] = (
                engine._registry._species_counts.get(sp.name, 0) + 1
            )

    conn.close()
    return engine
