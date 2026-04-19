"""
EcoSim Web Server — aiohttp
Lance un serveur HTTP+WebSocket sur localhost:8765.

Rendu :
  Les frames sont pré-rendues pendant la simulation et stockées dans le .db
  (table renders).  Au replay, le serveur lit simplement les PNG bytes depuis
  la BD et les sert.  Si la table renders est absente (ancien .db), fallback
  vers le re-rendu depuis WorldSnapshot.
"""
from __future__ import annotations

import asyncio
import io
import json
import threading
from pathlib import Path

import aiohttp
import numpy as np
from aiohttp import web

_BASE      = Path(__file__).parent
_STATIC    = _BASE / "static"
_SIM_DIR   = _BASE.parent
_SPECIES_D = _SIM_DIR / "species"
_RUNS_D    = _SIM_DIR / "runs"

_mgr = None  # SimulationManager — instancié dans run()

# ── Caches thread-safe ────────────────────────────────────────────────────────
_terrain_cache: dict  = {}      # (db, w, h) → np.ndarray H×W×3
_frame_cache:   dict  = {}      # (db, tick, w, h) → bytes PNG
_species_colors: dict | None = None
_cache_lock = threading.Lock()


# ── Helpers synchrones (pool threads) ─────────────────────────────────────────

def _load_species_colors() -> dict[str, tuple[int, int, int]]:
    global _species_colors
    with _cache_lock:
        if _species_colors is not None:
            return _species_colors
    colors: dict[str, tuple] = {}
    for p in sorted(_SPECIES_D.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        name = data["params"]["name"]
        r, g, b = [int(c * 255) for c in data["params"]["color"]]
        colors[name] = (r, g, b)
    with _cache_lock:
        _species_colors = colors
    return colors


def _render_terrain_arr(db_or_seed, preset: str, world_size: int,
                         out_w: int, out_h: int) -> np.ndarray:
    """Génère un ndarray H×W×3 uint8 pour le terrain.
    db_or_seed : int (seed direct) ou str (chemin .db pour lire les méta).
    """
    from world.grid import Grid
    from world.terrain import generate_terrain, BIOME_PALETTE
    from PIL import Image

    if isinstance(db_or_seed, str):
        from simulation.recording.replay import ReplayReader
        reader  = ReplayReader(Path(db_or_seed))
        m       = reader.meta
        world_size = int(m.get("world_width", 500))
        seed    = int(m.get("seed", 42))
        preset  = m.get("terrain_preset", "default")
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


def _get_terrain_arr(db: str, out_w: int, out_h: int) -> np.ndarray:
    """Terrain array avec cache.  Retourne un array READ-ONLY (ne pas modifier)."""
    key = (db, out_w, out_h)
    with _cache_lock:
        if key in _terrain_cache:
            return _terrain_cache[key]
    arr = _render_terrain_arr(db, "", 500, out_w, out_h)
    with _cache_lock:
        _terrain_cache[key] = arr
    return arr


def _get_stored_frame_png(db: str, tick: int) -> bytes | None:
    """Lit un PNG pré-rendu depuis la table renders du .db.  Retourne None si absent."""
    import sqlite3
    try:
        conn = sqlite3.connect(db, check_same_thread=False)
        row  = conn.execute("SELECT png FROM renders WHERE tick=?", (tick,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _render_frame_png_fallback(db: str, tick: int, out_w: int, out_h: int) -> bytes:
    """Fallback : re-rend depuis WorldSnapshot (anciens .db sans table renders)."""
    from simulation.recording.replay import ReplayReader
    from web.renderer import render_snapshot_frame

    terrain  = _get_terrain_arr(db, out_w, out_h)
    reader   = ReplayReader(Path(db))
    m        = reader.meta
    world_w  = int(m.get("world_width",  500))
    world_h  = int(m.get("world_height", 500))
    snap     = reader.state_at(tick)
    reader.close()

    if snap is None:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(terrain, "RGB").save(buf, format="PNG")
        return buf.getvalue()

    colors = _load_species_colors()
    return render_snapshot_frame(snap, terrain, colors, world_w, world_h, out_w, out_h)


def _get_frame_png(db: str, tick: int, out_w: int, out_h: int) -> bytes:
    """Sert un PNG de frame. Priorité : table renders > cache mémoire > re-rendu."""
    key = (db, tick, out_w, out_h)
    with _cache_lock:
        if key in _frame_cache:
            return _frame_cache[key]

    # Essaie d'abord la table renders (pré-rendu pendant la simulation)
    png = _get_stored_frame_png(db, tick)

    if png is None:
        # Fallback : re-rendu depuis WorldSnapshot (anciens .db)
        png = _render_frame_png_fallback(db, tick, out_w, out_h)

    with _cache_lock:
        _frame_cache[key] = png
    return png


def _read_replay_meta(db: str) -> dict:
    from simulation.recording.replay import ReplayReader
    reader = ReplayReader(Path(db))
    m      = reader.meta
    ticks  = reader._keyframe_ticks
    result = {
        "seed":           int(m.get("seed", 42)),
        "preset":         m.get("terrain_preset", "default"),
        "world_w":        int(m.get("world_width",  500)),
        "world_h":        int(m.get("world_height", 500)),
        "total_ticks":    reader.total_ticks,
        "min_tick":       reader.min_tick,
        "keyframe_ticks": ticks,
        "n_keyframes":    len(ticks),
        "version":        m.get("engine_version", "?"),
    }
    reader.close()
    return result


def _read_frame_json(db: str, tick: int) -> dict:
    """Données entités en JSON (pour panel info + sélection)."""
    from simulation.recording.replay import ReplayReader
    reader = ReplayReader(Path(db))
    snap   = reader.state_at(tick)
    reader.close()
    if snap is None:
        return {"tick": tick, "plants": [], "individuals": [], "counts": {}}
    return {
        "tick": snap.tick,
        "plants": [
            {"id": e.id, "x": round(e.x, 1), "y": round(e.y, 1),
             "sp": e.species, "energy": round(e.energy, 1), "age": e.age}
            for e in snap.plants if e.alive
        ],
        "individuals": [
            {"id": e.id, "sp": e.species,
             "x": round(e.x, 1), "y": round(e.y, 1),
             "energy": round(e.energy, 1), "age": e.age, "state": e.state}
            for e in snap.individuals if e.alive
        ],
        "counts": snap.species_counts,
    }


def _render_preview_png(seed: int, preset: str,
                         grid_size: int, out_w: int, out_h: int) -> bytes:
    """Preview terrain : utilise grid_size exact de la simulation → aperçu fidèle."""
    from PIL import Image
    arr = _render_terrain_arr(seed, preset, grid_size, out_w, out_h)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# ── Static ────────────────────────────────────────────────────────────────────

async def handle_index(request):
    return web.FileResponse(_STATIC / "index.html")


async def handle_static(request):
    p = _STATIC / request.match_info["path"]
    if p.exists() and p.is_file():
        return web.FileResponse(p)
    raise web.HTTPNotFound()


# ── API endpoints ─────────────────────────────────────────────────────────────

async def api_species(request):
    colors = _load_species_colors()
    items  = []
    for p in sorted(_SPECIES_D.glob("*.json")):
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
    config = await request.json()
    ok     = _mgr.start(config)
    return web.json_response({"ok": ok, "already_running": not ok})


async def api_sim_cancel(request):
    _mgr.cancel()
    return web.json_response({"ok": True})


async def api_runs(request):
    result = []
    if _RUNS_D.exists():
        for p in sorted(_RUNS_D.glob("*.db"), key=lambda f: -f.stat().st_mtime):
            result.append({
                "path":    p.as_posix(),
                "name":    p.name,
                "size_mb": round(p.stat().st_size / 1e6, 2),
            })
    return web.json_response(result)


async def api_replay_meta(request):
    db = request.rel_url.query.get("db", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    meta = await loop.run_in_executor(None, _read_replay_meta, db)
    return web.json_response(meta)


async def api_replay_terrain(request):
    """PNG du terrain seul (utilisé pour la miniature dans le header)."""
    db = request.rel_url.query.get("db", "")
    w  = int(request.rel_url.query.get("w", 260))
    h  = int(request.rel_url.query.get("h", 260))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    arr  = await loop.run_in_executor(None, _get_terrain_arr, db, w, h)
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return web.Response(body=buf.getvalue(), content_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})


async def api_frame_img(request):
    """PNG frame pré-rendu (terrain + entités) — cœur du viewer fluide."""
    db   = request.rel_url.query.get("db",   "")
    tick = int(request.rel_url.query.get("tick", 0))
    w    = int(request.rel_url.query.get("w",    700))
    h    = int(request.rel_url.query.get("h",    560))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    png  = await loop.run_in_executor(None, _get_frame_png, db, tick, w, h)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})


async def api_frame_json(request):
    """JSON entités pour un tick (panel info + sélection, pas le rendu visuel)."""
    db   = request.rel_url.query.get("db",   "")
    tick = int(request.rel_url.query.get("tick", 0))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_frame_json, db, tick)
    return web.json_response(data)


