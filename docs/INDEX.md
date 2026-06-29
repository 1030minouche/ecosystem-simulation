# Index du dépôt EcoSim

Cartographie exhaustive des fichiers suivis par git, organisée par module.
Pour chaque fichier : rôle en une ligne + statut (✅ vivant / 🧪 expérimental / ⚠️ candidat nettoyage).

> Mise à jour : `chore/package-and-perf` — après restructure en paquet `ecosim/` pip-installable.

---

## Racine du dépôt

| Fichier | Rôle | Statut |
|---|---|---|
| `README.md` | Pitch, install, lancement, structure, lien ODD. | ✅ |
| `LICENSE` | CC0 1.0 Universal. | ✅ |
| `pyproject.toml` | Métadonnées paquet, dépendances bornées, packages, entry-point `ecosim`, configs `ruff` et `pytest`. | ✅ |
| `.gitignore` | Ignore `__pycache__`, `logs/`, `reports/`, `runs/`, audits internes. | ✅ |
| `.github/workflows/ci.yml` | CI GitHub (pytest + ruff sur 3.10/3.11/3.12) — **bloquante**. | ✅ |
| `lancer_simulation.bat` | Raccourci Windows : `pip install -e .` puis `ecosim`. | ✅ |

---

## `ecosim/` — paquet pip-installable

| Fichier | Rôle | Statut |
|---|---|---|
| `__init__.py` | Expose `__version__`. | ✅ |
| `__main__.py` | Active `python -m ecosim`. | ✅ |
| `main.py` | CLI : `main()` dispatcher → `--headless`, `--purge-runs` ou serveur web. Entry-point `ecosim`. | ✅ |
| `version.py` | `__version__ = "0.6.0"` — source de vérité. | ✅ |

---

## `ecosim/entities/` — couche agents (animaux, plantes, gènes, maladies)

| Fichier | Rôle | Statut |
|---|---|---|
| `base.py` | Dataclass `Entity` commune à `Plant` et `Individual` (x, y, age, energy, alive, species). | ✅ |
| `animal.py` | Classe `Individual` : assemble les mixins Movement/Feeding/Reproduction + machine à états. | ✅ cœur |
| `plant.py` | Classe `Plant` : croissance, reproduction par dispersion, mort. | ✅ |
| `species.py` | Dataclass `Species` (type partagé immuable) + enum `SpeciesType` + `sample_params()`. | ✅ pivot |
| `genetics.py` | `Genome` 28 gènes, hérédité diploïde, mutation, `apply_to_params`, `genetic_distance`. | ✅ |
| `disease.py` | Modèle SEIR, `DiseaseSpec`, `DiseaseState`, `try_infect`. | ✅ |
| `movement.py` | `MovementMixin` — wander, flee, seek shelter, évitement eau. | ✅ |
| `feeding.py` | `FeedingMixin` — quête de nourriture par régime (herbi/carni/omni). | ✅ |
| `reproduction.py` | `ReproductionMixin` — gestation, naissance, transmission du génome. | ✅ |
| `activity.py` | Rythmes circadiens (`_is_resting`, `_is_pre_rest`) — cache module-level invalidé sur changement de `tod`. | ✅ |
| `death.py` | `mark_dead()` — finalise une entité et notifie les logs. | ✅ |
| `rng.py` | `_RNGWrapper` numpy ; point unique d'aléa pour le déterminisme. | ✅ critique |

---

## `ecosim/world/` — terrain et grille spatiale

| Fichier | Rôle | Statut |
|---|---|---|
| `grid.py` | `Grid` numpy (altitude, température, humidité, sols, eau). | ✅ |
| `cell.py` | Dataclass `Cell` retournée par `Grid.cell_at()`. | ✅ |
| `spatial_grid.py` | Hash spatial O(n) pour requêtes de voisinage (`query_radius`). | ✅ |
| `terrain.py` | Génération Perlin → biomes, `BIOME_PALETTE`, `altitude_to_rgb()`. | ✅ |

