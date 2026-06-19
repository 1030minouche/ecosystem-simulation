"""
EcoSim Web Server — aiohttp
Lance un serveur HTTP+WebSocket sur localhost:9000 (port par défaut).

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
import logging
import sqlite3
import threading
from pathlib import Path

import aiohttp
import numpy as np
from aiohttp import web

from web.routes_analyse import read_timeseries, register_analyse_routes

logger = logging.getLogger(__name__)

_BASE       = Path(__file__).parent
_STATIC     = _BASE / "static"
_SIM_DIR    = _BASE.parent
_SPECIES_D  = _SIM_DIR / "species"
_RUNS_D     = _SIM_DIR / "runs"
_DISEASES_D = _SIM_DIR / "species_data" / "diseases"

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
    from PIL import Image
    from world.grid import Grid
    from world.terrain import BIOME_PALETTE, generate_terrain

    if isinstance(db_or_seed, str):
        from engine.recording.replay import ReplayReader
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
    try:
        conn = sqlite3.connect(db, check_same_thread=False)
        row  = conn.execute("SELECT png FROM renders WHERE tick=?", (tick,)).fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error as exc:
        logger.debug("swallowed: %s (db=%s tick=%s)", exc, db, tick)
        return None


def _render_frame_png_fallback(db: str, tick: int, out_w: int, out_h: int) -> bytes:
    """Fallback : re-rend depuis WorldSnapshot (anciens .db sans table renders)."""
    from engine.recording.replay import ReplayReader

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
    from engine.recording.replay import ReplayReader
    reader = ReplayReader(Path(db))
    m      = reader.meta
    ticks  = reader._keyframe_ticks
    last_kf   = ticks[-1] if ticks else 0
    max_ticks = int(m.get("max_ticks", last_kf))   # durée configurée par l'utilisateur
    result = {
        "seed":           int(m.get("seed", 42)),
        "preset":         m.get("terrain_preset", "default"),
        "world_w":        int(m.get("world_width",  500)),
        "world_h":        int(m.get("world_height", 500)),
        "total_ticks":    last_kf,
        "max_ticks":      max_ticks,
        "min_tick":       reader.min_tick,
        "keyframe_ticks": ticks,
        "n_keyframes":    len(ticks),
        "version":        m.get("engine_version", "?"),
        "run_id":         m.get("run_id", ""),
    }
    reader.close()
    return result


def _read_frame_json(db: str, tick: int) -> dict:
    """Données entités en JSON (pour panel info + sélection)."""
    from engine.recording.replay import ReplayReader
    reader = ReplayReader(Path(db))
    snap   = reader.state_at(tick)
    reader.close()
    if snap is None:
        return {"tick": tick, "plants": [], "individuals": [], "counts": {}}
    return {
        "tick": snap.tick,
        "plants": [],
        "individuals": [
            {"id": e.id, "sp": e.species,
             "x": round(e.x, 1), "y": round(e.y, 1),
             "energy": round(e.energy, 1), "age": e.age, "state": e.state,
             "infected": e.infected}
            for e in snap.individuals if e.alive
        ],
        "counts": snap.species_counts,
    }


def _quick_meta(db_path: str, key: str) -> str:
    """Lit une valeur meta depuis un .db sans ouvrir un ReplayReader complet."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        row  = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else ""
    except sqlite3.Error as exc:
        logger.debug("swallowed: %s (db=%s key=%s)", exc, db_path, key)
        return ""


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


async def api_diseases(request):
    """GET /api/diseases — liste toutes les maladies disponibles."""
    diseases = []
    if _DISEASES_D.exists():
        for p in sorted(_DISEASES_D.glob("*.json")):
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


