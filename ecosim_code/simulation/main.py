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

TICK_INTERVAL = 0.050   # 50 ms entre chaque batch → 20 fps de simulation à ×1

def _sim_loop():
    while True:
        if engine.running:
            for _ in range(engine.speed):
                engine.tick()
        time.sleep(TICK_INTERVAL)

threading.Thread(target=_sim_loop, daemon=True).start()

# ── Viewer 2D (thread principal tkinter) ─────────────────────────────────────

from gui.viewer import SimViewer
SimViewer(engine).run()
