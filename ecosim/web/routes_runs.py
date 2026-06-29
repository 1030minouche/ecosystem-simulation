"""
Endpoints de gestion des `.db` archivés sous `runs/` — extraits de `web/server.py`.

Routes enregistrées :
  - GET   /api/runs                       (liste + métadonnées enrichies)
  - PATCH /api/runs/{run_id}/tag          (assigne un libellé)
  - GET   /api/runs/compare?a=...&b=...   (compare 2 runs)
  - GET   /api/runs/{run_id}/export?format=csv|json

Les helpers `_RUNS_D` et `_quick_meta` restent dans `ecosim.web.server`
(source de vérité unique), ce module les lit au moment de l'appel HTTP.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from aiohttp import web

from ecosim.web import server as _server
from ecosim.web.routes_analyse import read_timeseries

logger = logging.getLogger(__name__)


# ── Helpers synchrones (pool threads) ─────────────────────────────────────────

def _enrich_run_meta(p) -> dict:
    """Construit le dict enrichi pour une run (appelé dans un thread pool)."""
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


def _compare_runs(db_a: str, db_b: str) -> dict:
    return {"run_a": read_timeseries(db_a), "run_b": read_timeseries(db_b)}


def _export_csv(db: str) -> str:
    """Exporte les timeseries en CSV."""
    ts     = read_timeseries(db)
    buf    = io.StringIO()
    all_sp = sorted({sp for row in ts for sp in row["counts"]})
    w = csv.writer(buf)
    w.writerow(["tick"] + all_sp)
    for row in ts:
        w.writerow([row["tick"]] + [row["counts"].get(sp, 0) for sp in all_sp])
    return buf.getvalue()


# ── Handlers ──────────────────────────────────────────────────────────────────

async def api_runs(request):
    result = []
    runs_dir = _server._RUNS_D
    if runs_dir.exists():
        loop = asyncio.get_event_loop()
        files = sorted(runs_dir.glob("*.db"), key=lambda f: -f.stat().st_mtime)
        for p in files:
            data = await loop.run_in_executor(None, _enrich_run_meta, p)
            result.append(data)
    return web.json_response(result)


async def api_runs_tag(request):
    """PATCH /api/runs/{run_id}/tag — assigne un libellé à une run."""
    run_id = request.match_info["run_id"]
    body   = await request.json()
    tag    = body.get("tag", "")
    runs_dir = _server._RUNS_D
    if not runs_dir.exists():
        raise web.HTTPNotFound()
    for p in runs_dir.glob("*.db"):
        if _server._quick_meta(str(p), "run_id") == run_id:
            conn = sqlite3.connect(str(p))
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('tag',?)", (tag,))
            conn.commit()
            conn.close()
            return web.json_response({"ok": True})
    raise web.HTTPNotFound()


async def api_runs_compare(request):
    a = request.rel_url.query.get("a", "")
    b = request.rel_url.query.get("b", "")
    if not a or not b or not Path(a).exists() or not Path(b).exists():
        raise web.HTTPNotFound()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _compare_runs, a, b)
    return web.json_response(data)


async def api_export(request):
    """GET /api/runs/{run_id}/export?format=csv|json"""
    run_id = request.match_info.get("run_id", "")
    fmt    = request.rel_url.query.get("format", "csv")
    runs_dir = _server._RUNS_D
    db_path = None
    if runs_dir.exists():
        for p in runs_dir.glob("*.db"):
            if _server._quick_meta(str(p), "run_id") == run_id:
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


# ── Enregistrement ────────────────────────────────────────────────────────────

def register_runs_routes(app: web.Application) -> None:
    app.router.add_get  ("/api/runs",                   api_runs)
    app.router.add_patch("/api/runs/{run_id}/tag",      api_runs_tag)
    app.router.add_get  ("/api/runs/compare",           api_runs_compare)
    app.router.add_get  ("/api/runs/{run_id}/export",   api_export)
