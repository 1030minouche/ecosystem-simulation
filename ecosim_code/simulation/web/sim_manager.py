"""
SimulationManager — thread simulation + push WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path


class SimulationManager:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop     = loop
        self._clients: set = set()
        self._thread: threading.Thread | None = None
        self._cancelled = False

    # ── WebSocket clients ─────────────────────────────────────────────────────

    def add_ws(self, ws) -> None:
        self._clients.add(ws)

    def remove_ws(self, ws) -> None:
        self._clients.discard(ws)

    def _push(self, msg: dict) -> None:
        txt = json.dumps(msg)
        for ws in list(self._clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_str(txt), self._loop)
            except Exception:
                pass

    # ── Simulation ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self._cancelled = True

    def start(self, config: dict) -> bool:
        if self.is_running():
            return False
        self._cancelled = False
        self._thread = threading.Thread(target=self._run, args=(config,), daemon=True)
        self._thread.start()
        return True

    def _run(self, config: dict) -> None:
        from world.grid import Grid
        from world.terrain import generate_terrain
        from simulation.engine import SimulationEngine
        from simulation.runner import EngineRunner
        from simulation.recording.recorder import Recorder
        from web.renderer import terrain_arr_from_grid, render_engine_frame, RENDER_W, RENDER_H
        from simulation.headless import load_diseases
        from pathlib import Path as _Path
        _diseases_dir = _Path(__file__).parent.parent / "species_data" / "diseases"
        if _diseases_dir.exists():
            load_diseases(_diseases_dir)

        try:
            total    = config["ticks"]
            out_path = Path(config.get("out_path", "runs/sim.db"))
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if config.get("mode") == "extend" and config.get("db_path"):
                from simulation.recording.resume import load_engine_from_db
                engine      = load_engine_from_db(Path(config["db_path"]))
                out_path    = Path(config["db_path"])
                colors: dict[str, tuple] = {
                    sp.name: tuple(int(c * 255) for c in sp.color[:3])
                    for sp in engine.species_list
                }
                terrain_arr = terrain_arr_from_grid(engine.grid, RENDER_W, RENDER_H)
                def frame_renderer(eng, tick):
                    return render_engine_frame(eng, terrain_arr, colors, RENDER_W, RENDER_H)
                kf_every = max(3, total // 400)
                recorder = Recorder(out_path, keyframe_every=kf_every,
                                    frame_renderer=frame_renderer, append=True)
            else:
                size   = config["grid_size"]
                preset = config.get("preset", "default")
                grid   = Grid(width=size, height=size)
                generate_terrain(grid, seed=config["seed"], preset=preset)

                colors = {}
                for sp_cfg in config["species"]:
                    p = sp_cfg.get("params", {})
                    name = p.get("name")
                    col  = p.get("color")
                    if name and col:
                        colors[name] = tuple(int(c * 255) for c in col[:3])

                terrain_arr = terrain_arr_from_grid(grid, RENDER_W, RENDER_H)
                def frame_renderer(eng, tick):
                    return render_engine_frame(eng, terrain_arr, colors, RENDER_W, RENDER_H)

                engine = SimulationEngine(grid, seed=config["seed"])
                for sp in config["species"]:
                    if not sp.get("enabled", True):
                        continue
                    params = dict(sp["params"])
                    params["color"] = tuple(params["color"])
                    engine.add_species(params, count=sp["count"])

                if out_path.exists():
                    out_path.unlink()
                kf_every = max(3, total // 400)
                recorder = Recorder(out_path, keyframe_every=kf_every,
                                    frame_renderer=frame_renderer)
                recorder.write_engine_meta(engine)
                recorder.write_meta("terrain_preset", preset)
                recorder.write_meta("max_ticks", str(total))
                recorder.write_species_params(engine.species_list)

            t0         = time.monotonic()
            start_tick = engine.tick_count

            def on_progress(tick: int, counts: dict) -> None:
                elapsed = time.monotonic() - t0
                done    = tick - start_tick
                tps     = done / elapsed if elapsed > 0 else 0
                eta_s   = (total - done) / tps if tps > 1 else None
                self._push({
                    "type":   "progress",
                    "tick":   tick,
                    "total":  start_tick + total,
                    "done":   done,
                    "ticks":  total,
                    "counts": counts,
                    "tps":    round(tps),
                    "eta_s":  round(eta_s) if eta_s is not None else None,
                })

            runner = EngineRunner(engine, recorder=recorder)
            runner.run(
                max_ticks=total,
                on_progress=on_progress,
                cancel_flag=lambda: self._cancelled,
            )
            recorder.close()

            if self._cancelled:
                self._push({"type": "cancelled"})
            else:
                self._push({"type": "done", "db_path": str(out_path).replace("\\", "/")})

        except Exception as exc:
            import traceback
            self._push({"type": "error", "message": str(exc),
                        "trace": traceback.format_exc()})
