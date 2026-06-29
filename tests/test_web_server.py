"""
Tests HTTP de bout en bout pour ecosim.web.server via aiohttp.test_utils.

On évite la dépendance pytest-aiohttp en construisant TestServer/TestClient
à la main dans une fixture. Le module-level `_mgr` du serveur est neutralisé
par un faux SimulationManager pour ne lancer aucun thread de simulation.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from ecosim.web import server as server_mod
from ecosim.web.server import _build_app


class _FakeMgr:
    """SimulationManager double — n'instancie aucun thread."""

    def __init__(self) -> None:
        self.start_calls: list[dict] = []
        self.cancel_calls: int = 0
        self.next_start_result: bool = True

    def start(self, config: dict) -> bool:
        self.start_calls.append(config)
        return self.next_start_result

    def cancel(self) -> None:
        self.cancel_calls += 1

    def is_running(self) -> bool:
        return False

    def add_ws(self, ws) -> None:  # pragma: no cover
        pass

    def remove_ws(self, ws) -> None:  # pragma: no cover
        pass


def _seed_species_dir(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "lapin.json").write_text(json.dumps({
        "count": 50,
        "params": {"name": "Lapin", "color": [0.9, 0.9, 0.8]},
    }), encoding="utf-8")
    (target / "renard.json").write_text(json.dumps({
        "count": 10,
        "params": {"name": "Renard", "color": [0.8, 0.4, 0.1]},
    }), encoding="utf-8")


def _seed_diseases_dir(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "myxo.json").write_text(json.dumps({
        "name": "myxomatosis",
        "transmission_rate": 0.4,
        "mortality_chance": 0.6,
        "infectious_ticks": 200,
    }), encoding="utf-8")


def _seed_run_db(target: Path, run_id: str = "abc123") -> Path:
    db = target / f"run_{run_id}.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE counts(tick INTEGER PRIMARY KEY, data TEXT, eco_metrics TEXT);
        CREATE TABLE keyframes(tick INTEGER PRIMARY KEY, data_blob BLOB);
    """)
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [
            ("run_id", run_id),
            ("seed", "42"),
            ("terrain_preset", "temperate"),
            ("engine_version", "0.6.0"),
        ],
    )
    conn.executemany(
        "INSERT INTO counts(tick, data, eco_metrics) VALUES (?, ?, ?)",
        [
            (0,   json.dumps({"Lapin": 10, "Renard": 2}), None),
            (100, json.dumps({"Lapin": 12, "Renard": 3}), None),
        ],
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    """Isole runs/, species/, diseases/, et injecte un faux _mgr."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    species_dir = tmp_path / "species"
    diseases_dir = tmp_path / "diseases"
    _seed_species_dir(species_dir)
    _seed_diseases_dir(diseases_dir)

    monkeypatch.setattr(server_mod, "_RUNS_D", runs_dir)
    monkeypatch.setattr(server_mod, "_SPECIES_D", species_dir)
    monkeypatch.setattr(server_mod, "_DISEASES_D", diseases_dir)
    monkeypatch.setattr(server_mod, "_species_colors", None)

    fake_mgr = _FakeMgr()
    monkeypatch.setattr(server_mod, "_mgr", fake_mgr)

    return {
        "tmp_path":    tmp_path,
        "runs_dir":    runs_dir,
        "species_dir": species_dir,
        "diseases_dir": diseases_dir,
        "mgr":         fake_mgr,
    }


@pytest_asyncio.fixture
async def client(web_env):
    app = _build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.mark.asyncio
async def test_get_species_returns_list(client, web_env):
    resp = await client.get("/api/species")
    assert resp.status == 200
    data = await resp.json()
    names = [item["name"] for item in data]
    assert "Lapin" in names
    assert "Renard" in names
    item = next(x for x in data if x["name"] == "Lapin")
    assert item["color"].startswith("#")
    assert item["count_default"] == 50


@pytest.mark.asyncio
async def test_get_diseases_returns_list(client, web_env):
    resp = await client.get("/api/diseases")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "myxomatosis"
    assert data[0]["transmission_rate"] == 0.4


@pytest.mark.asyncio
async def test_get_diseases_empty_when_no_dir(client, web_env, monkeypatch):
    monkeypatch.setattr(server_mod, "_DISEASES_D", web_env["tmp_path"] / "missing")
    resp = await client.get("/api/diseases")
    assert resp.status == 200
    assert await resp.json() == []


@pytest.mark.asyncio
async def test_post_sim_start_forwards_config(client, web_env):
    cfg = {"out_path": "runs/test.db", "ticks": 100, "seed": 7}
    resp = await client.post("/api/sim/start", json=cfg)
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True, "already_running": False}
    assert len(web_env["mgr"].start_calls) == 1
    assert web_env["mgr"].start_calls[0]["ticks"] == 100


