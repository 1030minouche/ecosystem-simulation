import pathlib
from datetime import datetime
from simulation.utils.counting import count_by_species

_BASE_DIR = pathlib.Path(__file__).parent.parent
_LOGS_DIR = _BASE_DIR / "logs"


class SimulationLogger:
    def __init__(self):
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        filename = str(_LOGS_DIR / f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.file = open(filename, "w", encoding="utf-8")
        self.filename = filename
        self._write_header()
        print(f"📝 Log démarré : {filename}")

    def _write_header(self):
        self.file.write("=" * 60 + "\n")
        self.file.write(f"  ECOSIM LOG — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.file.write("=" * 60 + "\n\n")
        self.file.flush()

    def log(self, tick: int, plants: list, individuals: list):
        """Appelé périodiquement (pas à chaque tick)."""
        counts = count_by_species(list(plants) + list(individuals))
        total = sum(counts.values())
        line = f"[Tick {tick:>6}] total={total:>5} │ "
        line += "  ".join(f"{name}: {count:>4}" for name, count in sorted(counts.items()))
        self.file.write(line + "\n")

    def log_event(self, tick: int, message: str):
        """Pour les événements importants — extinction, explosion, reset."""
        self.file.write(f"\n{'─'*60}\n")
        self.file.write(f"  ⚡ [Tick {tick}] {message}\n")
        self.file.write(f"{'─'*60}\n\n")
        self.file.flush()

    def close(self):
        self.file.write("\n" + "=" * 60 + "\n")
        self.file.write("  FIN DU LOG\n")
        self.file.write("=" * 60 + "\n")
        self.file.close()
        print(f"📝 Log fermé : {self.filename}")
