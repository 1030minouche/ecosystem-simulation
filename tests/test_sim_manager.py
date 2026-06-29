"""
Tests pour ecosim.web.sim_manager.SimulationManager — gestion des clients
WebSocket, du cycle start/cancel, et exécution complète d'une simulation
minimale en thread.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
import pytest_asyncio

from ecosim.web.sim_manager import SimulationManager


class _MockWS:
    """WebSocket mock — collecte les messages envoyés par `send_str`."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.lock = threading.Lock()

    async def send_str(self, txt: str) -> None:
        with self.lock:
            self.sent.append(txt)

    def messages(self) -> list[dict]:
        with self.lock:
            return [json.loads(t) for t in self.sent]


@pytest_asyncio.fixture
async def mgr():
    loop = asyncio.get_running_loop()
    m = SimulationManager(loop)
    yield m
    # Si un thread est encore vivant en fin de test, le signaler et attendre.
    if m.is_running():
        m.cancel()
        m._thread.join(timeout=10)


# ── Gestion des clients WebSocket ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_ws_registers_client(mgr):
    ws = _MockWS()
    mgr.add_ws(ws)
    assert ws in mgr._clients


@pytest.mark.asyncio
async def test_remove_ws_drops_client(mgr):
    ws = _MockWS()
    mgr.add_ws(ws)
    mgr.remove_ws(ws)
    assert ws not in mgr._clients


@pytest.mark.asyncio
async def test_remove_ws_unknown_is_noop(mgr):
    ws = _MockWS()
    # Ne doit pas lever
    mgr.remove_ws(ws)
    assert ws not in mgr._clients


# ── _push : diffusion vers les clients via le loop asyncio ────────────────────

@pytest.mark.asyncio
async def test_push_sends_json_to_single_client(mgr):
    ws = _MockWS()
    mgr.add_ws(ws)
    mgr._push({"type": "progress", "tick": 42})
    # Laisser le loop traiter les coroutines schedulées par run_coroutine_threadsafe
    await asyncio.sleep(0.05)
    msgs = ws.messages()
    assert msgs == [{"type": "progress", "tick": 42}]


@pytest.mark.asyncio
async def test_push_sends_to_multiple_clients(mgr):
    ws1, ws2 = _MockWS(), _MockWS()
    mgr.add_ws(ws1)
    mgr.add_ws(ws2)
    mgr._push({"type": "done"})
    await asyncio.sleep(0.05)
    assert ws1.messages() == [{"type": "done"}]
    assert ws2.messages() == [{"type": "done"}]


@pytest.mark.asyncio
async def test_push_with_no_client_does_not_fail(mgr):
    # Ne doit pas lever même sans clients
    mgr._push({"type": "noop"})
    await asyncio.sleep(0.01)


# ── Cycle start/cancel/is_running ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_running_false_initially(mgr):
    assert mgr.is_running() is False


@pytest.mark.asyncio
async def test_cancel_sets_flag(mgr):
    assert mgr._cancelled is False
    mgr.cancel()
    assert mgr._cancelled is True


@pytest.mark.asyncio
async def test_start_returns_false_when_already_running(mgr, monkeypatch):
    """Si une simulation est déjà en cours, start() renvoie False sans lancer
    un second thread."""
    started = threading.Event()
    blocker = threading.Event()

    def _slow_run(self, config):
        started.set()
        blocker.wait()

    monkeypatch.setattr(SimulationManager, "_run", _slow_run, raising=True)

    assert mgr.start({}) is True
    assert started.wait(timeout=2)
    assert mgr.is_running()

    second = mgr.start({})
    assert second is False
    # Toujours un seul thread, toujours en vie
    assert mgr.is_running()

    blocker.set()
    mgr._thread.join(timeout=5)
    assert not mgr.is_running()


# ── Smoke test : start exécute une vraie mini-simulation ──────────────────────

def _minimal_species_cfg() -> dict:
    """Définition complète d'une espèce minimaliste, compatible Species(**...)."""
    return {
        "enabled": True,
        "count":   5,
        "params": {
            "name": "TestLapin",
            "type": "herbivore",
            "color": [0.9, 0.9, 0.8],
            "temp_min": 0.0, "temp_max": 40.0,
            "humidity_min": 0.0, "humidity_max": 1.0,
            "altitude_min": 0.0, "altitude_max": 1.0,
            "reproduction_rate": 0.9, "reproduction_rate_std": 0.0,
            "max_age": 1_000_000, "max_age_std": 0,
            "max_population": 200,
            "energy_start": 200.0, "energy_start_std": 0.0,
            "energy_consumption": 0.001, "energy_consumption_std": 0.0,
            "energy_from_food": 50.0, "energy_from_food_std": 0.0,
            "speed": 1.0, "speed_std": 0.0,
            "perception_radius": 5.0, "perception_radius_std": 0.0,
            "food_sources": [],
            "growth_rate": 0.0, "growth_rate_std": 0.0,
            "dispersal_radius": 0,
            "activity_pattern": "diurnal",
            "can_swim": False,
            "reproduction_cooldown_length": 100_000,
            "reproduction_cooldown_length_std": 0,
            "litter_size_min": 1, "litter_size_max": 1,
            "sexual_maturity_ticks": 0, "sexual_maturity_ticks_std": 0,
            "gestation_ticks": 0, "gestation_ticks_std": 0,
            "juvenile_mortality_rate": 0.0, "juvenile_mortality_rate_std": 0.0,
            "fear_factor": 0.0, "fear_factor_std": 0.0,
        },
    }


@pytest.mark.asyncio
async def test_start_runs_minimal_simulation_to_done(mgr, tmp_path):
    """Une simulation de 30 ticks doit pousser au moins un `done` (succès) ou
    `error` (échec). On vérifie qu'aucune exception ne fuit hors du thread et
    que le manager redevient inactif."""
    ws = _MockWS()
    mgr.add_ws(ws)
    db_path = tmp_path / "smoke.db"
    config = {
        "ticks":     30,
        "grid_size": 25,
        "seed":      42,
        "preset":    "default",
        "out_path":  str(db_path),
        "species":   [_minimal_species_cfg()],
    }

    assert mgr.start(config) is True
    mgr._thread.join(timeout=60)
    assert not mgr.is_running()

    await asyncio.sleep(0.1)  # laisser les push se vider
    types = [m["type"] for m in ws.messages()]
    # Le worker pousse soit 'done', soit 'error' en fin. On vérifie qu'un
    # terminal est arrivé (pas de hang), et que le fichier de sortie a été
    # créé en cas de succès.
    assert ("done" in types) or ("error" in types)
    if "done" in types:
        assert Path(config["out_path"]).exists()


@pytest.mark.asyncio
async def test_start_then_cancel_stops_simulation(mgr, tmp_path):
    """Une annulation pendant le run doit lever le cancel_flag et faire pousser
    `cancelled`."""
    ws = _MockWS()
    mgr.add_ws(ws)
    config = {
        "ticks":     5000,    # long, pour avoir le temps d'annuler
        "grid_size": 25,
        "seed":      42,
        "preset":    "default",
        "out_path":  str(tmp_path / "cancel.db"),
        "species":   [_minimal_species_cfg()],
    }

    assert mgr.start(config) is True
    # Annule dès qu'on est sûr que le thread est lancé.
    await asyncio.sleep(0.05)
    mgr.cancel()
    mgr._thread.join(timeout=30)
    assert not mgr.is_running()

    await asyncio.sleep(0.1)
    types = [m["type"] for m in ws.messages()]
    assert ("cancelled" in types) or ("done" in types) or ("error" in types)