---

## `ecosim/engine/` — moteur de simulation

| Fichier | Rôle | Statut |
|---|---|---|
| `engine.py` | `SimulationEngine` — façade, agrège grid + species_registry + snapshotter + logs. | ✅ cœur |
| `engine_const.py` | `DAY_LENGTH = 1200`, `SIM_YEAR = 438 000`. | ✅ |
| `timescale.py` | `apply_time_acceleration()` — compresse les durées biologiques. | ✅ |
| `runner.py` | `EngineRunner` — boucle tick + `RunSummary`. | ✅ |
| `headless.py` | `run_headless()` — CLI synchrone, lit config JSON, écrit `.db`. | ✅ |
| `species_registry.py` | `SpeciesRegistry` — spawn/comptage/extinction. | ✅ |
| `snapshotter.py` | Génère dict de snapshot pour WebSocket / rapport. | ✅ |
| `snapshot_view.py` | Dataclass frozen `SimulationSnapshot` pour le replay. | ✅ |
| `maintenance.py` | `purge_runs(keep=N)` — supprime les vieux `.db`. | ✅ |
| `api.py` | Façade scriptée `Simulation` + `SimConfig` pour notebooks/recherche. | 🧪 jamais importé en runtime |
| `recording/schema.py` | Dataclasses `EntitySnapshot`, `WorldSnapshot`, `Event`. | ✅ |
| `recording/recorder.py` | SQLite : keyframes (gzip) + events + table `renders` (PNG pré-rendus). | ✅ |
| `recording/replay.py` | `ReplayReader` — reconstruit état à tick T, cache LRU. | ✅ |
| `recording/resume.py` | `load_engine_from_db()` — reprise d'un run depuis un `.db`. | ✅ |
| `recording/manifest.py` | `build_manifest()` — métadonnées d'expérience (seed, git hash, etc.). | ✅ |
| `recording/migrations.py` | Versioning SQLite v1→v3, appelé automatiquement. | ✅ infra |
| `utils/counting.py` | `count_by_species()` — dict `{name → count}`. | ✅ |

---

## `ecosim/web/` — interface localhost (active par défaut)

| Fichier | Rôle | Statut |
|---|---|---|
| `server.py` | App aiohttp, endpoints REST + WebSocket `/ws`. Sert le SPA + frames PNG. | ✅ |
| `routes_analyse.py` | Routes `/api/analyse/*` + `/api/replay/genetics` et `/heatmap`. | ✅ |
| `sim_manager.py` | Thread simulation, push WebSocket (progress/done/error/cancelled). | ✅ |
| `renderer.py` | Rendu numpy → PNG (`terrain_arr_from_grid`, `render_engine_frame`, `render_snapshot_frame`). | ✅ |
| `static/index.html` | SPA unique, 3 sections (setup / running / replay). | ✅ |
| `static/css/style.css` | Dark theme, variables CSS, glassmorphism. | ✅ |
| `static/js/app.js` | Vanilla JS : state machine + Canvas 2D renderer. | ✅ |
| `static/js/dashboard.js` | Graphes Chart.js (populations, génétique, épidémies). | ✅ |

---

## `ecosim/research/` — outils hors runtime (post-hoc + sweeps)

Tout ce qui se trouve sous `research/` est destiné aux notebooks et scripts
de recherche — jamais importé par le moteur, le web ou le mode headless.
Voir `ecosim/research/README.md` pour les exemples.

### `ecosim/research/analysis/`

| Fichier | Rôle | Statut |
|---|---|---|
| `stats.py` | `aggregate_replicates()`, `bootstrap_ci()` pour multi-réplicats. | 🧪 hors runtime |
| `genetics_metrics.py` | He, π, Fst, fréquences alléliques. | 🧪 hors runtime |
| `epidemiology.py` | `compute_R0()` empirique depuis un `.db`. | 🧪 hors runtime |
| `export.py` | CSV/Parquet (populations, life history, génétique, events, spatial). | 🧪 hors runtime |