@pytest.mark.asyncio
async def test_post_sim_start_already_running(client, web_env):
    web_env["mgr"].next_start_result = False
    resp = await client.post("/api/sim/start", json={"out_path": "runs/x.db"})
    assert (await resp.json()) == {"ok": False, "already_running": True}


@pytest.mark.asyncio
async def test_post_sim_cancel(client, web_env):
    resp = await client.post("/api/sim/cancel")
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True}
    assert web_env["mgr"].cancel_calls == 1


@pytest.mark.asyncio
async def test_post_replay_infect_404_when_db_missing(client, web_env):
    resp = await client.post("/api/replay/infect", json={
        "db": str(web_env["tmp_path"] / "nope.db"),
        "tick": 100,
        "disease_name": "myxo",
    })
    assert resp.status == 404
    body = await resp.json()
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_post_replay_infect_400_when_disease_missing(client, web_env):
    db = _seed_run_db(web_env["runs_dir"])
    resp = await client.post("/api/replay/infect", json={
        "db": str(db),
        "tick": 100,
        "disease_name": "",
    })
    assert resp.status == 400
    body = await resp.json()
    assert "maladie" in body["error"].lower()


@pytest.mark.asyncio
async def test_post_replay_infect_single_target(client, web_env):
    db = _seed_run_db(web_env["runs_dir"])
    resp = await client.post("/api/replay/infect", json={
        "db": str(db),
        "tick": 50,
        "disease_name": "myxo",
        "species": "Lapin",
        "x": 12.5, "y": 33.0,
    })
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["n_targets"] == 1
    sent = web_env["mgr"].start_calls[-1]
    assert sent["mode"] == "infect"
    assert sent["targets"] == [{"species": "Lapin", "x": 12.5, "y": 33.0}]


@pytest.mark.asyncio
async def test_post_replay_infect_multi_targets(client, web_env):
    db = _seed_run_db(web_env["runs_dir"])
    resp = await client.post("/api/replay/infect", json={
        "db":  str(db),
        "tick": 50,
        "disease_name": "myxo",
        "targets": [
            {"species": "Lapin",  "x": 1.0, "y": 2.0},
            {"species": "Renard", "x": 5.0, "y": 6.0},
        ],
    })
    body = await resp.json()
    assert body["ok"] is True
    assert body["n_targets"] == 2
    sent = web_env["mgr"].start_calls[-1]
    assert len(sent["targets"]) == 2
    assert sent["species"] == "Lapin"


@pytest.mark.asyncio
async def test_get_runs_empty(client, web_env):
    resp = await client.get("/api/runs")
    assert resp.status == 200
    assert (await resp.json()) == []


@pytest.mark.asyncio
async def test_get_runs_lists_db_with_meta(client, web_env):
    _seed_run_db(web_env["runs_dir"], run_id="abc123")
    resp = await client.get("/api/runs")
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "abc123"
    assert data[0]["seed"] == 42
    assert data[0]["terrain_preset"] == "temperate"
    assert "Lapin" in data[0]["species"]
    assert data[0]["max_populations"]["Lapin"] == 12


@pytest.mark.asyncio
async def test_patch_run_tag_persists_meta(client, web_env):
    db = _seed_run_db(web_env["runs_dir"], run_id="run_tagme")
    resp = await client.patch(
        "/api/runs/run_tagme/tag",
        json={"tag": "interesting"},
    )
    assert resp.status == 200
    assert (await resp.json()) == {"ok": True}
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT value FROM meta WHERE key='tag'").fetchone()
    conn.close()
    assert row[0] == "interesting"


@pytest.mark.asyncio
async def test_patch_run_tag_404_when_unknown(client, web_env):
    _seed_run_db(web_env["runs_dir"], run_id="other")
    resp = await client.patch(
        "/api/runs/missing/tag",
        json={"tag": "anything"},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_replay_meta_404_when_db_missing(client, web_env):
    resp = await client.get(
        "/api/replay/meta",
        params={"db": str(web_env["tmp_path"] / "missing.db")},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_frame_img_404_when_db_missing(client, web_env):
    resp = await client.get(
        "/api/replay/frame_img",
        params={"db": str(web_env["tmp_path"] / "missing.db"), "tick": "0"},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_export_404_when_run_unknown(client, web_env):
    resp = await client.get("/api/runs/unknown/export", params={"format": "csv"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_export_csv(client, web_env):
    _seed_run_db(web_env["runs_dir"], run_id="exp1")
    resp = await client.get("/api/runs/exp1/export", params={"format": "csv"})
    assert resp.status == 200
    body = await resp.text()
    assert body.splitlines()[0].startswith("tick,Lapin,Renard")
    assert "100,12,3" in body


@pytest.mark.asyncio
async def test_export_json(client, web_env):
    _seed_run_db(web_env["runs_dir"], run_id="exp2")
    resp = await client.get("/api/runs/exp2/export", params={"format": "json"})
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 2
    assert data[0]["counts"]["Lapin"] == 10