async def api_replay_infect(request):
    """POST /api/replay/infect — démarre une simulation à partir d'un tick
    en infectant une ou plusieurs entités.

    Body accepté (deux formats) :
      - Cible unique  : {species, x, y, ...}
      - Cibles multi : {targets: [{species, x, y}, ...], ...}

    Champs communs : db, tick, disease_name, more_ticks.
    """
    body        = await request.json()
    db          = body.get("db", "")
    tick        = int(body.get("tick", 0))
    disease     = body.get("disease_name", "")
    more_ticks  = int(body.get("more_ticks", 5000))

    if not db or not Path(db).exists():
        return web.json_response({"ok": False, "error": "db introuvable"}, status=404)
    if not disease:
        return web.json_response({"ok": False, "error": "maladie manquante"}, status=400)

    raw_targets = body.get("targets")
    if isinstance(raw_targets, list) and raw_targets:
        targets = [
            {
                "species": str(t.get("species", "")),
                "x":       float(t.get("x", 0)),
                "y":       float(t.get("y", 0)),
            }
            for t in raw_targets
        ]
    else:
        targets = [{
            "species": str(body.get("species", "")),
            "x":       float(body.get("x", 0)),
            "y":       float(body.get("y", 0)),
        }]

    config = {
        "mode":         "infect",
        "db_path":      db,
        "tick":         tick,
        "targets":      targets,
        # Champs unique conservés pour compat (le manager privilégie `targets`)
        "species":      targets[0]["species"],
        "entity_x":     targets[0]["x"],
        "entity_y":     targets[0]["y"],
        "disease_name": disease,
        "ticks":        more_ticks,
    }
    ok = _mgr.start(config)
    return web.json_response({"ok": ok, "already_running": not ok, "n_targets": len(targets)})


async def api_sim_start(request):
    config  = await request.json()
    db_path = config.get("out_path", "runs/sim.db")
    # Invalider le cache mémoire pour ce chemin avant toute nouvelle simulation
    with _cache_lock:
        for key in list(_frame_cache.keys()):
            if key[0] == db_path:
                del _frame_cache[key]
        for key in list(_terrain_cache.keys()):
            if key[0] == db_path:
                del _terrain_cache[key]
    ok = _mgr.start(config)
    return web.json_response({"ok": ok, "already_running": not ok})


async def api_sim_cancel(request):
    _mgr.cancel()
    return web.json_response({"ok": True})


def _enrich_run_meta(p) -> dict:
    """Construit le dict enrichi pour une run (appelé dans un thread pool)."""
    from datetime import datetime
    db = str(p)
    try:
        conn = sqlite3.connect(db, check_same_thread=False)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        ticks_row = conn.execute(
            "SELECT MAX(tick) FROM keyframes"
        ).fetchone()
        last_tick = ticks_row[0] or 0
        max_pops: dict = {}
        species_seen: set = set()
        for (data,) in conn.execute("SELECT data FROM counts"):
            for sp, n in json.loads(data).items():
                species_seen.add(sp)
                if n > max_pops.get(sp, 0):
                    max_pops[sp] = n
        conn.close()
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        logger.debug("swallowed: %s (%s)", exc, db)
        meta = {}
        last_tick = 0
        max_pops = {}
        species_seen = set()

    stat = p.stat()
    return {
        "path":           p.as_posix(),
        "name":           p.name,
        "run_id":         meta.get("run_id", ""),
        "created_at":     datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "file_size_mb":   round(stat.st_size / 1e6, 2),
        "ticks":          last_tick,
        "species":        sorted(species_seen),
        "max_populations": max_pops,
        "terrain_preset": meta.get("terrain_preset", "default"),
        "seed":           int(meta.get("seed", 0)),
        "engine_version": meta.get("engine_version", "?"),
    }


async def api_runs(request):
    result = []
    if _RUNS_D.exists():
        loop = asyncio.get_event_loop()
        files = sorted(_RUNS_D.glob("*.db"), key=lambda f: -f.stat().st_mtime)
        for p in files:
            data = await loop.run_in_executor(None, _enrich_run_meta, p)
            result.append(data)
    return web.json_response(result)


async def api_runs_tag(request):
    """PATCH /api/runs/{run_id}/tag — assigne un libellé à une run."""
    run_id = request.match_info["run_id"]
    body   = await request.json()
    tag    = body.get("tag", "")
    if not _RUNS_D.exists():
        raise web.HTTPNotFound()
    for p in _RUNS_D.glob("*.db"):
        if _quick_meta(str(p), "run_id") == run_id:
            import sqlite3
            conn = sqlite3.connect(str(p))
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('tag',?)", (tag,))
            conn.commit()
            conn.close()
            return web.json_response({"ok": True})
    raise web.HTTPNotFound()


