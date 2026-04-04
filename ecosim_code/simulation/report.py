import json
import math
import os
from datetime import datetime

class SimulationReport:
    def __init__(self):
        self.start_time = datetime.now()
        self.history = []          # snapshot toutes les N ticks
        self.events = []           # extinctions, explosions, etc.
        self.species_stats = {}    # stats par espèce

    def record(self, tick: int, plants: list, individuals: list):
        """Appelé toutes les 50 ticks pour enregistrer l'état."""
        snapshot = {"tick": tick, "populations": {}}

        all_entities = [(p.species.name, "plant", p.energy, p.growth) for p in plants] + \
                       [(i.species.name, i.species.type, i.energy, i.age) for i in individuals]

        species_data = {}
        for name, stype, energy, extra in all_entities:
            if name not in species_data:
                species_data[name] = {
                    "count": 0,
                    "type": stype,
                    "total_energy": 0.0,
                    "min_energy": float("inf"),
                    "max_energy": 0.0,
                }
            d = species_data[name]
            d["count"] += 1
            d["total_energy"] += energy
            d["min_energy"] = min(d["min_energy"], energy)
            d["max_energy"] = max(d["max_energy"], energy)

        for name, d in species_data.items():
            d["avg_energy"] = round(d["total_energy"] / d["count"], 2)
            d["min_energy"] = round(d["min_energy"], 2)
            d["max_energy"] = round(d["max_energy"], 2)
            d.pop("total_energy")
            snapshot["populations"][name] = d

            # Init stats globales
            if name not in self.species_stats:
                self.species_stats[name] = {
                    "peak_population": 0,
                    "peak_tick": 0,
                    "extinct_tick": None,
                    "type": d["type"]
                }
            s = self.species_stats[name]
            if d["count"] > s["peak_population"]:
                s["peak_population"] = d["count"]
                s["peak_tick"] = tick

        # Détection d'extinction
        for name in self.species_stats:
            if (name not in species_data and
                    self.species_stats[name]["extinct_tick"] is None):
                self.species_stats[name]["extinct_tick"] = tick
                self.events.append({
                    "tick": tick,
                    "type": "extinction",
                    "species": name
                })
                print(f"💀 Extinction : {name} au tick {tick}")

        self.history.append(snapshot)

    def record_event(self, tick: int, event_type: str, details: str):
        self.events.append({
            "tick": tick,
            "type": event_type,
            "details": details
        })

    def _generate_charts(self, base_path: str) -> None:
        """Génère un graphique PNG de l'évolution des populations."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib non installé — graphiques désactivés")
            return

        if len(self.history) < 2:
            return

        all_species = sorted({
            name
            for snap in self.history
            for name in snap["populations"]
        })
        ticks = [s["tick"] for s in self.history]

        # Couleurs par type d'espèce
        type_colors = {"plant": "#4caf50", "herbivore": "#90caf9", "carnivore": "#ef9a9a"}
        type_map = {}
        for snap in self.history:
            for name, data in snap["populations"].items():
                type_map.setdefault(name, data["type"])

        fig, ax = plt.subplots(figsize=(13, 6))
        for sp in all_species:
            counts = [s["populations"].get(sp, {}).get("count", 0) for s in self.history]
            color  = type_colors.get(type_map.get(sp, "herbivore"), "#aaaaaa")
            ax.plot(ticks, counts, label=sp, linewidth=2.5, color=color)
            ax.fill_between(ticks, counts, alpha=0.08, color=color)

        ax.set_xlabel("Tick", fontsize=12)
        ax.set_ylabel("Population", fontsize=12)
        ax.set_title("Évolution des populations", fontsize=14, fontweight="bold")
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(base_path + ".png", dpi=120)
        plt.close(fig)
        print(f"📈 Graphique généré : {base_path}.png")

    def generate(self, tick: int, plants: list, individuals: list,
                 grid_width: int = 100, grid_height: int = 100) -> str:
        end_time = datetime.now()
        duration = (end_time - self.start_time).seconds

        # Populations finales
        final_populations = {}
        for p in plants:
            final_populations[p.species.name] = final_populations.get(p.species.name, 0) + 1
        for i in individuals:
            final_populations[i.species.name] = final_populations.get(i.species.name, 0) + 1

        # Indice de Shannon (biodiversité)
        total = sum(final_populations.values())
        shannon = 0.0
        if total > 0:
            for count in final_populations.values():
                if count > 0:
                    p = count / total
                    shannon -= p * math.log(p)
        shannon = round(shannon, 4)

        # Construction du rapport
        report = {
            "meta": {
                "date": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_seconds": duration,
                "total_ticks": tick,
                "grid_size": f"{grid_width}x{grid_height}"
            },
            "summary": {
                "final_populations": final_populations,
                "total_individuals_alive": total,
                "biodiversity_index_shannon": shannon,
                "species_survived": [k for k, v in self.species_stats.items()
                                     if v["extinct_tick"] is None],
                "species_extinct": [k for k, v in self.species_stats.items()
                                    if v["extinct_tick"] is not None],
            },
            "species_details": self.species_stats,
            "events": self.events,
            "population_history": self.history,
        }

        # Sauvegarde
        os.makedirs("reports", exist_ok=True)
        base     = f"reports/rapport_{self.start_time.strftime('%Y%m%d_%H%M%S')}"
        filename = base + ".json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Graphiques
        self._generate_charts(base)

        # Résumé texte
        txt = base + ".txt"
        with open(txt, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("          RAPPORT DE SIMULATION ECOSIM\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Date           : {report['meta']['date']}\n")
            f.write(f"Durée réelle   : {duration}s\n")
            f.write(f"Ticks simulés  : {tick}\n\n")

            f.write("── POPULATIONS FINALES ──\n")
            for sp, count in final_populations.items():
                f.write(f"  {sp:20} : {count} individus\n")

            f.write(f"\n── BIODIVERSITÉ ──\n")
            f.write(f"  Indice de Shannon   : {shannon}\n")
            f.write(f"  Espèces survivantes : {', '.join(report['summary']['species_survived']) or 'aucune'}\n")
            f.write(f"  Espèces éteintes    : {', '.join(report['summary']['species_extinct']) or 'aucune'}\n")

            f.write(f"\n── RECORDS PAR ESPÈCE ──\n")
            for name, stats in self.species_stats.items():
                f.write(f"\n  {name} ({stats['type']})\n")
                f.write(f"    Population max : {stats['peak_population']} (tick {stats['peak_tick']})\n")
                if stats['extinct_tick']:
                    f.write(f"    Extinction     : tick {stats['extinct_tick']}\n")
                else:
                    f.write(f"    Statut         : survivant\n")

            f.write(f"\n── ÉVÉNEMENTS ──\n")
            for ev in self.events:
                f.write(f"  [Tick {ev['tick']:5}] {ev['type']} — {ev.get('species', ev.get('details', ''))}\n")

            # Tableau d'évolution dans le temps
            f.write(f"\n── ÉVOLUTION DES POPULATIONS DANS LE TEMPS ──\n\n")

            # Récupère tous les noms d'espèces
            all_species = sorted(set(
                name
                for snapshot in self.history
                for name in snapshot["populations"].keys()
            ))

            # En-tête du tableau
            header = f"{'Tick':>8} │ " + " │ ".join(f"{sp:>12}" for sp in all_species)
            f.write(header + "\n")
            f.write("─" * len(header) + "\n")

            # Lignes du tableau
            for snapshot in self.history:
                row = f"{snapshot['tick']:>8} │ "
                row += " │ ".join(
                    f"{snapshot['populations'].get(sp, {}).get('count', 0):>12}"
                    for sp in all_species
                )
                f.write(row + "\n")

            f.write("\n" + "=" * 60 + "\n")


            print(f"📊 Rapport généré : {filename}")
            print(f"📄 Résumé texte   : {txt}")
            return filename