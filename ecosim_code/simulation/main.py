import glob
import json
import os
import threading
import time
from world.grid import Grid
from world.terrain import generate_terrain
from simulation.engine import SimulationEngine

os.makedirs("saves", exist_ok=True)

# ── Initialisation ────────────────────────────────────────────────────────────

grid = Grid(width=500, height=500)
generate_terrain(grid, seed=42)
engine = SimulationEngine(grid)

# ── Éditeur de terrain (bloquant — s'exécute dans le thread principal) ────────

print("=" * 60)
print("  EcoSim — Éditeur de terrain")
print("  Configurez le terrain puis cliquez Confirmer.")
print("=" * 60)

from gui.terrain_editor import TerrainEditorGUI

def _noop(_=None): pass

gui = TerrainEditorGUI(engine.grid, _noop, _noop)
result = gui.run()
print("Terrain", "confirmé." if result == "confirm" else "annulé (terrain original conservé).")

# ── Chargement des espèces APRÈS confirmation du terrain ─────────────────────
# (les cellules valides pour le spawn dépendent du terrain final)

_species_dir = os.path.join(os.path.dirname(__file__), "species")
for _path in sorted(glob.glob(os.path.join(_species_dir, "*.json"))):
    with open(_path, encoding="utf-8") as _f:
        _spec = json.load(_f)
    _params = _spec["params"]
    _params["color"] = tuple(_params["color"])
    engine.add_species(_params, count=_spec["count"])

# ── Thread de simulation ──────────────────────────────────────────────────────

TICK_RATE  = 20    # ticks/s à ×1
MAX_BATCH  = 200   # cap de sécurité : jamais plus de N ticks par itération

def _sim_loop():
    """Boucle time-based avec accumulateur fractionnaire.

    Au lieu d'un gros burst (speed × ticks d'un coup puis 50 ms de silence),
    on distribue les ticks en petits lots réguliers selon le temps réel écoulé.
    Résultat : le compteur de ticks avance de façon linéaire quelle que soit
    la vitesse choisie.
    """
    _acc  = 0.0
    _last = time.monotonic()
    while True:
        time.sleep(0.002)          # polling court ; Windows arrondira à ~15 ms, c'est OK
        now = time.monotonic()
        dt  = now - _last
        _last = now
        if not engine.running:
            _acc = 0.0             # réinitialise l'accumulateur à la pause
            continue
        _acc += dt * TICK_RATE * engine.speed
        n = min(int(_acc), MAX_BATCH)
        if n <= 0:
            continue
        _acc -= n                  # conserve la partie fractionnaire
        with engine.lock:
            for _ in range(n):
                engine.tick()

threading.Thread(target=_sim_loop, daemon=True).start()

# ── Viewer 2D (thread principal tkinter) ─────────────────────────────────────

from gui.viewer import SimViewer
SimViewer(engine).run()
