# Plan d'implémentation EcoSim — Prompt Claude Code

> Copier-coller ce fichier entier dans une session Claude Code depuis la racine du projet
> (`ecosim_code/simulation/`). Chaque phase est autonome et testable séparément.

---

## Contexte du projet

EcoSim est un simulateur d'écosystème biologique en Python (v0.4.0).
Architecture : moteur tick-based, entités individuelles avec mixins, enregistrement SQLite,
interface web aiohttp + interface Tkinter optionnelle. Tous les tests actuels (121/121) passent.

**Répertoire de travail présumé** : `ecosim_code/simulation/`

---

## PHASE 0 — Corrections de bugs existants

### 0-A : Non-déterminisme — unifier les RNG

**Problème** : `entities/rng.py` définit un `_RNGWrapper` avec numpy, mais chaque module entité
utilise `import random` (stdlib) directement, rendant le seed sans effet.

**Fichiers à modifier** : `entities/animal.py`, `entities/reproduction.py`,
`entities/feeding.py`, `entities/movement.py`, `entities/plant.py`, `entities/species.py`,
`simulation/species_registry.py`

**Actions** :

1. Dans `entities/rng.py`, s'assurer que `_RNGWrapper` expose les méthodes manquantes :
   ```python
   def uniform(self, a=0.0, b=1.0): return float(self.generator.uniform(a, b))
   def gauss(self, mu, sigma):       return float(self.generator.normal(mu, sigma))
   def randint(self, a, b):          return int(self.generator.integers(a, b+1))
   def choice(self, seq):
       idx = int(self.generator.integers(0, len(seq)))
       return seq[idx]
   def shuffle(self, lst):
       arr = self.generator.permuted(lst)
       lst[:] = list(arr)
   def random(self):                 return float(self.generator.random())
   ```

2. Dans chaque fichier entité, remplacer `import random` par `from entities.rng import rng`
   et adapter les appels :
   - `random.random()` → `rng.random()`
   - `random.uniform(a,b)` → `rng.uniform(a,b)`
   - `random.gauss(mu,s)` → `rng.gauss(mu,s)`
   - `random.randint(a,b)` → `rng.randint(a,b)`
   - `random.choice(seq)` → `rng.choice(seq)`
   - `random.shuffle(lst)` → `rng.shuffle(lst)`

3. Dans `simulation/species_registry.py` ligne ~58, remplacer :
   ```python
   rng = np.random.default_rng()
   ```
   par :
   ```python
   from entities.rng import rng as _ent_rng
   _spawn_positions = _ent_rng.generator.integers(...)
   ```
   (utiliser `_ent_rng.generator` directement pour les opérations numpy)

4. Vérifier que `test_determinism.py` passe après ces changements.

---

### 0-B : Argument manquant `time_of_day` dans `_seek_food`

**Fichier** : `entities/animal.py`, méthode `tick()`.

Remplacer :
```python
self._seek_food(grid, all_plants, all_individuals)
```
par :
```python
self._seek_food(grid, all_plants, all_individuals, time_of_day)
```

---

### 0-C : Thread-safety de `get_state_snapshot()`

**Fichier** : `simulation/snapshotter.py`

Envelopper la lecture dans `core.lock` :
```python
def get_state_snapshot(self) -> dict:
    with self.core.lock:
        plants = list(self.core.plants)
        individuals = list(self.core.individuals)
    # ... reste du code avec les listes locales
```

---

### 0-D : Compteur espèces sans garde min(0)

**Fichier** : `simulation/engine.py`, section décrémentation `_species_counts`.

Remplacer chaque décrémentation non-gardée :
```python
self._species_counts[name] -= 1
```
par :
```python
self._species_counts[name] = max(0, self._species_counts.get(name, 0) - 1)
```

---

### 0-E : Cooldown partenaire asymétrique lors de la gestation

**Fichier** : `entities/reproduction.py`, méthode `_try_reproduce()`.

Dans le bloc gestation, remplacer :
```python
nearest_partner.reproduction_cooldown = self.species.reproduction_cooldown_length
```
par :
```python
nearest_partner.reproduction_cooldown = self.species.gestation_ticks
```

---

### 0-F : Chemins relatifs dans monitoring

**Fichiers** : `monitoring/report.py`, `monitoring/logger.py`

