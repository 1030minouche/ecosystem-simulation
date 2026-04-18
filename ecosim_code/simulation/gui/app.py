"""
EcoSim — Fenêtre principale (SETUP → RUNNING → REPLAY).
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import font as tkfont

WIN_W = 1100
WIN_H = 720

# ── Palette globale ───────────────────────────────────────────────────────────
C_BG      = "#0d0d1a"
C_PANEL   = "#16213e"
C_CARD    = "#1a2540"
C_BORDER  = "#2a2a4a"
C_ACCENT  = "#4e9af1"
C_DANGER  = "#e94560"
C_SUCCESS = "#4ecdc4"
C_TEXT    = "#e8e8f0"
C_SUB     = "#8888aa"
C_WARN    = "#f7dc6f"


class EcoSimApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("EcoSim — Simulateur d'écosystème")
        self.root.configure(bg=C_BG)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)

        self._fonts: dict[str, tkfont.Font] = {}
        self._setup_fonts()

        self._container = tk.Frame(self.root, bg=C_BG)
        self._container.place(x=0, y=0, width=WIN_W, height=WIN_H)

        self._frames: dict = {}
        self._current: str | None = None
        self._sim_thread: threading.Thread | None = None

        self._init_frames()
        self.show_frame("setup")

    # ── Polices ───────────────────────────────────────────────────────────────

    def _setup_fonts(self) -> None:
        self._fonts["title"]  = tkfont.Font(family="Consolas", size=16, weight="bold")
        self._fonts["h2"]     = tkfont.Font(family="Consolas", size=11, weight="bold")
        self._fonts["body"]   = tkfont.Font(family="Consolas", size=10)
        self._fonts["small"]  = tkfont.Font(family="Consolas", size=9)
        self._fonts["mono"]   = tkfont.Font(family="Consolas", size=10)

    def font(self, name: str) -> tkfont.Font:
        return self._fonts.get(name, self._fonts["body"])

    # ── Frames ────────────────────────────────────────────────────────────────

    def _init_frames(self) -> None:
        from gui.frames.setup_frame import SetupFrame
        from gui.frames.run_frame import RunFrame
        from gui.frames.replay_frame import ReplayFrame

        self._frames["setup"]  = SetupFrame(self._container, self)
        self._frames["run"]    = RunFrame(self._container, self)
        self._frames["replay"] = ReplayFrame(self._container, self)

    def show_frame(self, name: str) -> None:
        if self._current:
            self._frames[self._current].place_forget()
        self._frames[name].place(x=0, y=0, width=WIN_W, height=WIN_H)
        self._current = name
        frame = self._frames[name]
        if hasattr(frame, "on_show"):
            frame.on_show()

    # ── Lancement simulation ──────────────────────────────────────────────────

    def start_simulation(self, config: dict) -> None:
        run_frame = self._frames["run"]
        run_frame.prepare(config)
        self.show_frame("run")
        self._sim_thread = threading.Thread(
            target=self._sim_worker, args=(config,), daemon=True
        )
        self._sim_thread.start()

    def _sim_worker(self, config: dict) -> None:
        from pathlib import Path
        from world.grid import Grid
        from world.terrain import generate_terrain
        from simulation.engine import SimulationEngine
        from simulation.runner import EngineRunner
        from simulation.recording.recorder import Recorder

        run_frame = self._frames["run"]

        try:
            grid = Grid(width=config["grid_size"], height=config["grid_size"])
            generate_terrain(grid, seed=config["seed"], preset=config.get("preset", "default"))

            engine = SimulationEngine(grid, seed=config["seed"])

            for sp in config["species"]:
                if not sp["enabled"]:
                    continue
                params = dict(sp["params"])
                params["color"] = tuple(params["color"])
                engine.add_species(params, count=sp["count"])

            out_path = Path(config["out_path"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            recorder = Recorder(out_path)
            recorder.write_engine_meta(engine)

            def on_progress(tick: int, species_counts: dict) -> None:
                if run_frame.cancelled:
                    return
                self.root.after(0, run_frame.update_progress,
                                tick, config["ticks"], species_counts)

            runner = EngineRunner(engine, recorder=recorder)
            runner.run(
                max_ticks=config["ticks"],
                on_progress=on_progress,
                cancel_flag=lambda: run_frame.cancelled,
            )
            recorder.close()

            if not run_frame.cancelled:
                self.root.after(0, run_frame.on_done, str(out_path))

        except Exception as exc:
            self.root.after(0, run_frame.on_error, str(exc))

    # ── Replay ────────────────────────────────────────────────────────────────

    def open_replay(self, db_path: str) -> None:
        replay_frame = self._frames["replay"]
        replay_frame.load(db_path)
        self.show_frame("replay")

    def back_to_setup(self) -> None:
        self.show_frame("setup")

    # ── Boucle principale ─────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()
