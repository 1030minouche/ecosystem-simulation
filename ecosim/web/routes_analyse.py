"""
Endpoints d'analyse — extraits de `web/server.py` pour le découper.

Tous les handlers ci-dessous reçoivent un chemin de `.db` en query
param et délèguent le travail bloquant (lectures SQLite, calculs)
à un thread pool via `loop.run_in_executor`.

Point d'entrée pour le serveur : `register_analyse_routes(app)`.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)


# ─── Helpers synchrones (exécutés dans le pool de threads) ───────────────────

def read_timeseries(db: str) -> list:
    """Toutes les populations par keyframe avec eco_metrics si disponible."""
    conn = sqlite3.connect(db, check_same_thread=False)
    try:
        try:
            rows = conn.execute(
                "SELECT tick, data, eco_metrics FROM counts ORDER BY tick"
            ).fetchall()
            if rows:
                conn.close()
                result = []
                for t, d, em in rows:
                    row: dict = {"tick": t, "counts": json.loads(d)}
                    if em:
                        try:
                            row["eco"] = json.loads(em)
                        except (json.JSONDecodeError, TypeError) as exc:
                            logger.debug("swallowed: %s", exc)
                    result.append(row)
                return result
        except sqlite3.Error as exc:
            logger.debug("swallowed: %s", exc)
        rows = conn.execute("SELECT tick, data FROM counts ORDER BY tick").fetchall()
        if rows:
            conn.close()
            return [{"tick": t, "counts": json.loads(d)} for t, d in rows]
    except sqlite3.Error as exc:
        logger.debug("swallowed: %s", exc)
    rows = conn.execute("SELECT tick, data_blob FROM keyframes ORDER BY tick").fetchall()
    conn.close()
    result = []
    for tick, blob in rows:
        data = json.loads(gzip.decompress(blob))
        result.append({"tick": tick, "counts": data["species_counts"]})
    return result


def _read_genealogy(db: str, entity_id: int) -> dict:
    """Arbre généalogique autour de entity_id (3 générations up + 2 down)."""
    conn = sqlite3.connect(db, check_same_thread=False)
    rows = conn.execute(
        "SELECT entity_id, tick, payload FROM events WHERE kind='birth'"
    ).fetchall()
    conn.close()

    by_id: dict     = {}
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
    """Snapshot de population au début du jour `day` (1-indexed)."""
    from ecosim.engine.engine_const import DAY_LENGTH
    from ecosim.engine.recording.replay import ReplayReader
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
    conn = sqlite3.connect(db, check_same_thread=False)
    births_by_sp: dict = {}
    try:
        for (payload_str,) in conn.execute(
                "SELECT payload FROM events WHERE kind='birth'"):
            sp = json.loads(payload_str).get("species", "?")
            births_by_sp[sp] = births_by_sp.get(sp, 0) + 1
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        logger.debug("swallowed: %s", exc)
    max_pops: dict = {}
    try:
        for (data,) in conn.execute("SELECT data FROM counts"):
            for sp, n in json.loads(data).items():
                if n > max_pops.get(sp, 0):
                    max_pops[sp] = n
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        logger.debug("swallowed: %s", exc)
    conn.close()
    return {"births_by_species": births_by_sp, "max_populations": max_pops}


def _read_genetics(db: str, tick: int, species: str) -> dict:
    """Calcule diversité génétique depuis la keyframe la plus proche."""
    import math

    from ecosim.engine.recording.replay import ReplayReader
    from ecosim.entities.genetics import N_GENES, Genome
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


def _read_epidemic(db: str) -> dict:
    """Épidémiologie : courbes, R₀, par espèce, métadonnées d'infection."""
    conn = sqlite3.connect(db, check_same_thread=False)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    infect_meta: dict = {}
    if meta.get("infect_disease"):
        infect_meta = {
            "disease":    meta.get("infect_disease", ""),
            "source_tick": int(meta.get("infect_tick", 0)),
            "source_db":   meta.get("infect_source", ""),
        }

    inf_events:   list[dict] = []
    death_events: list[dict] = []
    try:
        for (tick, eid, payload_str) in conn.execute(
                "SELECT tick, entity_id, payload FROM events "
                "WHERE kind='disease_infection' ORDER BY tick"):
            p = json.loads(payload_str)
            inf_events.append({
                "tick": tick, "uid": eid, "type": "infection",
                "disease": p.get("disease_name", "?"),
                "species": p.get("species", "?"),
                "source_uid": p.get("source_uid", -1),
            })
        for (tick, eid, payload_str) in conn.execute(
                "SELECT tick, entity_id, payload FROM events "
                "WHERE kind='disease_death' ORDER BY tick"):
            p = json.loads(payload_str)
            death_events.append({
                "tick": tick, "uid": eid, "type": "death",
                "disease": p.get("disease_name", "?"),
                "species": p.get("species", "?"),
                "source_uid": -1,
            })
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        logger.debug("swallowed: %s", exc)
    conn.close()

    diseases   = sorted({e["disease"] for e in inf_events + death_events})
    cumulative = {d: sum(1 for e in inf_events   if e["disease"] == d) for d in diseases}
    deaths     = {d: sum(1 for e in death_events if e["disease"] == d) for d in diseases}

    BIN = 200
    infections_by_tick: list[dict] = []
    if inf_events:
        min_t = inf_events[0]["tick"]
        max_t = inf_events[-1]["tick"]
        for b in range(min_t, max_t + BIN, BIN):
            row: dict = {"tick": b}
            for d in diseases:
                row[d] = sum(1 for e in inf_events
                             if e["disease"] == d and b <= e["tick"] < b + BIN)
            infections_by_tick.append(row)

    r0: dict = {}
    for d in diseases:
        sources = [e["source_uid"] for e in inf_events
                   if e["disease"] == d and e["source_uid"] >= 0]
        if sources:
            c = Counter(sources)
            r0[d] = round(sum(c.values()) / len(c), 2)

    by_species: dict = {}
    for e in inf_events:
        by_species.setdefault(e["species"], {}).setdefault(e["disease"], 0)
        by_species[e["species"]][e["disease"]] += 1

    all_ev = sorted(inf_events + death_events, key=lambda x: x["tick"])
    return {
        "diseases":           diseases,
        "total_infections":   sum(cumulative.values()),
        "total_deaths":       sum(deaths.values()),
        "cumulative":         cumulative,
        "deaths":             deaths,
        "r0":                 r0,
        "infections_by_tick": infections_by_tick,
        "by_species":         by_species,
        "recent_events":      all_ev[-60:],
        "infect_meta":        infect_meta,
    }