### `ecosim/research/batch/`

| Fichier | Rôle | Statut |
|---|---|---|
| `sweep.py` | `ParameterSweep` — N simulations × M réplicats, agrégation CSV. | 🧪 hors runtime |

---

## `ecosim/monitoring/` — journalisation runtime

| Fichier | Rôle | Statut |
|---|---|---|
| `death_log.py` | `DeathLogger` — CSV mort/tick avec cause/énergie/position (écrit dans cwd/reports/). | ✅ |
| `logger.py` | `SimulationLogger` — fichier texte log tick/tick (cwd/logs/). | ✅ |
| `report.py` | `SimulationReport` — JSON final + stats par espèce (Shannon, cwd/reports/). | ✅ |

---

## `ecosim/config/` — constantes et validation

| Fichier | Rôle | Statut |
|---|---|---|
| `simulation_defaults.py` | Ré-exporte `DAY_LENGTH`, `SIM_YEAR`, `N_GENES` + tailles rendu web. | ✅ |
| `validator.py` | `validate_config()` — vérifie dict de config (grid_size, ticks, species, out_path). | ✅ |

---

## `ecosim/data/` — ressources livrées avec le paquet

| Chemin | Contenu |
|---|---|
| `data/species/*.json` | 12 espèces calibrées (4 plantes + 8 animaux). |
| `data/diseases/*.json` | 2 maladies SEIR (`myxomatosis`, `mange`). |

---

## `docs/` — documentation scientifique (racine du dépôt)

| Fichier | Rôle | Statut |
|---|---|---|
| `ODD_protocol.md` | Protocole ODD (Overview, Design concepts, Details) à la Grimm 2006/2020. | ✅ |
| `parameters.md` | Référence des paramètres modifiables. | ✅ |
| `INDEX.md` | Ce fichier — cartographie des modules. | ✅ |

---

## `tests/` — suite pytest (racine du dépôt, 188 tests, < 2 s)

| Fichier | Couverture |
|---|---|
| `conftest.py` | Ajoute racine du dépôt à `sys.path` pour `import ecosim`. |
| `helpers.py` | Fixtures partagées (grille, espèce mock). |
| `test_animal.py` | Comportements `Individual` (mouvement, alimentation, mort). |
| `test_plant.py` | Croissance, dispersion, mort des plantes. |
| `test_species.py` | Chargement JSON, `sample_params()`. |
| `test_species_sharing.py` | Invariant : 1 seul objet Species partagé après naissances. |
| `test_grid.py` | `Grid`, `Cell`, `nearest_non_water`. |
| `test_engine.py` | `SimulationEngine.tick()`, comptes d'espèces. |
| `test_disease.py` | Modèle SEIR, contamination. |
| `test_genetics.py` | Hérédité, mutation, `genetic_distance`. |
| `test_resume.py` | Reprise depuis `.db`. |
| `test_determinism.py` | Reproductibilité bit-à-bit avec une seed. |
| `test_death_log.py` | `DeathLogger`. |
| `test_timescale.py` | `apply_time_acceleration` (9 tests). |
| `test_maintenance.py` | `purge_runs` (5 tests). |
| `test_research_genetics_metrics.py` | He, π, Fst, Ne (12 tests). |
| `test_web_smoke.py` | `_build_app` + helpers analyse contre `.db` SQLite fixture. |

---

## Légende des statuts

- ✅ **vivant** — importé/exécuté par le runtime ou les tests.
- 🧪 **expérimental / hors runtime** — destiné aux notebooks ou scripts utilisateur, jamais importé par le moteur ni les tests. À documenter ou à supprimer si abandonné.
- ⚠️ **candidat nettoyage** — mort à confirmer.
