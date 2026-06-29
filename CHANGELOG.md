# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; ce projet suit
le [versionnement sémantique](https://semver.org/lang/fr/) à partir de la 0.4.

## [0.7.0] — 2026-06-29

Vectorisation hot path (étape 2), 2ᵉ notebook scientifique, suite du
découpage du serveur web, couverture `sim_manager`.

### Ajouté
- **`SpatialGrid` vectorisé** (`ecosim/world/spatial_grid.py`) — stocke
  désormais des triplets `(x, y, idx)` ; `query` et `query_radius`
  renvoient `np.ndarray[int32]` d'indices. `engine.tick` matérialise les
  indices → entités via les listes de vérité. Déterminisme préservé. 6
  tests d'invariant (`tests/test_spatial_grid.py`).
- **Notebook `02_drift_fst.ipynb`** — dérive génétique He(t) sur 5
  réplicats (bande mean ± σ) + Fst entre quadrants spatiaux d'une
  simulation, basé sur `ecosim.research.analysis.genetics_metrics`.
- **`ecosim/web/routes_runs.py`** — extrait de `server.py` :
  `/api/runs`, `/api/runs/{id}/tag`, `/api/runs/compare`,
  `/api/runs/{id}/export` + helpers `_enrich_run_meta`, `_compare_runs`,
  `_export_csv`.
- **Tests `web/sim_manager.py`** — 11 tests (clients WS, `_push` 1/N/0
  clients, cycle start/cancel/is_running, smoke E2E de simulation +
  annulation).

### Modifié
- **`web/server.py`** : 533 → 404 lignes (-24 %) après extraction de
  `routes_runs.py`. Reste un cycle de découpage (`routes_replay.py`)
  pour atteindre la cible <200 lignes.

## [0.6.0] — 2026-06-29

### Ajouté
- **SoA prep (`ecosim/engine/state_arrays.py`)** — première étape du plan de vectorisation
  du hot path. Maintient un miroir NumPy (x, y, energy, age, alive, species_id) des listes
  `engine.individuals` / `engine.plants`, mapping species_id stable. Aucune logique métier
  ne lit encore depuis la SoA, mais l'invariant « SoA == listes » est verrouillé par 6
  tests (`tests/test_state_arrays.py`).
- **Galerie de notebooks scientifiques (`notebooks/`)** — premier notebook
  `01_lotka_volterra.ipynb` reproduisant un cycle proie-prédateur (Herbe → Lapin → Renard)
  avec séries temporelles, portrait de phase et mesures d'autocorrélation. Convention :
  chaque notebook exporte sa configuration en `*.config.json` pour rendre le run
  reproductible à l'identique.
- **`CHANGELOG.md`** à la racine, suivant Keep-a-Changelog.

## [0.5.0] — 2026-06-19

Refonte structurelle, paquet pip propre, optimisations ciblées du hot path.

### Ajouté
- **Paquet `ecosim/` installable** (`pip install -e .`) avec entry-point `ecosim`
  (`ecosim --headless …`) et `python -m ecosim`. `pyproject.toml` à la racine avec
  `package-data` pour les JSON d'espèces et de maladies.
- **`--time-acceleration N`** : facteur d'échelle qui divise les durées biologiques
  (`*_ticks`, `*_age`, `*_cooldown_length`) sans toucher aux taux par tick. Permet de
  raccourcir les expériences. `ecosim/engine/timescale.py`.
- **Maintenance** : `--purge-runs --keep N` pour ne garder que les N derniers `.db`.
  `ecosim/engine/maintenance.py`.
- **Multi-sélection + infection groupée** dans l'UI Analyse (Maj/Ctrl+clic) ; endpoint
  `/api/replay/infect` accepte désormais `targets: [{species, x, y}]`.

### Modifié
- **`engine/` (renommage)** : `simulation/simulation/` → `ecosim/engine/`, élimine le
  double-nesting. `docs/INDEX.md` cartographie le dépôt.
- **`research/`** : `analysis/` et `batch/` regroupés sous `ecosim/research/` (signal
  clair « hors runtime »).
- **`gui/` (Tkinter) supprimé** : ~2 700 lignes mortes. Le web (`ecosim.web`) est
  l'interface unique.
- **`web/server.py`** : 1 008 → 646 lignes. Routes `/api/analyse/*` extraites dans
  `ecosim/web/routes_analyse.py`.
- **Génétique unifiée** : `blend_species()` supprimé. Toute variation phénotypique passe
  par le `Genome`. Invariant « 1 seul objet Species partagé » verrouillé par
  `tests/test_species_sharing.py`.
- **Performance hot path** (+18.6 % ticks/s, 86 → 102 sur 400 ticks 200²) :
  cache module-level pour `_is_resting`/`_is_pre_rest`, type-checks Species précalculés
  (`_is_flying`, `_is_predator`, etc.), centroïde de troupeau en une seule passe sur
  `nearby_inds`, suppression de `hasattr(grid, "nutrients")` dans `Plant.tick`.
- **Hygiène** : ~11 `print()` applicatifs migrés vers `logging`, `except Exception` :
  32 → 3 (exceptions spécifiques `sqlite3.Error`, `OSError`, …).
- **CI** : ruff bloquant (156 → 0 erreurs), pytest sur Python 3.10/3.11/3.12.

### Corrigé
- `engine.reset()` dupliqué supprimé.
- `disease.py` : souche pathogène portée par l'hôte via `DiseaseState.strain` (plus de
  mutation du `DISEASE_REGISTRY` global pendant l'itération).
- `animal.py` : `_uid_counter` en `ClassVar[int]` (plus d'attribut fantôme dataclass).

### Documentation
- `README.md` à la racine, `docs/INDEX.md` (cartographie), `docs/internal/` (audits
  historiques dont `2026-06-12_audit_initial.md`).

## [0.4.0] — 2026-05-28

Interface ANALYSE, déterminisme, anti-extinction des prédateurs.

### Ajouté
- **Interface ANALYSE** dans l'UI web : onglets GRAPHES, GÉNÉALOGIE, JOURS, STATS
  alimentés par 4 endpoints (`/api/analyse/timeseries`, `/genealogy`, `/day_info`,
  `/stats`).
- **Recording étendu** : table `genealogy` (parent_id, birth events, compteurs),
  échantillonnage ×4 (~200 keyframes / run).
- **Replay enrichi** : filtre jour/nuit sur le terrain + HUD heure/icône, frames PNG
  pré-rendues dans le `.db` pendant la simulation (plus de re-rendu serveur), panneau
  latéral enrichi.
- **Contamination trophique** : ingestion de proies infectées peut transmettre la
  maladie (`food_disease_chance`).

### Modifié
- **Centroïde de troupeau local** (rayon 3×perception) au lieu du centroïde global —
  corrige la convergence des entités vers le centre de la carte.
- **Robustesse des prédateurs** : équilibrage long terme des paramètres des espèces
  carnivores.
- **API recording** : `runs` enrichi (`max_pops`, `species`, `seed`…), routes
  `runs_tag`, `runs_compare`, `export` (CSV).

### Corrigé
- RNG, thread-safety et logique biologique (paths normalisés, races sur le manager).
- Replay : cache-bust URL frames par session, label tick corrigé, vitesse libre.
- Recorder : nettoyage du `.db` existant avant chaque nouvelle simulation.

## [0.3.0] — 2026-04-19

Interface web localhost (aiohttp + Canvas 2D) — remplace le live-viewer Tkinter.

### Ajouté
- **Serveur web `ecosim.web`** (aiohttp + WebSocket sur `localhost:8765`) : flow
  SETUP → RUNNING → REPLAY dans le navigateur.
- **Rendu côté serveur** : frames PNG rendues une fois pendant la simulation et
  stockées dans le `.db` (replay = lecture BD directe).
- **Preset terrain** sauvegardé dans le recorder et restauré au replay.

### Modifié
- `main.py` : `python main.py` ouvre l'interface web par défaut. `--tk` conserve l'UI
  Tkinter, `--headless …` inchangé.

## [0.2.0] — 2026-04-18

Première réorganisation : architecture en façade, headless/recorder/replay.

### Ajouté
- **Mode headless** (`python main.py --headless --ticks N --seed S [--out run.db]`)
  sans dépendance Tkinter.
- **Recording / replay** : `Recorder` SQLite (keyframes + events), `ReplayReader`
  (dichotomie + LRU cache), point d'entrée `python -m simulation.replay run.db`.
- **Génétique** : `Genome` à 8 gènes, transmission parent → enfant via
  `Genome.from_parents`, application au phénotype par `apply_to_params`.
- **Maladies** : modèle SEIR (`DiseaseSpec` / `DiseaseState`), maladies JSON dans
  `species_data/diseases/`.
- **Reprise de simulation** : `load_engine_from_db` + `Recorder(append=True)`.

### Modifié
- **Architecture en façade** : `SimulationEngine` délègue à `SpeciesRegistry` (spawn,
  comptage, extinction) et `Snapshotter` (snapshots WebSocket / rapport).
- **Déterminisme global** : `entities/rng.py` + `seed: int | None` sur `SimulationEngine`.
- **Terrain vectorisé** : `world/terrain.py` avec Perlin numpy.
- **Variabilité gaussienne inter-simulation** : chaque paramètre d'espèce a une moyenne
  µ et un écart-type σ (clés `*_std` dans les JSON), tiré au démarrage par
  `sample_params`.

[0.7.0]: https://example.invalid/ecosim/compare/v0.6.0...v0.7.0
[0.6.0]: https://example.invalid/ecosim/compare/v0.5.0...v0.6.0
[0.5.0]: https://example.invalid/ecosim/compare/v0.4.0...v0.5.0
[0.4.0]: https://example.invalid/ecosim/compare/v0.3.0...v0.4.0
[0.3.0]: https://example.invalid/ecosim/compare/v0.2.0...v0.3.0
[0.2.0]: https://example.invalid/ecosim/releases/tag/v0.2.0
