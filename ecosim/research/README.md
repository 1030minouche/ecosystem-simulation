# `research/` — outils hors runtime

Ce dossier regroupe les modules destinés au **post-traitement scientifique**
et aux **expériences batch**. Ils sont **jamais importés par le runtime**
(moteur, web, headless) ; ils s'utilisent depuis des scripts et des notebooks.

## Contenu

### `research/analysis/` — métriques scientifiques

- `stats.py` — `aggregate_replicates()`, `bootstrap_ci()` pour multi-réplicats.
- `genetics_metrics.py` — He, π, Fst, fréquences alléliques (Nei 1973, Wright 1951).
- `epidemiology.py` — `compute_R0()` empirique depuis un `.db`.
- `export.py` — export CSV/Parquet (populations, life-history, génétique, events, spatial).

### `research/batch/` — sweeps de paramètres

- `sweep.py` — `ParameterSweep` : N simulations × M réplicats, agrégation.

## Exemples d'usage

```python
# Post-traitement d'un run
from ecosim.research.analysis.genetics_metrics import compute_diversity_at_tick
diversity = compute_diversity_at_tick("runs/sim.db", tick=5000, species="lapin")

# R₀ empirique
from ecosim.research.analysis.epidemiology import compute_R0
r0 = compute_R0("runs/sim.db", disease_name="myxomatosis")

# Sweep de paramètres
from ecosim.research.batch.sweep import ParameterSweep, SweepParam
sweep = ParameterSweep(
    base_species_dir="species/",
    out_dir="runs/sweep_speed",
    params=[SweepParam("speed", [0.5, 1.0, 2.0])],
    n_ticks=10_000,
    n_replicates=5,
)
sweep.run()
```

## Pourquoi un dossier séparé ?

- **Signal d'intention** : tout ce qui est sous `research/` ne s'exécute
  pas pendant une simulation live. Le moteur reste minimal.
- **Pas de dépendance circulaire** possible avec le runtime (le moteur ne
  doit JAMAIS importer depuis `research/`).
- **Faciliter les futures contributions** : pour ajouter un script
  d'analyse, on sait où le poser.
