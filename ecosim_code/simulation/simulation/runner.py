"""
EngineRunner — boucle de run réutilisable.

Encapsule "tant que alive et tick < max, appelle engine.tick()" pour éviter
la duplication entre le mode headless et le viewer Tk.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.engine import SimulationEngine
    from simulation.recording.recorder import Recorder


@dataclass
class RunSummary:
    ticks_done: int
    elapsed_s: float
    final_populations: dict[str, int]
    death_causes: dict[str, int]


class EngineRunner:
    def __init__(
        self,
        engine: "SimulationEngine",
        recorder: "Recorder | None" = None,
    ) -> None:
        self.engine   = engine
        self.recorder = recorder

    def run(
        self,
        max_ticks: int,
        on_progress: Callable[[int, dict], None] | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> RunSummary:
        engine    = self.engine
        recorder  = self.recorder
        t_start   = time.monotonic()
        last_prog = 0
        target    = engine.tick_count + max_ticks

        while engine.tick_count < target:
            if cancel_flag is not None and cancel_flag():
                break

            engine.tick()

            if recorder is not None:
                recorder.on_tick_end(engine)

            tick = engine.tick_count
            if on_progress is not None and tick - last_prog >= 500:
                on_progress(tick, dict(engine.species_counts))
                last_prog = tick

        elapsed = time.monotonic() - t_start

        death_causes: dict[str, int] = dict(
            getattr(engine.death_log, "cause_counts", {})
        )

        return RunSummary(
            ticks_done=max_ticks,
            elapsed_s=elapsed,
            final_populations=dict(engine.species_counts),
            death_causes=death_causes,
        )
