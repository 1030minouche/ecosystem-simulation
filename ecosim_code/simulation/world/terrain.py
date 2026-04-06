import os
import json
import numpy as np
from noise import pnoise2
from world.grid import Grid

_LAKE_WATER_LEVEL = 0.20
_WATER_THRESHOLD  = 0.30
_ROCK_THRESHOLD   = 0.80

_BIOME_ALTITUDES = {
    "water":  0.15,
    "sand":   0.36,
    "plain":  0.50,
    "forest": 0.55,
    "rock":   0.83,
    "snow":   0.92,
}

# ── Helpers internes ──────────────────────────────────────────────────────────

def _pnoise(x: int, y: int, scale: float, octaves: int, seed: int) -> float:
    """Bruit de Perlin normalisé dans [0, 1]."""
    return (pnoise2(x / scale, y / scale, octaves=octaves, base=seed) + 1.0) * 0.5


def _disk_cells(cx: int, cy: int, radius: int, width: int, height: int):
    """Génère (x, y, t) pour chaque cellule dans le disque, t = dist/radius ∈ [0,1]."""
    inv_r = 1.0 / radius if radius > 0 else 0.0
    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
            t = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 * inv_r
            if t <= 1.0:
                yield x, y, t


def _apply_soil_at(grid: Grid, x: int, y: int) -> None:
    """Met à jour la classification du sol et les conditions environnementales d'une cellule."""
    alt  = float(grid.altitude[y][x])
    cell = grid.cells[y][x]

    # Terrain
    cell.altitude = alt

    # Sol
    if alt < _WATER_THRESHOLD:
        cell.soil_type   = "water"
        cell.water_depth = _WATER_THRESHOLD - alt
    elif alt > _ROCK_THRESHOLD:
        cell.soil_type   = "rock"
        cell.water_depth = 0.0
    else:
        cell.soil_type   = "clay"
        cell.water_depth = 0.0

    # Humidité : inverse de l'altitude (eau = 1.0, sommet = 0.0)
    hum = 1.0 - alt
    grid.humidity[y][x] = hum
    cell.humidity = hum

    # Température : décroît avec l'altitude.
    # Formule calibrée pour que les espèces survivent dans leur plage altitudinale :
    #   alt=0.30 (plage) ≈ 17.5 °C  |  alt=0.50 (plaine) ≈ 12.5 °C
    #   alt=0.75 (forêt haute) ≈ 6.25 °C  |  alt=0.85 (roche) ≈ 3.75 °C
    cell.temperature = 15.0 + (0.4 - alt) * 25.0


def _classify_all(grid: Grid) -> None:
    """Reclassifie toutes les cellules (utilisé après génération complète)."""
    for y in range(grid.height):
        for x in range(grid.width):
            _apply_soil_at(grid, x, y)


# ── Génération de terrain ─────────────────────────────────────────────────────

def generate_terrain(grid: Grid, seed: int = 42, preset: str = "default") -> None:
    generators = {
        "default":   _generate_default,
        "ile":       _generate_island,
        "archipel":  _generate_archipelago,
        "montagne":  _generate_mountain,
        "continent": _generate_continent,
    }
    generators.get(preset, _generate_default)(grid, seed)
    _classify_all(grid)


def _generate_default(grid: Grid, seed: int) -> None:
    for y in range(grid.height):
        for x in range(grid.width):
            grid.altitude[y][x] = _pnoise(x, y, 50.0, 6, seed)


def _generate_island(grid: Grid, seed: int) -> None:
    cx, cy  = grid.width / 2.0, grid.height / 2.0
    max_d   = min(grid.width, grid.height) / 2.0
    for y in range(grid.height):
        for x in range(grid.width):
            noise    = _pnoise(x, y, 38.0, 6, seed)
            gradient = max(0.0, 1.0 - (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_d) ** 1.4)
            grid.altitude[y][x] = max(0.0, min(1.0, noise * 0.55 + gradient * 0.65 - 0.18))


