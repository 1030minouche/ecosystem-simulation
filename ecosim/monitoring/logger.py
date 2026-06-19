import logging
import pathlib
from datetime import datetime

from ecosim.engine.utils.counting import count_by_species

logger = logging.getLogger(__name__)

def _logs_dir() -> pathlib.Path:
    """logs/ vit dans le cwd (où l'utilisateur lance ecosim), pas dans le paquet."""
    return pathlib.Path.cwd() / "logs"


class SimulationLogger:
    def __init__(self):
        logs_dir = _logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        filename = str(logs_dir / f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.file = open(filename, "w", encoding="utf-8")
        self.filename = filename
        self._write_header()
        logger.info("Log démarré : %s", filename)

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
        logger.info("Log fermé : %s", self.filename)