Remplacer `os.makedirs("reports", ...)` et `os.makedirs("logs", ...)` par des chemins
absolus relatifs au fichier source :
```python
from pathlib import Path
_BASE = Path(__file__).parent.parent
_REPORTS_DIR = _BASE / "reports"
_LOGS_DIR    = _BASE / "logs"
```

---

### 0-G : `RunSummary.ticks_done` toujours égal à `max_ticks`

**Fichier** : `simulation/runner.py`

Dans `EngineRunner.run()`, tracker le tick réel effectué :
```python
actual_ticks = engine.tick_count - start_tick
summary = RunSummary(ticks_done=actual_ticks, ...)
```

---

### 0-H : Commentaire incohérent "1 tick sur 10"

**Fichier** : `simulation/engine.py`, ligne ~153.
Corriger le commentaire en `# ── Plantes (1 tick sur 3)`.

---

### 0-I : Représentation double de la grille (Grid)

**Fichier** : `world/grid.py`

Le Grid maintient à la fois des tableaux numpy (`altitude`, `temperature`, `humidity`,
`soil_type`) ET des objets `Cell`. L'éditeur de terrain utilise les `Cell`, le moteur
utilise les numpy arrays — risque de divergence.

**Action** : Faire en sorte que les `Cell` soient construites à la demande depuis les arrays
numpy (lecture seule pour le terrain editor), ou supprimer entièrement les Cell si l'éditeur
de terrain peut être refactored pour utiliser les arrays directement.

Option recommandée — ajouter une méthode `cell_at(x, y)` qui construit un Cell temporaire :
```python
def cell_at(self, x: int, y: int) -> Cell:
    return Cell(
        altitude=float(self.altitude[y, x]),
        temperature=float(self.temperature[y, x]),
        humidity=float(self.humidity[y, x]),
        soil_type=int(self.soil_type[y, x]),
    )
```
Et supprimer l'initialisation du tableau `self.cells`.

---

## PHASE 1 — Système de génétique

### Architecture

Chaque individu portera un **génome** : un vecteur de `N_GENES` flottants dans `[-1, 1]`,
hérités des parents avec mutation. Ces gènes modifient les paramètres phénotypiques de l'espèce
(valeur de base × facteur génétique). Le génome est stocké dans l'Individual ET dans le SQLite.

### 1-A : Constantes et helpers génétiques

Créer `entities/genetics.py` :

```python
"""
Système de génétique simple pour EcoSim.
Un génome = vecteur de N_GENES flottants dans [-1.0, 1.0].
Chaque gène module un paramètre phénotypique de l'espèce.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from entities.rng import rng

if TYPE_CHECKING:
    from entities.species import Species

N_GENES = 8  # nombre de loci génétiques

# Mapping indice → nom du paramètre modulé (facteur multiplicatif : base × (1 + gene * 0.3))
GENE_TRAITS = [
    "max_speed",          # 0 : vitesse max
    "max_energy",         # 1 : énergie max
    "energy_per_food",    # 2 : efficacité digestive
    "reproduction_rate",  # 3 : fécondité
    "perception_radius",  # 4 : acuité sensorielle
    "aggression",         # 5 : agressivité
    "disease_resistance", # 6 : résistance aux maladies (nouveau)
    "longevity",          # 7 : longévité (max_age)
]

GENE_INFLUENCE = 0.30  # ±30 % d'influence max d'un gène sur son trait


@dataclass
class Genome:
    genes: list[float] = field(default_factory=lambda: [0.0] * N_GENES)

    @classmethod
    def random(cls) -> "Genome":
        return cls(genes=[rng.uniform(-1.0, 1.0) for _ in range(N_GENES)])

    @classmethod
    def from_parents(cls, parent_a: "Genome", parent_b: "Genome",
                     mutation_rate: float) -> "Genome":
        """Recombinaison mendélienne uniforme + mutation gaussienne."""
        child_genes = []
        for a, b in zip(parent_a.genes, parent_b.genes):
            # Recombinaison : chaque gène vient d'un parent au hasard
            gene = a if rng.random() < 0.5 else b
            # Mutation
            if rng.random() < mutation_rate:
                gene += rng.gauss(0.0, 0.15)
                gene = max(-1.0, min(1.0, gene))
            child_genes.append(gene)
        return cls(genes=child_genes)

    def apply_to_params(self, base_params: dict) -> dict:
        """Retourne une copie des params avec les modifications génétiques."""
        params = dict(base_params)
        for i, trait in enumerate(GENE_TRAITS):
            if trait in params:
                factor = 1.0 + self.genes[i] * GENE_INFLUENCE
                params[trait] = params[trait] * factor
        return params

    def genetic_distance(self, other: "Genome") -> float:
        """Distance euclidienne normalisée entre deux génomes (0=identique, 1=max)."""
        diffs = [(a - b) ** 2 for a, b in zip(self.genes, other.genes)]
        return (sum(diffs) / N_GENES) ** 0.5 / (2 ** 0.5)

    def to_list(self) -> list[float]:
        return list(self.genes)

    @classmethod
    def from_list(cls, lst: list[float]) -> "Genome":
        return cls(genes=list(lst))

    def to_json(self) -> str:
        return json.dumps(self.genes)

    @classmethod
    def from_json(cls, s: str) -> "Genome":
        return cls(genes=json.loads(s))
```

