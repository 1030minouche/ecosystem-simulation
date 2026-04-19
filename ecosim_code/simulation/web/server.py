"""
EcoSim Web Server — aiohttp
Lance un serveur HTTP+WebSocket sur localhost:8765.
"""
from __future__ import annotations

import asyncio
import glob
import io
import json
import os
from pathlib import Path

import aiohttp
from aiohttp import web

_BASE      = Path(__file__).parent
_STATIC    = _BASE / "static"
_SIM_DIR   = _BASE.parent
_SPECIES_D = _SIM_DIR / "species"
_RUNS_D    = _SIM_DIR / "runs"

_mgr = None   # SimulationManager — set in create_app()


# ── Static ────────────────────────────────────────────────────────────────────

async def handle_index(request):
    return web.FileResponse(_STATIC / "index.html")


async def handle_static(request):
    rel  = request.match_info["path"]
    path = _STATIC / rel
    if path.exists() and path.is_file():
        return web.FileResponse(path)
    raise web.HTTPNotFound()


# ── API ───────────────────────────────────────────────────────────────────────

async def api_species(request):
    items = []
    for p in sorted(_SPECIES_D.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        params = data["params"]
        r, g, b = [int(c * 255) for c in params["color"]]
        items.append({
            "file":          p.stem,
            "name":          params["name"],
            "color":         f"#{r:02x}{g:02x}{b:02x}",
            "count_default": data["count"],
            "params":        params,
        })
    return web.json_response(items)


async def api_terrain_preview(request):
    body   = await request.json()
    seed   = int(body.get("seed", 42))
    preset = body.get("preset", "default")
    size   = min(int(body.get("size", 150)), 400)

    loop = asyncio.get_event_loop()
    png  = await loop.run_in_executor(None, _render_terrain_png, seed, preset, size, size)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-store"})


async def api_sim_start(request):
    config = await request.json()
    ok = _mgr.start(config)
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
    db = request.rel_url.query.get("db", "")
    w  = int(request.rel_url.query.get("w", 700))
    h  = int(request.rel_url.query.get("h", 580))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    png  = await loop.run_in_executor(None, _render_replay_terrain, db, w, h)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})


async def api_replay_frame(request):
    db   = request.rel_url.query.get("db", "")
    tick = int(request.rel_url.query.get("tick", 0))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_frame, db, tick)
    return web.json_response(data)


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


# ── Helpers synchrones (run_in_executor) ──────────────────────────────────────

def _render_terrain_png(seed: int, preset: str, out_w: int, out_h: int) -> bytes:
    import numpy as np
    from PIL import Image
    from world.grid import Grid
    from world.terrain import generate_terrain, BIOME_PALETTE

    size = max(out_w, out_h)
    grid = Grid(width=size, height=size)
    generate_terrain(grid, seed=seed, preset=preset)
    alt = np.array(grid.altitude)
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        rgb[alt >= threshold] = color
    img = Image.fromarray(rgb, "RGB").resize((out_w, out_h), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


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


def _render_replay_terrain(db: str, out_w: int, out_h: int) -> bytes:
    from simulation.recording.replay import ReplayReader
    from world.grid import Grid
    from world.terrain import generate_terrain, BIOME_PALETTE
    from PIL import Image
    import numpy as np

    reader  = ReplayReader(Path(db))
    m       = reader.meta
    world_w = int(m.get("world_width",  500))
    world_h = int(m.get("world_height", 500))
    seed    = int(m.get("seed", 42))
    preset  = m.get("terrain_preset", "default")
    reader.close()

    grid = Grid(width=world_w, height=world_h)
    generate_terrain(grid, seed=seed, preset=preset)
    alt = np.array(grid.altitude)
    rgb = np.zeros((world_h, world_w, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        rgb[alt >= threshold] = color

    img = Image.fromarray(rgb, "RGB").resize((out_w, out_h), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _read_frame(db: str, tick: int) -> dict:
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
             "sp": e.species, "energy": round(e.energy, 1), "age": e.age, "state": e.state}
            for e in snap.plants if e.alive
        ],
        "individuals": [
            {
                "id": e.id, "sp": e.species,
                "x": round(e.x, 1), "y": round(e.y, 1),
                "energy": round(e.energy, 1),
                "age": e.age, "state": e.state,
            }
            for e in snap.individuals if e.alive
        ],
        "counts": snap.species_counts,
    }


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    global _mgr
    from web.sim_manager import SimulationManager
    loop = asyncio.get_event_loop()
    _mgr = SimulationManager(loop)

    app = web.Application()
    app.router.add_get("/",                       handle_index)
    app.router.add_get("/static/{path:.*}",       handle_static)
    app.router.add_get("/api/species",            api_species)
    app.router.add_post("/api/terrain/preview",   api_terrain_preview)
    app.router.add_post("/api/sim/start",         api_sim_start)
    app.router.add_post("/api/sim/cancel",        api_sim_cancel)
    app.router.add_get("/api/runs",               api_runs)
    app.router.add_get("/api/replay/meta",        api_replay_meta)
    app.router.add_get("/api/replay/terrain",     api_replay_terrain)
    app.router.add_get("/api/replay/frame",       api_replay_frame)
    app.router.add_get("/ws",                     websocket_handler)
    return app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import webbrowser
    import threading

    app = create_app()

    async def _start():
        runner  = web.AppRunner(app)
        await runner.setup()
        site    = web.TCPSite(runner, host, port)
        await site.start()
        print(f"[EcoSim] Interface web → http://{host}:{port}", flush=True)
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
        await asyncio.Event().wait()   # run forever

    asyncio.run(_start())
