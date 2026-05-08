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
    from simulation.recording.replay import ReplayReader
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
             "energy": round(e.energy, 1), "age": e.age, "state": e.state}
            for e in snap.individuals if e.alive
        ],
        "counts": snap.species_counts,
    }


def _quick_meta(db_path: str, key: str) -> str:
    """Lit une valeur meta depuis un .db sans ouvrir un ReplayReader complet."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        row  = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception:
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
    import sqlite3
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
    except Exception:
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
            conn.commit(); conn.close()
            return web.json_response({"ok": True})
    raise web.HTTPNotFound()


def _compare_runs(db_a: str, db_b: str) -> dict:
    ts_a = _read_timeseries(db_a)
    ts_b = _read_timeseries(db_b)
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


# ── Analyse helpers ──────────────────────────────────────────────────────────

def _read_timeseries(db: str) -> list:
    """Toutes les populations par keyframe. Lit la table counts (rapide) ou dégrade."""
    import sqlite3, gzip
    conn = sqlite3.connect(db, check_same_thread=False)
    try:
        rows = conn.execute("SELECT tick, data FROM counts ORDER BY tick").fetchall()
        if rows:
            conn.close()
            return [{"tick": t, "counts": json.loads(d)} for t, d in rows]
    except Exception:
        pass
    # Fallback : lit les keyframes complètes
    rows = conn.execute("SELECT tick, data_blob FROM keyframes ORDER BY tick").fetchall()
    conn.close()
    result = []
    for tick, blob in rows:
        data = json.loads(gzip.decompress(blob))
        result.append({"tick": tick, "counts": data["species_counts"]})
    return result


def _read_genealogy(db: str, entity_id: int) -> dict:
    """Arbre généalogique autour de entity_id (2 générations up + 2 down)."""
    import sqlite3
    conn = sqlite3.connect(db, check_same_thread=False)
    rows = conn.execute(
        "SELECT entity_id, tick, payload FROM events WHERE kind='birth'"
    ).fetchall()
    conn.close()

    by_id: dict    = {}
    by_parent: dict = {}
    for eid, tick, payload_str in rows:
        p   = json.loads(payload_str)
        pid = p.get("parent_id", -1)
        by_id[eid] = {"id": eid, "birth_tick": tick,
                      "species": p.get("species", "?"), "parent_id": pid}
        by_parent.setdefault(pid, []).append(eid)

    def enrich(info: dict) -> dict:
        r = dict(info)
        r["children_count"] = len(by_parent.get(r["id"], []))
        return r

    subject = enrich(by_id.get(entity_id,
                     {"id": entity_id, "birth_tick": -1, "species": "?", "parent_id": -1}))

    # Ancêtres (3 niveaux)
    ancestors = []
    cur = subject["parent_id"]
    for _ in range(3):
        if cur <= 0:
            break
        if cur in by_id:
            ancestors.append(enrich(by_id[cur]))
            cur = by_id[cur]["parent_id"]
        else:
            ancestors.append({"id": cur, "birth_tick": 0,
                               "species": subject["species"],
                               "parent_id": -1, "children_count": 1})
            break

    # Descendants (enfants + petits-enfants)
    desc = []
    for cid in by_parent.get(entity_id, [])[:40]:
        if cid in by_id:
            c = enrich(by_id[cid])
            desc.append(c)
            for gcid in by_parent.get(cid, [])[:15]:
                if gcid in by_id:
                    desc.append(enrich(by_id[gcid]))

    return {
        "subject":     subject,
        "ancestors":   list(reversed(ancestors)),
        "descendants": desc,
    }


def _read_day_info(db: str, day: int) -> dict:
    """Snapshot de population au début du jour day (1-indexed)."""
    from simulation.engine_const import DAY_LENGTH
    from simulation.recording.replay import ReplayReader
    target_tick = day * DAY_LENGTH
    reader = ReplayReader(Path(db))
    snap   = reader.state_at(target_tick)
    actual = reader._best_keyframe(target_tick)
    min_t  = reader.min_tick
    max_t  = int(reader.meta.get("max_ticks", 0))
    reader.close()
    counts = snap.species_counts if snap else {}
    return {"day": day, "tick": actual, "min_tick": min_t,
            "max_ticks": max_t, "counts": counts}


def _read_stats(db: str) -> dict:
    """Statistiques agrégées : naissances/espèce, max populations."""
    import sqlite3
    conn = sqlite3.connect(db, check_same_thread=False)
    births_by_sp: dict = {}
    try:
        for (payload_str,) in conn.execute(
                "SELECT payload FROM events WHERE kind='birth'"):
            sp = json.loads(payload_str).get("species", "?")
            births_by_sp[sp] = births_by_sp.get(sp, 0) + 1
    except Exception:
        pass
    max_pops: dict = {}
    try:
        for (data,) in conn.execute("SELECT data FROM counts"):
            for sp, n in json.loads(data).items():
                if n > max_pops.get(sp, 0):
                    max_pops[sp] = n
    except Exception:
        pass
    conn.close()
    return {"births_by_species": births_by_sp, "max_populations": max_pops}


# ── Analyse endpoints ─────────────────────────────────────────────────────────

async def api_timeseries(request):
    db = request.rel_url.query.get("db", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_timeseries, db)
    return web.json_response(data)


async def api_genealogy(request):
    db  = request.rel_url.query.get("db", "")
    eid = int(request.rel_url.query.get("id", "0"))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_genealogy, db, eid)
    return web.json_response(data)


async def api_day_info(request):
    db  = request.rel_url.query.get("db", "")
    day = int(request.rel_url.query.get("day", "1"))
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_day_info, db, day)
    return web.json_response(data)


async def api_stats(request):
    db = request.rel_url.query.get("db", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_stats, db)
    return web.json_response(data)


def _read_genetics(db: str, tick: int, species: str) -> dict:
    """Calcule diversité génétique depuis la keyframe la plus proche."""
    from simulation.recording.replay import ReplayReader
    from entities.genetics import Genome, N_GENES
    import math
    reader = ReplayReader(Path(db))
    snap   = reader.state_at(tick)
    reader.close()
    if snap is None:
        return {"diversity_index": 0.0, "gene_means": [0.0]*N_GENES,
                "gene_stds": [0.0]*N_GENES}
    genomes = []
    for e in snap.individuals:
        if not e.alive:
            continue
        if species and e.species != species:
            continue
        gj = getattr(e, "genome_json", "")
        if gj:
            genomes.append(Genome.from_json(gj).genes)
    if not genomes:
        return {"diversity_index": 0.0, "gene_means": [0.0]*N_GENES,
                "gene_stds": [0.0]*N_GENES}
    n = len(genomes)
    means = [sum(g[i] for g in genomes) / n for i in range(N_GENES)]
    stds  = [
        math.sqrt(sum((g[i] - means[i])**2 for g in genomes) / n)
        for i in range(N_GENES)
    ]
    diversity = sum(stds) / N_GENES
    return {"diversity_index": round(diversity, 4),
            "gene_means": [round(m, 4) for m in means],
            "gene_stds":  [round(s, 4) for s in stds]}


async def api_genetics(request):
    """GET /api/replay/genetics?db=...&tick=...&species=..."""
    db      = request.rel_url.query.get("db", "")
    tick    = int(request.rel_url.query.get("tick", 0))
    species = request.rel_url.query.get("species", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_genetics, db, tick, species)
    return web.json_response(data)


def _read_epidemic(db: str) -> dict:
    """Courbes S/E/I/R par espèce (depuis disease_states dans les events)."""
    import sqlite3
    conn = sqlite3.connect(db, check_same_thread=False)
    disease_events = []
    try:
        for (tick, payload_str) in conn.execute(
                "SELECT tick, payload FROM events WHERE kind IN "
                "('disease_infection','disease_death') ORDER BY tick"):
            disease_events.append((tick, json.loads(payload_str)))
    except Exception:
        pass
    conn.close()
    by_species: dict = {}
    for tick, p in disease_events:
        sp   = p.get("species", "?")
        kind = p.get("disease_name", "?")
        by_species.setdefault(sp, []).append({"tick": tick, "event": kind})
    return {"by_species": by_species, "total_events": len(disease_events)}


async def api_epidemic(request):
    """GET /api/analyse/epidemic?db=..."""
    db = request.rel_url.query.get("db", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_epidemic, db)
    return web.json_response(data)


def _export_csv(db: str) -> str:
    """Exporte les timeseries en CSV."""
    import csv, io
    ts   = _read_timeseries(db)
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
    ts = await loop.run_in_executor(None, _read_timeseries, db_path)
    return web.json_response(ts)


def _render_heatmap_png(db: str, tick: int, species: str,
                         out_w: int = 300, out_h: int = 300) -> bytes:
    """PNG heatmap de densité pour une espèce à un tick donné."""
    from simulation.recording.replay import ReplayReader
    import io
    try:
        from PIL import Image
        import numpy as np
        try:
            from scipy.stats import gaussian_kde
            _HAS_SCIPY = True
        except ImportError:
            _HAS_SCIPY = False

        reader = ReplayReader(Path(db))
        m      = reader.meta
        world_w = int(m.get("world_width", 500))
        world_h = int(m.get("world_height", 500))
        snap   = reader.state_at(tick)
        reader.close()
        if snap is None:
            raise ValueError("no snap")

        xs = np.array([e.x for e in snap.individuals if e.alive and e.species == species])
        ys = np.array([e.y for e in snap.individuals if e.alive and e.species == species])
        if len(xs) < 3 or not _HAS_SCIPY:
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

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        from PIL import Image
        import io
        img = Image.new("RGB", (out_w, out_h), (20, 20, 40))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


async def api_heatmap(request):
    """GET /api/replay/heatmap?db=...&tick=...&species=..."""
    db      = request.rel_url.query.get("db", "")
    tick    = int(request.rel_url.query.get("tick", 0))
    species = request.rel_url.query.get("species", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    png  = await loop.run_in_executor(None, _render_heatmap_png, db, tick, species)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-store"})


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
    app.router.add_get   ("/api/analyse/timeseries",    api_timeseries)
    app.router.add_get   ("/api/analyse/genealogy",     api_genealogy)
    app.router.add_get   ("/api/analyse/day_info",      api_day_info)
    app.router.add_get   ("/api/analyse/stats",         api_stats)
    app.router.add_get   ("/api/analyse/epidemic",      api_epidemic)
    app.router.add_patch ("/api/runs/{run_id}/tag",     api_runs_tag)
    app.router.add_get   ("/api/runs/compare",          api_runs_compare)
    app.router.add_get   ("/api/runs/{run_id}/export",  api_export)
    app.router.add_get   ("/api/replay/genetics",       api_genetics)
    app.router.add_get   ("/api/replay/heatmap",        api_heatmap)
    app.router.add_get   ("/ws",                        websocket_handler)
    return app


def run(host: str = "0.0.0.0", port: int = 9000) -> None:
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
        print(f"[EcoSim] Interface web → http://localhost:{port}", flush=True)
        threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{port}")).start()
        await asyncio.Event().wait()

    asyncio.run(_start())