def _generate_archipelago(grid: Grid, seed: int) -> None:
    cx, cy  = grid.width / 2.0, grid.height / 2.0
    max_d   = min(grid.width, grid.height) / 2.0
    for y in range(grid.height):
        for x in range(grid.width):
            noise = _pnoise(x, y, 18.0, 5, seed)
            edge  = max(0.0, 1.0 - (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_d) ** 2)
            grid.altitude[y][x] = max(0.0, min(1.0, noise * 0.85 * edge - 0.12))


def _generate_mountain(grid: Grid, seed: int) -> None:
    for y in range(grid.height):
        for x in range(grid.width):
            grid.altitude[y][x] = _pnoise(x, y, 28.0, 8, seed) ** 0.65


def _generate_continent(grid: Grid, seed: int) -> None:
    for y in range(grid.height):
        for x in range(grid.width):
            grid.altitude[y][x] = min(1.0, _pnoise(x, y, 65.0, 5, seed) * 0.65 + 0.22)


# ── Outils d'édition ─────────────────────────────────────────────────────────

def modify_altitude(grid: Grid, cx: int, cy: int, radius: int, delta: float) -> list:
    changes = []
    for x, y, t in _disk_cells(cx, cy, radius, grid.width, grid.height):
        grid.altitude[y][x] = max(0.0, min(1.0, float(grid.altitude[y][x]) + delta * (1.0 - t)))
        _apply_soil_at(grid, x, y)
        changes.append({"x": x, "y": y, "a": round(float(grid.altitude[y][x]), 3)})
    return changes


def paint_cell(grid: Grid, cx: int, cy: int, radius: int, biome: str) -> list:
    target = _BIOME_ALTITUDES.get(biome, 0.5)
    changes = []
    for x, y, t in _disk_cells(cx, cy, radius, grid.width, grid.height):
        strength = 1.0 - t * t
        cur = float(grid.altitude[y][x])
        grid.altitude[y][x] = max(0.0, min(1.0, cur * (1 - strength) + target * strength))
        _apply_soil_at(grid, x, y)
        changes.append({"x": x, "y": y, "a": round(float(grid.altitude[y][x]), 3)})
    return changes


def draw_river(grid: Grid, start_x: int, start_y: int) -> list:
    visited = set()
    path    = []
    x, y    = start_x, start_y

    for _ in range(300):
        if not (0 <= x < grid.width and 0 <= y < grid.height):
            break
        if (x, y) in visited:
            break
        if float(grid.altitude[y][x]) < 0.28:
            path.append((x, y))
            break
        visited.add((x, y))
        path.append((x, y))

        neighbors = []
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, -1), (-1, 1), (1, 1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < grid.width and 0 <= ny < grid.height and (nx, ny) not in visited:
                neighbors.append((float(grid.altitude[ny][nx]), nx, ny))

        if not neighbors:
            break
        neighbors.sort()
        best_alt, nx, ny = neighbors[0]
        if best_alt > float(grid.altitude[y][x]) + 0.03:
            break
        x, y = nx, ny

    changes = []
    for rx, ry in path:
        grid.altitude[ry][rx] = min(float(grid.altitude[ry][rx]), 0.22)
        _apply_soil_at(grid, rx, ry)
        changes.append({"x": rx, "y": ry, "a": round(float(grid.altitude[ry][rx]), 3)})
    return changes


def place_lake(grid: Grid, cx: int, cy: int, radius: int) -> list:
    changes = []
    for x, y, _ in _disk_cells(cx, cy, radius, grid.width, grid.height):
        grid.altitude[y][x] = min(float(grid.altitude[y][x]), _LAKE_WATER_LEVEL)
        _apply_soil_at(grid, x, y)
        changes.append({"x": x, "y": y, "a": round(float(grid.altitude[y][x]), 3)})
    return changes


# ── Sauvegarde / Chargement ───────────────────────────────────────────────────

def save_terrain(grid: Grid, filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    data = {
        "width":    grid.width,
        "height":   grid.height,
        "altitude": [[round(float(v), 3) for v in row] for row in grid.altitude],
        "humidity": [[round(float(v), 3) for v in row] for row in grid.humidity],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_terrain(grid: Grid, filepath: str) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    grid.altitude = np.array(data["altitude"], dtype=float)
    grid.humidity = np.array(data["humidity"], dtype=float)
    _classify_all(grid)