### 1-B : Intégration dans Individual

**Fichier** : `entities/animal.py`

1. Ajouter l'import : `from entities.genetics import Genome, N_GENES`
2. Ajouter les champs à `Individual.__init__()` :
   ```python
   self.genome: Genome = Genome.random()
   self.sex: str = "M" if rng.random() < 0.5 else "F"
   # Paramètres effectifs (base × gènes)
   self._effective_params: dict = {}
   self._refresh_effective_params()
   ```
3. Ajouter la méthode :
   ```python
   def _refresh_effective_params(self) -> None:
       base = {
           "max_speed":         self.species.max_speed,
           "max_energy":        self.species.max_energy,
           "energy_per_food":   self.species.energy_per_food,
           "reproduction_rate": self.species.reproduction_rate,
           "perception_radius": self.species.perception_radius,
           "aggression":        getattr(self.species, "aggression", 0.5),
           "disease_resistance":getattr(self.species, "disease_resistance", 0.5),
           "longevity":         getattr(self.species, "max_age", 5000),
       }
       self._effective_params = self.genome.apply_to_params(base)
   ```
4. Partout où `self.species.max_speed`, `self.species.perception_radius` etc. sont utilisés
   dans les mixins, les remplacer par `self._effective_params.get("max_speed", self.species.max_speed)`.

### 1-C : Transmission du génome à la reproduction

**Fichier** : `entities/reproduction.py`, méthode `_try_reproduce()` et `_deliver()`

Dans `_try_reproduce()` ou `_deliver()`, lors de la création d'un offspring :
```python
from entities.genetics import Genome
# ...
offspring.genome = Genome.from_parents(
    self.genome, partner.genome, self.species.mutation_rate
)
offspring.sex = "M" if rng.random() < 0.5 else "F"
offspring._refresh_effective_params()
offspring.parent_genome_distance = self.genome.genetic_distance(partner.genome)
```

### 1-D : Stockage du génome dans SQLite

**Fichier** : `simulation/recording/schema.py`

Ajouter `genome_json: str = ""` et `sex: str = "?"` à `EntitySnapshot` :
```python
@dataclass(frozen=True)
class EntitySnapshot:
    id: int
    species: str
    x: float
    y: float
    energy: float
    age: int
    alive: bool
    state: str
    sex: str = "?"
    genome_json: str = ""  # JSON list of N_GENES floats, "" si plante
```

Mettre à jour `WorldSnapshot.to_blob()` / `from_blob()` en conséquence (rétrocompatibilité :
utiliser `.get("sex", "?")` et `.get("genome_json", "")`).

**Fichier** : `simulation/recording/recorder.py`, `_write_keyframe()`

Passer `sex` et `genome_json` dans chaque `EntitySnapshot` pour les individus.

### 1-E : Affichage dans le viewer

**Fichier** : `gui/frames/replay_frame.py`, panneau inspecteur d'entité

Dans la section qui affiche l'énergie / l'âge, ajouter :
- Sexe (♂ / ♀)
- Mini-barres pour les 8 gènes (couleur verte = positif, rouge = négatif)
- Distance génétique avec l'individu précédemment sélectionné (si applicable)

**Fichier** : `web/server.py`

Ajouter un endpoint :
```
GET /api/replay/genetics?db=...&tick=...&species=...
→ { "diversity_index": float, "gene_means": [float×8], "gene_stds": [float×8] }
```
qui lit la keyframe la plus proche et calcule la diversité génétique de la population.

### 1-F : Tests génétique

