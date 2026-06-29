# EcoSim

EcoSim est un simulateur d'écosystème multi-espèces individu-centré (agent-based) en Python. Chaque animal et chaque plante est un agent autonome qui se déplace, mange, se reproduit, tombe malade et meurt sur une grille de terrain procédural. Le projet vise un usage scientifique : étude des cycles proie-prédateur, de l'évolution génétique, de la propagation d'épidémies (SEIR) et de la diversité génétique.

## Caractéristiques clés

- **12 espèces calibrées** : 8 animales (herbivores, carnivores, omnivores) et 4 végétales.
- **Génétique mendélienne** : 28 gènes avec allèles dominants/récessifs, mutation, hérédité diploïde.
- **Maladies SEIR** : modèle compartimental Susceptible-Exposé-Infectieux-Rétabli avec souches par hôte et contamination trophique.
- **Mortalité de Gompertz** : sénescence dépendante de l'âge.
- **Dimorphisme sexuel**, gestation, rythmes circadiens, saisonnalité.
- **Terrain procédural** généré par bruit de Perlin (altitude, humidité, biomes).
- **Enregistrement SQLite** avec replay et resume d'une simulation.
- **Sweep batch** pour balayer des plages de paramètres.
- **Métriques scientifiques** : Fst, hétérozygotie attendue (He), diversité nucléotidique (π), R₀.
- **188 tests pytest**.

## Installation

```bash
git clone <url-du-depot>
cd <repo>
pip install -e .
```

EcoSim est désormais un paquet Python propre — `pip install -e .` expose un module importable `ecosim` et installe l'entry-point CLI `ecosim`. Pour le développement, ajoute `[dev]` :

```bash
pip install -e ".[dev]"   # installe aussi pytest et ruff
```

Prérequis : Python 3.10 ou plus récent.

## Comment lancer

Toutes les commandes ci-dessous fonctionnent depuis n'importe quel répertoire après installation. Les répertoires `runs/`, `logs/` et `reports/` sont créés dans le dossier courant.

- **Interface web (par défaut)** :

  ```bash
  ecosim
  ```

  Démarre un serveur local sur `http://localhost:9000` (port modifiable via `--port 8765`).

- **Mode headless / CLI** :

  ```bash
  ecosim --headless --seed 42 --ticks 10000
  ```

  Flags : `--ticks N`, `--seed S`, `--config <dossier>`, `--out <chemin.sqlite>`, `--progress`, `--time-acceleration N`.

- **Purger d'anciens runs** :

  ```bash
  ecosim --purge-runs --keep 5
  ```

- **Alternative sans entry-point** : `python -m ecosim ...` fonctionne aussi.

- **Tests** :

  ```bash
  python -m pytest
  ```

## Structure du dépôt

```
<root>/
├── ecosim/                    paquet importable
│   ├── main.py                CLI dispatcher (ecosim:main)
│   ├── entities/              agents : animal, plant, genetics, disease, …
│   ├── world/                 grid, spatial_grid, terrain (Perlin)
│   ├── engine/                moteur : engine, runner, headless, recording (SQLite)
│   ├── research/              outils hors runtime (post-hoc + sweeps batch)
│   │   ├── analysis/            stats, génétique (Fst/He/π), épidémiologie (R₀)
│   │   └── batch/               sweep de paramètres
│   ├── monitoring/            logger, death_log, report
│   ├── web/                   serveur aiohttp + renderer + SPA JS
│   ├── config/                defaults + validator
│   └── data/                  ressources livrées avec le paquet
│       ├── species/             12 fichiers JSON (espèces calibrées)
│       └── diseases/            JSON SEIR (myxomatosis, mange)
├── tests/                     188 tests pytest
├── docs/                      ODD_protocol.md, parameters.md, INDEX.md
├── pyproject.toml
├── README.md
└── LICENSE
```

> 📄 [`docs/INDEX.md`](docs/INDEX.md) — cartographie exhaustive de chaque fichier et de son rôle.

## Documentation scientifique

- Protocole ODD (Overview, Design concepts, Details) à la Grimm 2006/2020 : [`docs/ODD_protocol.md`](docs/ODD_protocol.md).
- Référence des paramètres : [`docs/parameters.md`](docs/parameters.md).

## Version

0.6.0 — voir [`CHANGELOG.md`](CHANGELOG.md) pour l'historique complet.

## Licence

Voir le fichier [`LICENSE`](LICENSE) à la racine du dépôt (CC0 1.0 Universal).
