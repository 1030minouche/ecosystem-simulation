import csv
import pathlib
from datetime import datetime

_BASE_DIR    = pathlib.Path(__file__).parent.parent
_REPORTS_DIR = _BASE_DIR / "reports"


class DeathLogger:
    """Enregistre chaque mort d'individu dans un CSV pour analyse post-mortem."""

    FIELDS = ["tick", "species", "age", "energy", "x", "y",
              "state", "time_of_day", "is_night", "on_water", "cause"]

    def __init__(self):
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = str(_REPORTS_DIR / f"death_log_{ts}.csv")
        self._file   = open(filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.FIELDS)
        self.cause_counts: dict[str, int] = {}

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
        cause = getattr(ind, "death_cause", "unknown")
        self.cause_counts[cause] = self.cause_counts.get(cause, 0) + 1
        if tick % 500 == 0:
            self._file.flush()

    def close(self) -> None:
        self._file.close()
