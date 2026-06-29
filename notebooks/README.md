# Notebooks d'expériences EcoSim

Galerie d'expériences reproductibles bâties sur `ecosim.engine.api`. Chaque notebook fixe son
seed, sa configuration de grille, et produit une figure illustrant un phénomène biologique
classique.

## Pré-requis

```bash
pip install -e ".[dev]"
pip install jupyter matplotlib pandas
```

## Lancement

```bash
jupyter lab notebooks/
```

## Catalogue

| Notebook                       | Phénomène illustré                                |
|--------------------------------|---------------------------------------------------|
| `01_lotka_volterra.ipynb`      | Cycle proie–prédateur (Herbe → Lapin → Renard)    |

## Convention

Chaque notebook écrit sa configuration (seed + paramètres) dans un fichier
`<nom>.config.json` à côté de lui pour rendre le run reproductible à l'identique sur la
même version d'EcoSim.
