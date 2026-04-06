import csv
import os
from datetime import datetime

class DeathLogger:
    """Enregistre chaque mort d'individu dans un CSV pour analyse post-mortem."""

    FIELDS = ["tick", "species", "age", "energy", "x", "y",
              "state", "time_of_day", "is_night", "on_water", "cause"]

    def __init__(self):
        os.makedirs("reports", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"reports/death_log_{ts}.csv"
        self._file   = open(filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.FIELDS)

    def record(self, ind, tick: int) -> None:
        self._writer.writerow([
            tick,
            ind.species.name,
            ind.age,
            round(ind.energy, 2),
            round(ind.x, 1),
            round(ind.y, 1),
            getattr(ind, "death_state",        "?"),
            round(getattr(ind, "death_tod",    -1), 3),
            getattr(ind, "death_is_night",     "?"),
            getattr(ind, "death_on_water",     "?"),
            getattr(ind, "death_cause",        "unknown"),
        ])
        self._file.flush()

    def close(self) -> None:
        self._file.close()