Créer `tests/test_genetics.py` :
- Recombinaison mendélienne produit des gènes entre les deux parents
- Mutation avec taux 1.0 modifie tous les gènes
- Mutation avec taux 0.0 produit un clone exact
- `apply_to_params` respecte les bornes (facteur ±30 %)
- `genetic_distance(self, self) == 0.0`
- Sérialisation/désérialisation `to_json` / `from_json`

---

## PHASE 2 — Système de maladies

### Architecture

Les maladies sont des **agents pathogènes** paramétriques. Un individu peut être : sain,
exposé (incubation), infecté (symptomatique), rétabli (immunisé temporairement), ou mort.
La transmission se fait par contact (distance < transmission_radius) avec probabilité
`transmission_rate × (1 - receptor.disease_resistance)`. Chaque tick actif, une maladie
draine de l'énergie et réduit la mobilité.

### 2-A : Dataclass `Disease`

Créer `entities/disease.py` :

```python
"""
Système de maladies épidémiques pour EcoSim.
Modèle SEIR simplifié : Susceptible → Exposed → Infected → Recovered (→ Susceptible)
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from entities.animal import Individual

DISEASE_REGISTRY: dict[str, "DiseaseSpec"] = {}


@dataclass
class DiseaseSpec:
    name: str
    transmission_rate: float     # prob. transmission par contact par tick (0–1)
    transmission_radius: float   # distance max de contagion
    incubation_ticks: int        # ticks en état exposé avant symptômes
    infectious_ticks: int        # durée de la phase infectieuse
    energy_drain: float          # énergie drainée par tick pendant infection
    speed_penalty: float         # facteur multiplicatif sur max_speed (0.5 = -50%)
    mortality_chance: float      # prob. de mort par tick pendant infection (sans résistance)
    immunity_ticks: int          # durée de l'immunité post-guérison (0 = pas d'immunité)
    affects_species: list[str] = field(default_factory=list)  # [] = toutes les espèces

    @classmethod
    def from_dict(cls, d: dict) -> "DiseaseSpec":
        return cls(**d)


@dataclass
class DiseaseState:
    """État épidémiologique d'un individu pour une maladie donnée."""
    disease_name: str
    status: str = "susceptible"   # susceptible | exposed | infected | recovered
    ticks_in_state: int = 0
    source_id: int = -1           # id de l'individu contaminateur

    def tick(self, individual: "Individual", spec: DiseaseSpec) -> str:
        """Avance d'un tick. Retourne 'alive' ou 'dead'."""
        from entities.rng import rng
        self.ticks_in_state += 1

        if self.status == "exposed":
            if self.ticks_in_state >= spec.incubation_ticks:
                self.status = "infected"
                self.ticks_in_state = 0

        elif self.status == "infected":
            resistance = individual._effective_params.get("disease_resistance", 0.5)
            # Drain d'énergie
            individual.energy -= spec.energy_drain * (1.0 - resistance * 0.5)
            # Risque de mortalité
            mort_chance = spec.mortality_chance * (1.0 - resistance)
            if rng.random() < mort_chance:
                return "dead"
            # Guérison
            if self.ticks_in_state >= spec.infectious_ticks:
                if spec.immunity_ticks > 0:
                    self.status = "recovered"
                else:
                    self.status = "susceptible"
                self.ticks_in_state = 0

        elif self.status == "recovered":
            if self.ticks_in_state >= spec.immunity_ticks:
                self.status = "susceptible"
                self.ticks_in_state = 0

        return "alive"


def try_infect(source: "Individual", target: "Individual",
               spec: DiseaseSpec) -> bool:
    """Tente une transmission de source à target. Retourne True si infection."""
    from entities.rng import rng
    import math

    if not spec.affects_species or target.species.name in spec.affects_species:
        # Vérifier que target est susceptible
        existing = target.disease_states.get(spec.name)
        if existing and existing.status != "susceptible":
            return False
        # Distance
        dist = math.hypot(source.x - target.x, source.y - target.y)
        if dist > spec.transmission_radius:
            return False
        # Probabilité de transmission modulée par la résistance génétique
        resistance = target._effective_params.get("disease_resistance", 0.5)
        effective_rate = spec.transmission_rate * (1.0 - resistance * 0.4)
        if rng.random() < effective_rate:
            state = DiseaseState(disease_name=spec.name,
                                 status="exposed", source_id=id(source))
            target.disease_states[spec.name] = state
            return True
    return False
```

### 2-B : Intégration dans Individual

**Fichier** : `entities/animal.py`

