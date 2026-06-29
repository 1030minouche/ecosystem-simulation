"""
Endpoints de pilotage de simulation — extraits de `web/server.py`.

Routes enregistrées :
  - GET  /api/species
  - GET  /api/diseases
  - POST /api/terrain/preview
  - POST /api/sim/start
  - POST /api/sim/cancel

Les caches et le `SimulationManager` restent attachés au module
`ecosim.web.server` (globales `_mgr`, `_frame_cache`, `_terrain_cache`,
`_cache_lock`, `_SPECIES_D`, `_DISEASES_D`, `_species_colors`) pour que
les tests qui font `monkeypatch.setattr(server, "_mgr", …)` continuent
de fonctionner et que la source de vérité de l'état runtime reste
unique. Les handlers ci-dessous reachent dans ce module au moment de
l'appel HTTP, pas à l'import.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import numpy as np
from aiohttp import web

from ecosim.web import server as _server  # cycle résolu à l'appel, pas à l'import

logger = logging.getLogger(__name__)


# ── Helpers terrain (rendu) ───────────────────────────────────────────────────

def _load_species_colors() -> dict[str, tuple[int, int, int]]:
    """Cache module-level (sur `_server._species_colors`)."""
    with _server._cache_lock:
        if _server._species_colors is not None:
            return _server._species_colors
    colors: dict[str, tuple] = {}
    for p in sorted(_server._SPECIES_D.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        name = data["params"]["name"]
        r, g, b = (int(c * 255) for c in data["params"]["color"])
        colors[name] = (r, g, b)
    with _server._cache_lock:
        _server._species_colors = colors
    return colors


def _render_terrain_arr(db_or_seed, preset: str, world_size: int,
                         out_w: int, out_h: int) -> np.ndarray:
    """Génère un ndarray H×W×3 uint8 pour le terrain.

    db_or_seed : int (seed direct) ou str (chemin .db pour lire les méta).
    """
    from pathlib import Path

    from PIL import Image

    from ecosim.world.grid import Grid
    from ecosim.world.terrain import BIOME_PALETTE, generate_terrain

    if isinstance(db_or_seed, str):
        from ecosim.engine.recording.replay import ReplayReader
        reader     = ReplayReader(Path(db_or_seed))
        m          = reader.meta
        world_size = int(m.get("world_width", 500))
        seed       = int(m.get("seed", 42))
        preset     = m.get("terrain_preset", "default")
        reader.close()
    else:
        seed = db_or_seed

    grid = Grid(width=world_size, height=world_size)
    generate_terrain(grid, seed=seed, preset=preset)

    alt = np.array(grid.altitude)
    rgb = np.zeros((world_size, world_size, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        rgb[alt >= threshold] = color

    img = Image.fromarray(rgb, "RGB").resize((out_w, out_h), Image.NEAREST)
    return np.asarray(img, dtype=np.uint8).copy()


def _render_preview_png(seed: int, preset: str,
                         grid_size: int, out_w: int, out_h: int) -> bytes:
    """Preview terrain : utilise grid_size exact → aperçu fidèle."""
    from PIL import Image
    arr = _render_terrain_arr(seed, preset, grid_size, out_w, out_h)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# ── Handlers ──────────────────────────────────────────────────────────────────

async def api_species(request):
    colors = _load_species_colors()
    items  = []
    for p in sorted(_server._SPECIES_D.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        params = data["params"]
        name   = params["name"]
        r, g, b = colors.get(name, (128, 128, 128))
        items.append({
            "file":          p.stem,
            "name":          name,
            "color":         f"#{r:02x}{g:02x}{b:02x}",
            "count_default": data["count"],
            "params":        params,
        })
    return web.json_response(items)


async def api_diseases(request):
    diseases = []
    if _server._DISEASES_D.exists():
        for p in sorted(_server._DISEASES_D.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                diseases.append({
                    "file": p.stem,
                    "name": d.get("name", p.stem),
                    "transmission_rate": d.get("transmission_rate", 0),
                    "mortality_chance":  d.get("mortality_chance", 0),
                    "infectious_ticks":  d.get("infectious_ticks", 0),
                })
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.debug("swallowed: %s (%s)", exc, p)
    return web.json_response(diseases)


async def api_terrain_preview(request):
    body      = await request.json()
    seed      = int(body.get("seed",      42))
    preset    = body.get("preset",        "default")
    out_size  = min(int(body.get("size",  260)), 400)
    grid_size = int(body.get("grid_size", 500))

    loop = asyncio.get_event_loop()
    png  = await loop.run_in_executor(
        None, _render_preview_png, seed, preset, grid_size, out_size, out_size
    )
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-store"})


async def api_sim_start(request):
    config  = await request.json()
    db_path = config.get("out_path", "runs/sim.db")
    # Invalider le cache mémoire pour ce chemin avant toute nouvelle simulation
    with _server._cache_lock:
        for key in list(_server._frame_cache.keys()):
            if key[0] == db_path:
                del _server._frame_cache[key]
        for key in list(_server._terrain_cache.keys()):
            if key[0] == db_path:
                del _server._terrain_cache[key]
    ok = _server._mgr.start(config)
    return web.json_response({"ok": ok, "already_running": not ok})


async def api_sim_cancel(request):
    _server._mgr.cancel()
    return web.json_response({"ok": True})


# ── Enregistrement ────────────────────────────────────────────────────────────

def register_sim_routes(app: web.Application) -> None:
    app.router.add_get ("/api/species",         api_species)
    app.router.add_get ("/api/diseases",        api_diseases)
    app.router.add_post("/api/terrain/preview", api_terrain_preview)
    app.router.add_post("/api/sim/start",       api_sim_start)
    app.router.add_post("/api/sim/cancel",      api_sim_cancel)
