"""
Tests directs de SpatialGrid après l'étape 2 du plan de vectorisation :
- `insert(x, y, idx)` stocke des indices entiers
- `query` et `query_radius` renvoient des np.ndarray[int32]
- le "set d'entités" recouvert reste identique (ordre indifférent)
- `query_radius` filtre le cercle exact, `query` la bounding box.
"""
from __future__ import annotations

import numpy as np

from ecosim.world.spatial_grid import SpatialGrid


def test_empty_grid_returns_empty_int32_array():
    g = SpatialGrid(cell_size=8.0)
    out = g.query(0.0, 0.0, 5.0)
    assert isinstance(out, np.ndarray)
    assert out.size == 0
    assert out.dtype == np.int32


def test_insert_then_query_returns_indices():
    g = SpatialGrid(cell_size=8.0)
    g.insert(10.0, 10.0, 0)
    g.insert(50.0, 50.0, 1)
    g.insert(11.0, 11.0, 2)
    res = g.query(10.5, 10.5, 5.0)
    assert sorted(res.tolist()) == [0, 2]
    res2 = g.query(50.0, 50.0, 1.0)
    assert res2.tolist() == [1]


def test_query_dtype_is_int32():
    g = SpatialGrid(cell_size=8.0)
    for i in range(10):
        g.insert(float(i), float(i), i)
    res = g.query(5.0, 5.0, 20.0)
    assert res.dtype == np.int32


def test_query_radius_filters_circle_strictly():
    """Bounding box vs cercle : un point à (5, 0) est dans le carré [-3..3]
    autour de (0,0) mais pas dans le cercle r=3."""
    g = SpatialGrid(cell_size=4.0)
    g.insert(0.0, 0.0, 0)
    g.insert(3.5, 3.5, 1)  # distance ~4.95 > 4 → hors cercle
    g.insert(2.0, 2.0, 2)  # distance ~2.83 < 4 → dans le cercle

    box = sorted(g.query(0.0, 0.0, 4.0).tolist())
    assert box == [0, 1, 2]

    circle = sorted(g.query_radius(0.0, 0.0, 4.0).tolist())
    assert circle == [0, 2]


def test_clear_resets_storage():
    g = SpatialGrid(cell_size=8.0)
    g.insert(10.0, 10.0, 0)
    assert g.query(10.0, 10.0, 1.0).tolist() == [0]
    g.clear()
    assert g.query(10.0, 10.0, 1.0).size == 0


def test_query_after_engine_tick_consistent():
    """Après quelques ticks, les indices renvoyés par query résolvent vers
    des individus vivants de engine.individuals — invariant clé pour le
    matérialisation côté moteur."""
    from ecosim.engine.engine import SimulationEngine
    from ecosim.world.grid import Grid

    grid = Grid(40, 40)
    grid.soil_type[:] = "clay"
    grid.temperature[:] = 20.0
    grid.humidity[:] = 0.5
    grid.altitude[:] = 0.5
    eng = SimulationEngine(grid, seed=42)
    eng.add_species({
        "name": "Herbe", "type": "plant",
        "color": (0.2, 0.8, 0.1),
        "temp_min": 5.0, "temp_max": 28.0,
        "humidity_min": 0.25, "humidity_max": 1.0,
        "altitude_min": 0.0, "altitude_max": 1.0,
        "reproduction_rate": 0.8, "max_age": 876_000,
        "max_population": 10_000, "energy_start": 100.0,
        "energy_consumption": 0.0, "energy_from_food": 0.0,
        "speed": 0.0, "perception_radius": 0.0, "food_sources": [],
        "growth_rate": 3e-5, "dispersal_radius": 6,
        "activity_pattern": "diurnal", "can_swim": False,
        "reproduction_cooldown_length": 1200,
        "litter_size_min": 1, "litter_size_max": 4,
        "sexual_maturity_ticks": 0, "gestation_ticks": 0,
        "juvenile_mortality_rate": 0.0, "fear_factor": 0.0,
    }, count=15)
    for _ in range(20):
        eng.tick()

    eng._plant_grid.clear()
    for j, p in enumerate(eng.plants):
        eng._plant_grid.insert(p.x, p.y, j)
    centroid = eng.plants[len(eng.plants) // 2]
    idx = eng._plant_grid.query(centroid.x, centroid.y, 50.0)
    # Tous les indices sont valides, distincts, et désignent les plantes courantes
    assert idx.dtype == np.int32
    assert len(set(idx.tolist())) == len(idx)
    for k in idx:
        assert 0 <= int(k) < len(eng.plants)