1. Ajouter le champ : `self.disease_states: dict[str, DiseaseState] = {}`
2. Dans la méthode `tick()`, après le mouvement, avant la reproduction :
   ```python
   # ── Maladies ──────────────────────────────────────────────────────────
   dead_from_disease = False
   for ds in list(self.disease_states.values()):
       spec = DISEASE_REGISTRY.get(ds.disease_name)
       if spec:
           result = ds.tick(self, spec)
           if result == "dead":
               dead_from_disease = True
               break
   if dead_from_disease:
       mark_dead(self, "disease", grid, time_of_day, is_night)
       return
   ```

3. Ajouter une propriété :
   ```python
   @property
   def is_infectious(self) -> bool:
       return any(ds.status == "infected" for ds in self.disease_states.values())
   ```

### 2-C : Propagation dans le moteur

**Fichier** : `simulation/engine.py`

Dans la boucle tick principale, ajouter une passe de contagion :

```python
def _tick_diseases(self) -> None:
    """Propage les maladies entre individus proches."""
    from entities.disease import DISEASE_REGISTRY, try_infect
    if not DISEASE_REGISTRY:
        return
    infectious = [i for i in self.individuals if i.alive and i.is_infectious]
    if not infectious:
        return
    for source in infectious:
        for spec in DISEASE_REGISTRY.values():
            # Récupérer les voisins dans le rayon de transmission
            neighbors = self._spatial.query_radius(
                source.x, source.y, spec.transmission_radius
            )
            for target in neighbors:
                if target is not source and target.alive:
                    try_infect(source, target, spec)
```

Appeler `self._tick_diseases()` une fois par tick (pas besoin de sous-tick).

### 2-D : Maladies prédéfinies

Créer `species_data/diseases/` avec des fichiers JSON :

`myxomatosis.json` (affecte les lapins) :
```json
{
  "name": "myxomatosis",
  "transmission_rate": 0.04,
  "transmission_radius": 1.5,
  "incubation_ticks": 300,
  "infectious_ticks": 600,
  "energy_drain": 0.8,
  "speed_penalty": 0.6,
  "mortality_chance": 0.003,
  "immunity_ticks": 3600,
  "affects_species": ["lapin"]
}
```

`mange.json` (affecte renards et loups) :
```json
{
  "name": "mange",
  "transmission_rate": 0.02,
  "transmission_radius": 1.0,
  "incubation_ticks": 500,
  "infectious_ticks": 1200,
  "energy_drain": 0.5,
  "speed_penalty": 0.8,
  "mortality_chance": 0.001,
  "immunity_ticks": 7200,
  "affects_species": ["renard", "loup"]
}
```

### 2-E : Chargement des maladies

**Fichier** : `simulation/headless.py` et `web/sim_manager.py`

Au démarrage, scanner `species_data/diseases/*.json` et peupler `DISEASE_REGISTRY` :
```python
from entities.disease import DISEASE_REGISTRY, DiseaseSpec
import json
from pathlib import Path

def load_diseases(diseases_dir: Path) -> None:
    for p in diseases_dir.glob("*.json"):
        spec = DiseaseSpec.from_dict(json.loads(p.read_text()))
        DISEASE_REGISTRY[spec.name] = spec
```

### 2-F : Logging des événements épidémiques

**Fichier** : `simulation/recording/recorder.py`

Dans `on_event()`, ajouter le support des événements `"disease_infection"` et
`"disease_death"` avec payload : `{disease_name, species, x, y}`.

### 2-G : Visualisation

- Dans le renderer (`web/renderer.py` et `gui/frames/replay_frame.py`), les individus
  infectés apparaissent avec un halo orange/brun autour d'eux.
- Endpoint API : `GET /api/analyse/epidemic?db=...` retourne les courbes S/E/I/R par espèce.

### 2-H : Ajout de `disease_resistance` dans les espèces

**Fichiers** : tous les JSON dans `species_data/individuals/`

Ajouter le champ `"disease_resistance": 0.5` (valeur par défaut) dans chaque JSON.
Ajouter `disease_resistance: float = 0.5` dans la dataclass `Species`.

### 2-I : Tests maladies

