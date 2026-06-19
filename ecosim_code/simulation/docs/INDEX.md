# Index du dépôt EcoSim

Cartographie exhaustive des fichiers suivis par git, organisée par module.
Pour chaque fichier : rôle en une ligne + statut (✅ vivant / 🧪 expérimental / ⚠️ candidat nettoyage).

> Mise à jour : `chore/restructure-cleanup` — après renommage `simulation/simulation/ → simulation/engine/`.

---

## Racine du dépôt

| Fichier | Rôle | Statut |
|---|---|---|
| `README.md` | Pitch, install, lancement, structure, lien ODD. | ✅ |
| `LICENSE` | CC0 1.0 Universal. | ✅ |
| `pyproject.toml` | Métadonnées paquet, dépendances bornées, configs `ruff` et `pytest`. | ✅ |
| `.gitignore` | Ignore `__pycache__`, `logs/`, `reports/`, `runs/`, audits internes. | ✅ |
| `.github/workflows/ci.yml` | CI GitHub (pytest + ruff sur 3.10/3.11/3.12). | ✅ |
| `lancer_simulation.bat` | Raccourci Windows : lance `python main.py`. | ✅ |

> Le fichier `COMPTE_RENDU_ANALYSE.md` à la racine est un audit interne **gitignored**, pas dans cet index.

---

## `ecosim_code/simulation/` — racine de l'application

| Fichier | Rôle | Statut |
|---|---|---|
| `main.py` | Point d'entrée CLI : route vers `--headless`, `--purge-runs`, ou serveur web (par défaut). | ✅ |
| `version.py` | `__version__ = "0.5.0"` — lu par `engine/recording/manifest.py` et `recorder.py`. | ✅ |

---

## `entities/` — couche agents (animaux, plantes, gènes, maladies)

| Fichier | Rôle | Statut |
|---|---|---|
| `base.py` | Dataclass `Entity` commune à `Plant` et `Individual` (x, y, age, energy, alive, species). | ✅ |
| `animal.py` | Classe `Individual` : assemble les mixins Movement/Feeding/Reproduction + machine à états. | ✅ cœur |
| `plant.py` | Classe `Plant` : croissance, reproduction par dispersion, mort. | ✅ |
| `species.py` | Dataclass `Species` + enum `SpeciesType` + `sample_params()` (variabilité gaussienne). | ✅ pivot |
| `genetics.py` | `Genome` 28 gènes, hérédité diploïde, mutation, `apply_to_params`, `genetic_distance`. | ✅ |
| `disease.py` | Modèle SEIR, `DiseaseSpec`, `DiseaseState`, `try_infect`. | ✅ |
| `movement.py` | `MovementMixin` — wander, flee, seek shelter, évitement eau. | ✅ |
| `feeding.py` | `FeedingMixin` — quête de nourriture par régime (herbi/carni/omni). | ✅ |
| `reproduction.py` | `ReproductionMixin` — gestation, naissance, transmission du génome. | ✅ |
| `activity.py` | Rythmes circadiens (`_is_resting`, `_is_pre_rest`). | ✅ |
| `death.py` | `mark_dead()` — finalise une entité et notifie les logs. | ✅ |
| `rng.py` | `_RNGWrapper` numpy ; point unique d'aléa pour le déterminisme. | ✅ critique |

---

## `world/` — terrain et grille spatiale

| Fichier | Rôle | Statut |
|---|---|---|
| `grid.py` | `Grid` numpy (altitude, température, humidité, sols, eau). Méthodes `cell_at()`, `nearest_non_water()`. | ✅ |
| `cell.py` | Dataclass `Cell` retournée par `Grid.cell_at()` et utilisée par `test_grid.py`. | ✅ |
| `spatial_grid.py` | Hash spatial O(n) pour requêtes de voisinage (`query_radius`). | ✅ |
| `terrain.py` | Génération Perlin → biomes, `BIOME_PALETTE`, `altitude_to_rgb()`. | ✅ |

---

## `engine/` — moteur de simulation (ex `simulation/simulation/`)

| Fichier | Rôle | Statut |
|---|---|---|
| `engine.py` | `SimulationEngine` — façade, agrège grid + species_registry + snapshotter + logs. | ✅ cœur |
| `engine_const.py` | `DAY_LENGTH = 1200`, `SIM_YEAR = 438 000`. | ✅ |
| `runner.py` | `EngineRunner` — boucle tick + `RunSummary` (réutilisé par headless/web/gui). | ✅ |
| `headless.py` | `run_headless()` — CLI synchrone sans GUI, lit config JSON, écrit `.db`. | ✅ |
| `species_registry.py` | `SpeciesRegistry` — spawn/comptage/extinction, pré-calcul cellules valides. | ✅ |
| `snapshotter.py` | Génère dict de snapshot pour WebSocket / rapport. | ✅ |
| `snapshot_view.py` | Dataclass frozen `SimulationSnapshot` pour le replay. | ✅ |
| `api.py` | Façade scriptée `Simulation` + `SimConfig` pour notebooks/recherche. | 🧪 jamais importé en runtime |
| `recording/schema.py` | Dataclasses `EntitySnapshot`, `WorldSnapshot`, `Event`. | ✅ |
| `recording/recorder.py` | SQLite : keyframes (gzip) + events + table `renders` (PNG pré-rendus). | ✅ |
| `recording/replay.py` | `ReplayReader` — reconstruit état à tick T, cache LRU. | ✅ |
| `recording/resume.py` | `load_engine_from_db()` — reprise d'un run depuis un `.db`. | ✅ |
| `recording/manifest.py` | `build_manifest()` — métadonnées d'expérience (seed, git hash, etc.). | ✅ |
| `recording/migrations.py` | Versioning SQLite v1→v3, appelé automatiquement. | ✅ infra |
| `utils/counting.py` | `count_by_species()` — dict `{name → count}`. | ✅ |
| `maintenance.py` | `purge_runs(keep=N)` — supprime les vieux `.db`. | ✅ |