def _compare_runs(db_a: str, db_b: str) -> dict:
    ts_a = read_timeseries(db_a)
    ts_b = read_timeseries(db_b)
    return {"run_a": ts_a, "run_b": ts_b}


async def api_runs_compare(request):
    a = request.rel_url.query.get("a", "")
    b = request.rel_url.query.get("b", "")
    if not a or not b or not Path(a).exists() or not Path(b).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _compare_runs, a, b)
    return web.json_response(data)


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
                        headers={"Cache-Control": "no-store"})


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
    from engine.recording.replay import ReplayReader
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
                except (json.JSONDecodeError, ConnectionError) as exc:
                    logger.debug("swallowed: %s", exc)
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
    finally:
        _mgr.remove_ws(ws)
    return ws


# ── Export & heatmap ────────────────────────────────────────────────────────
# Les handlers /api/analyse/* + /api/replay/genetics, /heatmap vivent dans
# `web/routes_analyse.py` (importés en tête de fichier). Ici on garde
# uniquement les helpers d'export CSV qui réutilisent `read_timeseries`.

def _export_csv(db: str) -> str:
    """Exporte les timeseries en CSV."""
    import csv
    import io
    ts   = read_timeseries(db)
    buf  = io.StringIO()
    all_sp = sorted({sp for row in ts for sp in row["counts"]})
    w = csv.writer(buf)
    w.writerow(["tick"] + all_sp)
    for row in ts:
        w.writerow([row["tick"]] + [row["counts"].get(sp, 0) for sp in all_sp])
    return buf.getvalue()


async def api_export(request):
    """GET /api/runs/{run_id}/export?format=csv|json"""
    run_id = request.match_info.get("run_id", "")
    fmt    = request.rel_url.query.get("format", "csv")
    db_path = None
    if _RUNS_D.exists():
        for p in _RUNS_D.glob("*.db"):
            if _quick_meta(str(p), "run_id") == run_id:
                db_path = str(p)
                break
    if db_path is None:
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    if fmt == "csv":
        csv_data = await loop.run_in_executor(None, _export_csv, db_path)
        return web.Response(body=csv_data, content_type="text/csv",
                            headers={"Content-Disposition":
                                     f'attachment; filename="run_{run_id}.csv"'})
    ts = await loop.run_in_executor(None, read_timeseries, db_path)
    return web.json_response(ts)


# ── App factory + lancement ───────────────────────────────────────────────────

def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get ("/",                        handle_index)
    app.router.add_get ("/static/{path:.*}",        handle_static)
    app.router.add_get ("/api/species",             api_species)
    app.router.add_get ("/api/diseases",            api_diseases)
    app.router.add_post("/api/terrain/preview",     api_terrain_preview)
    app.router.add_post("/api/sim/start",           api_sim_start)
    app.router.add_post("/api/sim/cancel",          api_sim_cancel)
    app.router.add_post("/api/replay/infect",       api_replay_infect)
    app.router.add_get ("/api/runs",                api_runs)
    app.router.add_get ("/api/replay/meta",         api_replay_meta)
    app.router.add_get ("/api/replay/terrain",      api_replay_terrain)
    app.router.add_get ("/api/replay/frame_img",    api_frame_img)
    app.router.add_get ("/api/replay/frame_json",   api_frame_json)
    app.router.add_post("/api/replay/prerender",    api_prerender)
    register_analyse_routes(app)  # /api/analyse/* + replay/genetics + replay/heatmap
    app.router.add_patch ("/api/runs/{run_id}/tag",     api_runs_tag)
    app.router.add_get   ("/api/runs/compare",          api_runs_compare)
    app.router.add_get   ("/api/runs/{run_id}/export",  api_export)
    app.router.add_get   ("/ws",                        websocket_handler)
    return app


def run(host: str = "0.0.0.0", port: int = 9000) -> None:
    import threading
    import webbrowser

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
        print(f"[EcoSim] Interface web → http://localhost:{port}", flush=True)
        threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        await asyncio.Event().wait()

    asyncio.run(_start())
