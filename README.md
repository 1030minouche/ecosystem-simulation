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
- **Métriques scientifiques** : Fst, hétérozygotie attendue (He), diversité nucléotidique (pi), R0.
- **153 tests pytest**.

## Installation

```bash
git clone <url-du-depot>
cd <repo>
pip install -e .
```

Cette commande installe les dépendances bornées déclarées dans `pyproject.toml`.

> ⚠️ La base de code vit sous `ecosim_code/simulation/` et utilise des imports relatifs à ce dossier (`from world.grid import …`). Elle n'est pas encore exposée comme un paquet importable nommé `ecosim` ; les commandes de lancement ci-dessous doivent donc être exécutées depuis ce répertoire. Le `pyproject.toml` à la racine sert à figer les dépendances, fournir la configuration `pytest` et `ruff`, et préparer une future ré-architecture en paquet propre.

Prérequis : Python 3.10 ou plus récent. Tkinter est inclus dans la bibliothèque standard.

## Comment lancer

Toutes les commandes ci-dessous sont à exécuter depuis `ecosim_code/simulation/`.

- **Interface web (recommandé)** :

  ```bash
  python main.py
  ```

  Démarre un serveur local sur `http://localhost:9000` (port modifiable via `--port 8765`).

- **Interface Tkinter (héritée)** :

  ```bash
  python main.py --tk
  ```

- **Mode headless / CLI** :

  ```bash
  python main.py --headless --seed 42 --ticks 10000
  ```

  Flags disponibles : `--ticks N`, `--seed S`, `--config <dossier>`, `--out <chemin.sqlite>`, `--progress`.

- **Tests** :

  ```bash
  cd ecosim_code/simulation
  python -m pytest
  ```

## Structure du dépôt

```
ecosim_code/simulation/
├── main.py        point d'entrée CLI
├── entities/      agents : animal, plant, genetics, disease, …
├── world/         grid, spatial_grid, terrain (Perlin)
├── engine/        moteur : engine, runner, headless, recording (SQLite)
├── analysis/      stats, génétique (Fst/He/π), épidémiologie (R₀) — post-hoc
├── batch/         sweep de paramètres
├── monitoring/    logger, death_log, report
├── gui/           Tkinter (setup → run → replay) — hérité
├── web/           serveur aiohttp + renderer + SPA JS
├── config/        defaults + validator
├── docs/          ODD_protocol.md, parameters.md, INDEX.md
└── tests/         153 tests pytest
```

> 📄 [`docs/INDEX.md`](ecosim_code/simulation/docs/INDEX.md) — cartographie exhaustive de chaque fichier et de son rôle.

## Documentation scientifique

- Protocole ODD (Overview, Design concepts, Details) à la Grimm 2006/2020 : [`ecosim_code/simulation/docs/ODD_protocol.md`](ecosim_code/simulation/docs/ODD_protocol.md).
- Référence des paramètres : [`ecosim_code/simulation/docs/parameters.md`](ecosim_code/simulation/docs/parameters.md).

## Version

0.5.0

## Licence

Voir le fichier [`LICENSE`](LICENSE) à la racine du dépôt (CC0 1.0 Universal).