---

## `web/` — interface localhost (active par défaut)

| Fichier | Rôle | Statut |
|---|---|---|
| `server.py` | App aiohttp, endpoints REST + WebSocket `/ws`. Sert le SPA + frames PNG. | ✅ |
| `sim_manager.py` | Thread simulation, push WebSocket (progress/done/error/cancelled). | ✅ |
| `renderer.py` | Rendu numpy → PNG (`terrain_arr_from_grid`, `render_engine_frame`, `render_snapshot_frame`). | ✅ |
| `static/index.html` | SPA unique, 3 sections (setup / running / replay). | ✅ |
| `static/css/style.css` | Dark theme, variables CSS, glassmorphism. | ✅ |
| `static/js/app.js` | Vanilla JS : state machine + Canvas 2D renderer. | ✅ |
| `static/js/dashboard.js` | Graphes Chart.js (populations, génétique, épidémies). | ✅ |

---

## `research/` — outils hors runtime (post-hoc + sweeps)

Tout ce qui se trouve sous `research/` est destiné aux notebooks et scripts
de recherche — jamais importé par le moteur, le web ou le mode headless.
Voir `research/README.md` pour les exemples.

### `research/analysis/`

| Fichier | Rôle | Statut |
|---|---|---|
| `stats.py` | `aggregate_replicates()`, `bootstrap_ci()` pour multi-réplicats. | 🧪 hors runtime |
| `genetics_metrics.py` | He, π, Fst, fréquences alléliques. | 🧪 hors runtime |
| `epidemiology.py` | `compute_R0()` empirique depuis un `.db`. | 🧪 hors runtime |
| `export.py` | CSV/Parquet (populations, life history, génétique, events, spatial). | 🧪 hors runtime |

### `research/batch/`

| Fichier | Rôle | Statut |
|---|---|---|
| `sweep.py` | `ParameterSweep` — N simulations × M réplicats, agrégation CSV. | 🧪 hors runtime |

---

## `monitoring/` — journalisation runtime

| Fichier | Rôle | Statut |
|---|---|---|
| `death_log.py` | `DeathLogger` — CSV mort/tick avec cause/énergie/position. | ✅ |
| `logger.py` | `SimulationLogger` — fichier texte log tick/tick. | ✅ |
| `report.py` | `SimulationReport` — JSON final + stats par espèce (Shannon). | ✅ |

---

## `config/` — constantes et validation

| Fichier | Rôle | Statut |
|---|---|---|
| `simulation_defaults.py` | Source unique : ré-exporte `DAY_LENGTH`, `SIM_YEAR`, `N_GENES` + tailles fenêtre/rendu. | ✅ |
| `validator.py` | `validate_config()` — vérifie dict de config (grid_size, ticks, species, out_path). | ✅ |

---

## `docs/` — documentation scientifique

| Fichier | Rôle | Statut |
|---|---|---|
| `ODD_protocol.md` | Protocole ODD (Overview, Design concepts, Details) à la Grimm 2006/2020. | ✅ |
| `parameters.md` | Référence des paramètres modifiables. | ✅ |
| `INDEX.md` | Ce fichier — cartographie des modules. | ✅ |

---

## `tests/` — suite pytest (153 tests, < 2 s)

| Fichier | Couverture |
|---|---|
| `conftest.py` | Ajoute `ecosim_code/simulation/` à `sys.path`. |
| `helpers.py` | Fixtures partagées (grille, engine headless). |
| `test_animal.py` | Comportements `Individual` (mouvement, alimentation, mort). |
| `test_plant.py` | Croissance, dispersion, mort des plantes. |
| `test_species.py` | Chargement JSON, `sample_params()`. |
| `test_grid.py` | `Grid`, `Cell`, `nearest_non_water`. |
| `test_engine.py` | `SimulationEngine.tick()`, comptes d'espèces. |
| `test_disease.py` | Modèle SEIR, contamination. |
| `test_genetics.py` | Hérédité, mutation, `genetic_distance`. |
| `test_resume.py` | Reprise depuis `.db`. |
| `test_determinism.py` | Reproductibilité bit-à-bit avec une seed. |
| `test_death_log.py` | `DeathLogger`. |

---

## Ressources

| Chemin | Contenu |
|---|---|
| `species/*.json` | 12 espèces calibrées (4 plantes + 8 animaux). |
| `species_data/diseases/*.json` | 2 maladies SEIR (`myxomatosis`, `mange`). |

---

## Légende des statuts

- ✅ **vivant** — importé/exécuté par le runtime ou les tests.
- 🧪 **expérimental / hors runtime** — destiné aux notebooks ou scripts utilisateur, jamais importé par le moteur ni les tests. À documenter ou à supprimer si abandonné.
- ⚠️ **candidat nettoyage** — mort à confirmer.