def _render_heatmap_png(db: str, tick: int, species: str,
                         out_w: int = 300, out_h: int = 300) -> bytes:
    """PNG heatmap de densité pour une espèce à un tick donné."""
    import io

    from PIL import Image

    from ecosim.engine.recording.replay import ReplayReader
    from ecosim.web.renderer import render_heatmap
    try:
        reader  = ReplayReader(Path(db))
        m       = reader.meta
        world_w = int(m.get("world_width", 500))
        world_h = int(m.get("world_height", 500))
        snap    = reader.state_at(tick)
        reader.close()
        if snap is None:
            raise ValueError("no snap")
        return render_heatmap(snap, world_w, world_h, species, out_w, out_h)
    except (sqlite3.Error, OSError, ValueError, KeyError, AttributeError) as exc:
        logger.debug("heatmap fallback: %s", exc)
        img = Image.new("RGB", (out_w, out_h), (20, 20, 40))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


# ─── Handlers aiohttp ────────────────────────────────────────────────────────

def _require_db(request) -> str:
    db = request.rel_url.query.get("db", "")
    if not db or not Path(db).exists():
        raise web.HTTPNotFound()
    return db


async def api_timeseries(request):
    db   = _require_db(request)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, read_timeseries, db)
    return web.json_response(data)


async def api_genealogy(request):
    db   = _require_db(request)
    eid  = int(request.rel_url.query.get("id", "0"))
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_genealogy, db, eid)
    return web.json_response(data)


async def api_day_info(request):
    db   = _require_db(request)
    day  = int(request.rel_url.query.get("day", "1"))
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_day_info, db, day)
    return web.json_response(data)


async def api_stats(request):
    db   = _require_db(request)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_stats, db)
    return web.json_response(data)


async def api_genetics(request):
    """GET /api/replay/genetics?db=...&tick=...&species=..."""
    db      = _require_db(request)
    tick    = int(request.rel_url.query.get("tick", 0))
    species = request.rel_url.query.get("species", "")
    loop    = asyncio.get_event_loop()
    data    = await loop.run_in_executor(None, _read_genetics, db, tick, species)
    return web.json_response(data)


async def api_epidemic(request):
    """GET /api/analyse/epidemic?db=..."""
    db   = _require_db(request)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _read_epidemic, db)
    return web.json_response(data)


async def api_heatmap(request):
    """GET /api/replay/heatmap?db=...&tick=...&species=..."""
    db      = _require_db(request)
    tick    = int(request.rel_url.query.get("tick", 0))
    species = request.rel_url.query.get("species", "")
    loop    = asyncio.get_event_loop()
    png     = await loop.run_in_executor(None, _render_heatmap_png, db, tick, species)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-store"})


# ─── Enregistrement ──────────────────────────────────────────────────────────

def register_analyse_routes(app) -> None:
    """Branche les routes /api/analyse/* + /api/replay/genetics, /heatmap."""
    app.router.add_get("/api/analyse/timeseries", api_timeseries)
    app.router.add_get("/api/analyse/genealogy",  api_genealogy)
    app.router.add_get("/api/analyse/day_info",   api_day_info)
    app.router.add_get("/api/analyse/stats",      api_stats)
    app.router.add_get("/api/analyse/epidemic",   api_epidemic)
    app.router.add_get("/api/replay/genetics",    api_genetics)
    app.router.add_get("/api/replay/heatmap",     api_heatmap)