Créer `tests/test_disease.py` :
- Un individu exposé passe à infecté après `incubation_ticks`
- Résistance génétique élevée réduit la mortalité
- Pas de re-infection pendant la phase recovered
- `try_infect` respecte la distance de transmission
- Les maladies se propagent dans le moteur (test d'intégration court)

---

## PHASE 3 — Reprise et extension de simulation

### Objectif

Permettre de charger un fichier `.db` existant, repartir du dernier état enregistré,
et continuer pour N ticks supplémentaires, en annexant les nouvelles données au même fichier.

### 3-A : Sérialisation complète des espèces dans la meta

**Problème actuel** : Le `.db` stocke `seed`, `world_width`, `world_height` mais pas les
paramètres complets des espèces, rendant la reconstruction impossible.

**Fichier** : `simulation/recording/recorder.py`

Ajouter une méthode :
```python
def write_species_params(self, species_list) -> None:
    """Sérialise tous les paramètres d'espèces en JSON dans meta."""
    import json
    data = []
    for sp in species_list:
        from dataclasses import asdict
        data.append(asdict(sp))
    self._conn.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES ('species_params',?)",
        (json.dumps(data),)
    )
    self._conn.commit()
```

Appeler cette méthode dans `app.py`/`sim_manager.py` après la création du Recorder.

### 3-B : Extension du schéma EntitySnapshot

Les `EntitySnapshot` doivent maintenant inclure `sex` et `genome_json` (cf. Phase 1-D).
Ajouter aussi : `reproduction_cooldown: int = 0`, `gestation_timer: int = 0`.

### 3-C : Lecture de la dernière keyframe pour reconstruction

Créer `simulation/recording/resume.py` :

```python
"""
Module de reprise de simulation depuis un fichier .db existant.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.engine import SimulationEngine


def load_engine_from_db(db_path: Path) -> "SimulationEngine":
    """
    Reconstruit un SimulationEngine depuis la dernière keyframe d'un .db.
    Retourne le moteur prêt à tourner depuis le tick suivant.
    """
    import sqlite3
    from world.grid import Grid
    from world.terrain import generate_terrain
    from simulation.engine import SimulationEngine
    from entities.animal import Individual
    from entities.plant import Plant
    from entities.genetics import Genome
    from entities.species import Species
    import dataclasses

    conn = sqlite3.connect(str(db_path))
    meta = dict(conn.execute("SELECT key,value FROM meta").fetchall())

    # Reconstruire le terrain
    width  = int(meta["world_width"])
    height = int(meta["world_height"])
    seed   = int(meta.get("seed", 0))
    preset = meta.get("terrain_preset", "default")
    grid = Grid(width=width, height=height)
    generate_terrain(grid, seed=seed, preset=preset)

    # Reconstruire le moteur
    engine = SimulationEngine(grid, seed=seed)

    # Charger les espèces
    species_data = json.loads(meta.get("species_params", "[]"))
    species_map: dict[str, Species] = {}
    for sd in species_data:
        sp = Species(**{k: v for k, v in sd.items() if k in Species.__dataclass_fields__})
        species_map[sp.name] = sp
        engine.registry.species_map[sp.name] = sp

    # Charger la dernière keyframe
    row = conn.execute(
        "SELECT tick, data_blob FROM keyframes ORDER BY tick DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("Aucune keyframe trouvée dans le fichier .db")

    from simulation.recording.schema import WorldSnapshot
    snap = WorldSnapshot.from_blob(row[1])
    engine._tick_count = snap.tick

    # Reconstruire les plantes
    for es in snap.plants:
        sp = species_map.get(es.species)
        if sp and es.alive:
            p = Plant(species=sp, x=es.x, y=es.y)
            p.energy = es.energy
            p.age    = es.age
            engine.plants.append(p)

    # Reconstruire les individus
    for es in snap.individuals:
        sp = species_map.get(es.species)
        if sp and es.alive:
            ind = Individual(species=sp, x=es.x, y=es.y)
            ind.energy = es.energy
            ind.age    = es.age
            ind.state  = es.state
            ind.sex    = getattr(es, "sex", "?")
            if getattr(es, "genome_json", ""):
                ind.genome = Genome.from_json(es.genome_json)
                ind._refresh_effective_params()
            engine.individuals.append(ind)

    conn.close()
    return engine
```

### 3-D : Mode extension dans sim_manager / app

**Fichier** : `web/sim_manager.py`

Modifier `start_simulation()` pour accepter `mode: "new" | "extend"` :
```python
if config.get("mode") == "extend" and config.get("db_path"):
    # NE PAS effacer le .db existant
    engine = load_engine_from_db(Path(config["db_path"]))
    recorder = Recorder(Path(config["db_path"]), append=True)
else:
    out_path.unlink(missing_ok=True)
    engine = build_new_engine(config)
    recorder = Recorder(out_path)
```

**Fichier** : `simulation/recording/recorder.py`

Ajouter un paramètre `append: bool = False` au constructeur.
En mode append, ne pas recréer les tables (elles existent déjà), et récupérer le dernier
`tick` pour éviter les collisions :
```python
if append:
    row = self._conn.execute(
        "SELECT MAX(tick) FROM keyframes"
    ).fetchone()
    self._last_keyframe = row[0] if row[0] else -1
```

### 3-E : Interface utilisateur — bouton "Étendre"

**Fichier** : `gui/frames/run_frame.py`

Sur l'écran "simulation terminée", ajouter un bouton "Étendre la simulation" qui ouvre
une boîte de dialogue demandant le nombre de ticks supplémentaires, puis relance via
`app.start_simulation({..., "mode": "extend", "db_path": ...})`.

**Fichier** : `web/static/index.html` (ou le composant JS équivalent)

Dans la section "runs", ajouter un bouton "▶ Étendre" à côté de chaque simulation
terminée, qui ouvre un modal avec un slider pour le nombre de ticks.

### 3-F : Tests reprise

Créer `tests/test_resume.py` :
- Lancer une simulation courte (100 ticks), l'arrêter, la reprendre pour 100 ticks de plus
- Vérifier que le tick_count repart bien depuis le tick 100 (pas de reset à 0)
- Vérifier que les populations sont plausibles (pas de doublon, pas d'extinction brutale)
- Vérifier que la nouvelle keyframe est bien annexée au .db (pas écrasée)

---

## PHASE 4 — Interface de gestion de données améliorée

### 4-A : Dashboard "Runs" dans l'interface web

**Fichier** : `web/server.py`

Enrichir l'endpoint `GET /api/runs` pour retourner :
```json
[{
  "path": "...",
  "run_id": "abc123",
  "created_at": "2025-...",
  "file_size_mb": 12.4,
  "ticks": 10000,
  "species": ["lapin", "renard", ...],
  "max_populations": {"lapin": 847, "renard": 34},
  "terrain_preset": "default",
  "seed": 42,
  "engine_version": "0.4.0",
  "thumbnail_b64": "..."  // PNG 120×96 de la dernière frame
}]
```

Ajouter un endpoint `PATCH /api/runs/{run_id}/tag` pour assigner un libellé/tag à une run.
Ajouter un endpoint `GET /api/runs/compare?a=...&b=...` pour renvoyer les timeseries des
deux runs côte à côte (même format de réponse, avec champ `run_id` dans chaque entrée).

### 4-B : Page "Tableau de bord" dans le frontend

Dans l'interface web, créer une vue `/dashboard` avec :

1. **Liste des runs** : tableau triable/filtrable par date, durée, preset, taille, espèces
2. **Vignette + métadonnées** pour chaque run (thumbnail généré depuis la dernière keyframe)
3. **Boutons d'action** : Ouvrir le replay | Étendre | Supprimer | Exporter CSV | Renommer
4. **Vue comparaison** : sélectionner 2 runs → graphe côte à côte des populations

**Technologie** : Vanilla JS + Chart.js (déjà dans requirements) dans `web/static/`.
Organiser le JS en modules ES6 dans `web/static/js/` :
- `dashboard.js` : liste des runs
- `compare.js` : vue comparaison
- `replay.js` : viewer existant
- `api.js` : wrapper fetch vers le backend

### 4-C : Export CSV enrichi

**Fichier** : `web/server.py`

Ajouter `GET /api/runs/{run_id}/export?format=csv|json` qui exporte :
- Timeseries de population (tick, espèce, count) par tick de keyframe
- Événements de naissance/mort (tick, espèce, cause)
- Statistiques agrégées (min, max, moyenne par espèce)
- Si génétique activée : diversité génétique par espèce par tick

### 4-D : Heatmaps de densité

**Fichier** : `web/renderer.py`

Ajouter `render_heatmap(snapshot, species_name, output_size)` qui génère une image PNG
représentant la densité de présence d'une espèce via un KDE (scipy.stats.gaussian_kde).

**Fichier** : `web/server.py`

Endpoint `GET /api/replay/heatmap?db=...&tick=...&species=...` retourne le PNG base64.

### 4-E : Graphes interactifs dans le replay

**Fichier** : `gui/frames/replay_frame.py`

Remplacer le mini-graphe statique (actuel, barres de population fixes) par un canvas
matplotlib embarqué dans Tkinter qui affiche la courbe de population sur les N derniers
ticks visibles, avec la position actuelle marquée d'une ligne verticale.

**Fichier** : `web/static/js/replay.js`

Dans le viewer web, ajouter un panneau latéral avec :
- Graphe de populations (Chart.js, live-scrolling pendant la lecture)
- Indicateur épidémique (courbe S/I/R si des maladies sont actives)
- Panneau "Génome" pour l'entité sélectionnée (radar chart à 8 axes)

### 4-F : Éditeur de paramètres d'espèces dans l'interface

**Fichier** : `gui/frames/setup_frame.py`

Ajouter un bouton "Modifier les paramètres" sur chaque espèce qui ouvre une fenêtre
modale (Toplevel Tkinter) avec des sliders pour :
- `reproduction_rate`, `max_speed`, `perception_radius`, `max_energy`
- `mutation_rate`, `disease_resistance` (nouveaux champs)
Les valeurs modifiées sont passées dans `config["species"][i]["params"]`.

---

## PHASE 5 — Refactoring architectural

### 5-A : Réorganisation des imports circulaires

Le projet a des imports croisés entre `entities/` et `simulation/` qui nécessitent des
`TYPE_CHECKING` guards. Vérifier et documenter chaque import circulaire dans un commentaire
`# circular-import-guard` pour les futures refactorisations.

### 5-B : Répertoire `config/` pour les constantes

Créer `config/simulation_defaults.py` regroupant :
- `DAY_LENGTH`, `SIM_YEAR` (actuellement dans `engine_const.py`)
- `RENDER_W`, `RENDER_H` (actuellement dans `web/renderer.py`)
- `WIN_W`, `WIN_H` (actuellement dans `gui/app.py`)
- `N_GENES`, `GENE_INFLUENCE` (nouveau, depuis `entities/genetics.py`)

### 5-C : Validation des configs en entrée

Créer `config/validator.py` qui valide le dict `config` avant démarrage :
- `grid_size` entre 20 et 500
- `ticks` > 0
- Au moins une espèce activée
- `out_path` est un chemin valide avec l'extension `.db`
Retourner une liste d'erreurs lisibles, affichées dans l'UI avant le lancement.

### 5-D : `spatial_grid.py` — filtre cercle exact

La méthode `query()` du `SpatialGrid` retourne une bounding-box carrée, pas un cercle.
Tous les appels qui filtrent par `perception_radius` ou `transmission_radius` font ensuite
une vérification de distance manuellement. Centraliser ce filtre :
```python
def query_radius(self, x: float, y: float, radius: float) -> list:
    candidates = self.query(x, y, radius)
    r2 = radius * radius
    return [e for e in candidates
            if (e.x - x)**2 + (e.y - y)**2 <= r2]
```
Utiliser `query_radius()` partout dans les mixins et le moteur de maladies.

---

## Ordre d'implémentation recommandé

```
Phase 0 (bugs)  →  Phase 1 (génétique)  →  Phase 2 (maladies)
                →  Phase 3 (reprise)    →  Phase 4 (interface)
                →  Phase 5 (refactoring)
```

Les phases 1, 3 et 5 peuvent être menées en parallèle après la Phase 0.
La Phase 2 dépend de la Phase 1 (pour `disease_resistance` génétique).
La Phase 4 peut commencer dès que la Phase 0 est terminée.

**À chaque phase** :
1. Écrire les tests d'abord (TDD)
2. Implémenter
3. Vérifier que les 121 tests existants passent toujours
4. Lancer une simulation courte (500 ticks) pour validation fonctionnelle

---

## Checklist de validation finale

- [ ] `pytest` → 0 échec (incluant les nouveaux tests)
- [ ] `python main.py --headless --ticks 500` → se termine sans erreur
- [ ] `python main.py --tk` → GUI démarre, simulation de 200 ticks, replay fonctionne
- [ ] `python main.py` (web) → serveur démarre, simulation via browser, replay via browser
- [ ] Reprise : lancer 500 ticks, reprendre pour 500 de plus → tick_count == 1000 dans le .db
- [ ] Génétique : après 1000 ticks, `GET /api/replay/genetics` retourne `diversity_index > 0`
- [ ] Maladies : myxomatosis configurée, après 2000 ticks sur une pop lapin > 200,
      au moins 1 événement `disease_death` dans la table `events`
- [ ] Dashboard : liste des runs triable, export CSV téléchargeable, comparaison 2 runs affichée
