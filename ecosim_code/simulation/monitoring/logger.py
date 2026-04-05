import os
from datetime import datetime

class SimulationLogger:
    def __init__(self):
        os.makedirs("logs", exist_ok=True)
        filename = f"logs/sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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
        counts = {}
        for p in plants:
            counts[p.species.name] = counts.get(p.species.name, 0) + 1
        for i in individuals:
            counts[i.species.name] = counts.get(i.species.name, 0) + 1
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