async def api_prerender(request):
    """Lance le pré-rendu de toutes les frames en arrière-plan."""
    body = await request.json()
    db   = body.get("db", "")
    w    = int(body.get("w", 700))
    h    = int(body.get("h", 560))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    asyncio.create_task(_prerender_all(db, w, h))
    return web.json_response({"ok": True})


async def _prerender_all(db: str, w: int, h: int) -> None:
    """Tâche asyncio : warm le cache mémoire pour les frames pas encore en cache."""
    from simulation.recording.replay import ReplayReader
    reader = ReplayReader(Path(db))
    ticks  = list(reader._keyframe_ticks)
    reader.close()
    loop = asyncio.get_event_loop()
    # Warm terrain cache (utile pour le fallback re-rendu des anciens .db)
    await loop.run_in_executor(None, _get_terrain_arr, db, w, h)
    # Warm frame cache (lit depuis la table renders si disponible, sinon re-rend)
    for tick in ticks:
        await loop.run_in_executor(None, _get_frame_png, db, tick, w, h)


# ── WebSocket ─────────────────────────────────────────────────────────────────

async def websocket_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    _mgr.add_ws(ws)
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
                except Exception:
                    pass
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
    finally:
        _mgr.remove_ws(ws)
    return ws


# ── App factory + lancement ───────────────────────────────────────────────────

