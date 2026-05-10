"""
Rendu numpy → PNG.  Utilisé à deux moments :
  1. Pendant la simulation (via recorder) : rendu depuis l'état live du moteur.
  2. Au replay (fallback) : rendu depuis un WorldSnapshot (vieux .db sans frames pré-rendues).

Résolution de sortie fixe : RENDER_W × RENDER_H pixels.
"""
from __future__ import annotations

import io
import numpy as np
from PIL import Image

RENDER_W = 720
RENDER_H = 576


# ── Terrain ───────────────────────────────────────────────────────────────────

def terrain_arr_from_grid(grid, out_w: int = RENDER_W, out_h: int = RENDER_H) -> np.ndarray:
    """Rend le terrain d'une Grid live → ndarray H×W×3 uint8."""
    from world.terrain import BIOME_PALETTE
    alt = grid.altitude                         # shape (H, W), range [0, 1]
    rgb = np.zeros((grid.height, grid.width, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        rgb[alt >= threshold] = color
    img = Image.fromarray(rgb, "RGB").resize((out_w, out_h), Image.NEAREST)
    return np.asarray(img, dtype=np.uint8).copy()


def terrain_arr_from_db(db_path: str, out_w: int = RENDER_W, out_h: int = RENDER_H) -> np.ndarray:
    """Recrée le terrain depuis les méta d'un .db → ndarray H×W×3 uint8."""
    from pathlib import Path
    from world.grid import Grid
    from world.terrain import generate_terrain, BIOME_PALETTE
    from simulation.recording.replay import ReplayReader

    reader     = ReplayReader(Path(db_path))
    m          = reader.meta
    world_size = int(m.get("world_width",  500))
    seed       = int(m.get("seed",         42))
    preset     = m.get("terrain_preset",   "default")
    reader.close()

    grid = Grid(width=world_size, height=world_size)
    generate_terrain(grid, seed=seed, preset=preset)

    alt = grid.altitude
    rgb = np.zeros((world_size, world_size, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        rgb[alt >= threshold] = color
    img = Image.fromarray(rgb, "RGB").resize((out_w, out_h), Image.NEAREST)
    return np.asarray(img, dtype=np.uint8).copy()


# ── Entités ───────────────────────────────────────────────────────────────────

def _draw_entities(arr: np.ndarray,
                   plants, individuals,
                   get_species_name,       # callable(entity) -> str
                   colors: dict[str, tuple],
                   world_w: int, world_h: int,
                   out_w: int, out_h: int) -> None:
    """Dessine plantes (1 px) et animaux (5×5 px) sur arr in-place."""
    sx, sy = out_w / world_w, out_h / world_h

    # Plantes — vectorisé par espèce
    plant_by_sp: dict[str, list] = {}
    for p in plants:
        if getattr(p, "alive", True):
            plant_by_sp.setdefault(get_species_name(p), []).append(p)

    for sp_name, grp in plant_by_sp.items():
        col = colors.get(sp_name, (100, 200, 100))
        xs = np.clip(
            np.round(np.array([p.x for p in grp], dtype=np.float32) * sx).astype(int),
            0, out_w - 1,
        )
        ys = np.clip(
            np.round(np.array([p.y for p in grp], dtype=np.float32) * sy).astype(int),
            0, out_h - 1,
        )
        arr[ys, xs] = col

    # Animaux — dot 5×5 (halo orange si infecté)
    for ind in individuals:
        if not getattr(ind, "alive", True):
            continue
        col = colors.get(get_species_name(ind), (255, 165, 0))
        cx = int(np.clip(round(ind.x * sx), 2, out_w - 3))
        cy = int(np.clip(round(ind.y * sy), 2, out_h - 3))
        if getattr(ind, "is_infectious", False):
            hx0 = max(0, cx - 3); hx1 = min(out_w, cx + 4)
            hy0 = max(0, cy - 3); hy1 = min(out_h, cy + 4)
            arr[hy0:hy1, hx0:hx1] = (180, 80, 0)
        arr[cy - 2:cy + 3, cx - 2:cx + 3] = col


def render_heatmap(snap, world_w: int, world_h: int, species: str,
                   out_w: int = 300, out_h: int = 300) -> bytes:
    """Heatmap de densité KDE pour une espèce à partir d'un WorldSnapshot → PNG bytes."""
    from PIL import Image
    import io as _io

    xs = np.array([e.x for e in snap.individuals if e.alive and e.species == species], dtype=np.float32)
    ys = np.array([e.y for e in snap.individuals if e.alive and e.species == species], dtype=np.float32)

    try:
        from scipy.stats import gaussian_kde
        has_scipy = True
    except ImportError:
        has_scipy = False

    if len(xs) < 3 or not has_scipy:
        img = Image.new("RGB", (out_w, out_h), (20, 20, 40))
    else:
        gx = np.linspace(0, world_w, out_w)
        gy = np.linspace(0, world_h, out_h)
        gxx, gyy = np.meshgrid(gx, gy)
        positions = np.vstack([gxx.ravel(), gyy.ravel()])
        values    = np.vstack([xs, ys])
        kde       = gaussian_kde(values, bw_method=0.15)
        density   = kde(positions).reshape(out_h, out_w)
        density   = density / density.max()
        rgb = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        rgb[..., 0] = (density * 255).astype(np.uint8)
        rgb[..., 1] = (density * 120).astype(np.uint8)
        img = Image.fromarray(rgb, "RGB")

    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def arr_to_png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# ── API principale ────────────────────────────────────────────────────────────

def render_engine_frame(engine,
                        terrain_arr: np.ndarray,
                        colors: dict[str, tuple],
                        out_w: int = RENDER_W,
                        out_h: int = RENDER_H) -> bytes:
    """Rend terrain + entités depuis l'état live du moteur → PNG bytes.

    Appelé pendant la simulation : engine.plants[i].species est un objet Species,
    donc on utilise .species.name pour obtenir le nom.
    """
    arr = terrain_arr.copy()
    _draw_entities(
        arr,
        plants      = (p for p in engine.plants if p.alive),
        individuals = engine.individuals,
        get_species_name = lambda e: e.species.name,
        colors      = colors,
        world_w     = engine.grid.width,
        world_h     = engine.grid.height,
        out_w       = out_w,
        out_h       = out_h,
    )
    return arr_to_png(arr)


def render_snapshot_frame(snap,
                          terrain_arr: np.ndarray,
                          colors: dict[str, tuple],
                          world_w: int, world_h: int,
                          out_w: int = RENDER_W,
                          out_h: int = RENDER_H) -> bytes:
    """Rend terrain + entités depuis un WorldSnapshot → PNG bytes.

    Appelé au replay (fallback) : EntitySnapshot.species est déjà un str.
    """
    arr = terrain_arr.copy()
    _draw_entities(
        arr,
        plants      = snap.plants,
        individuals = snap.individuals,
        get_species_name = lambda e: e.species,   # déjà une str
        colors      = colors,
        world_w     = world_w,
        world_h     = world_h,
        out_w       = out_w,
        out_h       = out_h,
    )
    return arr_to_png(arr)