def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get ("/",                        handle_index)
    app.router.add_get ("/static/{path:.*}",        handle_static)
    app.router.add_get ("/api/species",             api_species)
    app.router.add_post("/api/terrain/preview",     api_terrain_preview)
    app.router.add_post("/api/sim/start",           api_sim_start)
    app.router.add_post("/api/sim/cancel",          api_sim_cancel)
    app.router.add_get ("/api/runs",                api_runs)
    app.router.add_get ("/api/replay/meta",         api_replay_meta)
    app.router.add_get ("/api/replay/terrain",      api_replay_terrain)
    app.router.add_get ("/api/replay/frame_img",    api_frame_img)
    app.router.add_get ("/api/replay/frame_json",   api_frame_json)
    app.router.add_post("/api/replay/prerender",    api_prerender)
    app.router.add_get ("/ws",                      websocket_handler)
    return app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import webbrowser, threading

    async def _start():
        global _mgr
        from web.sim_manager import SimulationManager
        loop = asyncio.get_running_loop()
        _mgr = SimulationManager(loop)

        app    = _build_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site   = web.TCPSite(runner, host, port)
        await site.start()
        print(f"[EcoSim] Interface web → http://{host}:{port}", flush=True)
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
        await asyncio.Event().wait()

    asyncio.run(_start())
