# ODD Protocol — EcoSim

> ODD (Overview, Design concepts, Details) est le standard de description des modèles
> agents (Grimm et al. 2006, 2010, 2020). Ce document décrit EcoSim selon ce protocole.

---

## 1. Purpose and patterns

**Purpose** : EcoSim est un simulateur d'écosystèmes multi-espèces basé sur des agents
discrets (ticks). Il est conçu pour étudier :

- La dynamique des populations (cycles proie-prédateur, extinction, explosion)
- L'évolution des traits phénotypiques par sélection naturelle
- La propagation d'épidémies et l'évolution des pathogènes
- L'effet de la saisonnalité et des nutriments sur la structure des communautés
- La diversité génétique (He, π, Fst) et les signatures de dérive

**Patterns cibles** :
- Oscillations de Lotka-Volterra (proie-prédateur)
- Endémisme et différentiation spatiale (Fst > 0)
- Propagation épidémique sigmoïde avec R₀ > 1

---

## 2. Entities, state variables, and scales

### 2.1 Agents

#### Individual (animal)
| Variable | Type | Description |
|---|---|---|
| `uid` | int | Identifiant permanent unique |
| `x, y` | float | Position continue sur la grille |
| `species` | Species | Référence à l'espèce |
| `sex` | str | "male" / "female" |
| `age` | int | Âge en ticks |
| `energy` | float | Énergie courante |
| `state` | str | État comportemental (wander, feed, rest…) |
| `genome` | Genome | 8 gènes fonctionnels + 20 gènes neutres |
| `disease_states` | dict | État SEIR par pathogène |
| `parent_id, parent_b_id` | int | UIDs des parents (−1 = fondateur) |

#### Plant
| Variable | Type | Description |
|---|---|---|
| `x, y` | float | Position |
| `species` | Species | Référence à l'espèce végétale |
| `growth` | float | Taux de croissance [0, 1] |
| `energy` | float | Énergie (source pour les herbivores) |
| `age` | int | Âge en ticks |

### 2.2 Environnement (Grid)
| Variable | Dimensions | Description |
|---|---|---|
| `altitude` | H×W float | Altitude normalisée [0, 1] |
| `temperature` | H×W float | Température en °C |
| `humidity` | H×W float | Humidité [0, 1] |
| `soil_type` | H×W str | "clay", "sand", "rock", "water"… |
| `nutrients` | H×W float | Richesse du sol [0, 1] |

### 2.3 Échelles
- **Espace** : grille discrète de 500×500 cellules (par défaut), coordonnées continues
- **Temps** : 1 tick ≈ 1/20 s réelle ; 1 200 ticks/jour simulé ; 438 000 ticks/an

---

## 3. Process overview and scheduling

À chaque tick (dans l'ordre) :

1. **Saisonnalité** : calcul du facteur `season = sin(2π × tick / SIM_YEAR)`
2. **Plantes** (1 tick sur 3) :
   - Croissance modulée par saison et nutriments
   - Dispersion si `growth > 0.8` et capacité de charge non atteinte
   - Mort (libère des nutriments)
3. **Mise à jour des grilles spatiales** (SpatialGrid)
4. **Animaux** :
   - Consommation d'énergie (×0.3 si repos)
   - Mortalité Gompertz au-delà de 50% de `max_age`
   - Machine à états (wander → feed → flee → rest)
   - Mouvement (exploration + cohésion de troupeau)
   - Alimentation (plantes ou proies)
   - Reproduction (sélection sexuelle sur top-3 énergie)
   - Mort (énergie ≤ 0, âge, prédation, maladie)
5. **Propagation des maladies** (SEIR, rayon de transmission)
6. **Détection des extinctions**

---

## 4. Design concepts

### Basic principles
Modèle agent individu-centré avec héritage génétique mendelien et sélection naturelle
émergente. Aucune optimisation globale n'est codée : la sélection résulte uniquement
de la différence de survie et de reproduction entre individus.

### Emergence
- Dynamiques populationnelles (cycles, extinctions) émergent des interactions locales
- Différentiation génétique spatiale (Fst > 0) émerge de la barrière géographique (eau)

### Adaptation
Chaque trait phénotypique est modulé par un gène (`GENE_INFLUENCE = 0.30`) :
`paramètre_effectif = valeur_base × (1 + gène × 0.30)`

### Fitness
Implicite : déterminé par la survie jusqu'à la reproduction et le nombre d'offspring.

### Sensing
Chaque individu perçoit les entités dans un rayon `perception_radius` (grid spatiale).
Les volants ont un bonus de vitesse ×1.4.

### Interaction
- Prédation : un carnivore réduit l'énergie d'une proie adjacente
- Maladie : transmission probabiliste dans le rayon `transmission_radius`
- Compétition : indirecte (ressources communes, capacité de charge)
- Troupeau : cohésion vers le centroïde local (`herd_cohesion ∈ [0, 1]`)

### Stochasticity
- RNG global réinitialisable par `seed` (reproductibilité exacte)
- Mutation gaussienne au génome à la naissance (`mutation_rate`)
- Transmission maladie, mort Gompertz, prédation : probabilistes

### Collectives
Troupeaux implicites via `herd_cohesion`. Pas de rôles définis.

### Observation
- Keyframes SQLite toutes les 500 ticks (compressées gzip)
- Tables `life_history`, `pedigree`, `displacement`, `counts` (métriques écologiques)
- Métriques génétiques calculables en post-traitement (`analysis/genetics_metrics.py`)

---

## 5. Initialization

1. Génération du terrain (`world/terrain.py`) : altitude → humidité → température → sol
2. Pour chaque espèce : `count` individus placés aléatoirement sur des cellules non-eau
3. Génomes initiaux aléatoires (uniform [−1, 1])
4. Ticks initiaux : `tick_count = DAY_LENGTH // 2` (milieu du premier jour)

---

## 6. Input data

Aucune donnée externe : terrain et espèces sont générés procéduralement.
Les paramètres d'espèces sont définis dans des fichiers JSON (`species/*.json`).

---

## 7. Submodels

### 7.1 Saisonnalité
```
season(t) = sin(2π × t / 438000)
growth_saisonnière = growth_rate × (1 + 0.30 × season)
énergie_plante += 0.05 × (1 + 0.20 × season) × nut_factor
```

### 7.2 Mortalité Gompertz
```
p_mort(t) = a × exp(b × t / max_age),  t > 0.5 × max_age
valeurs par défaut : a = 0.0001,  b = 5.0
```

### 7.3 Génétique
- 8 gènes fonctionnels (vitesse, énergie, résistance maladie…)
- 20 gènes neutres (dérive génétique)
- Recombinaison mendélienne uniforme + mutation gaussienne N(0, 0.15)
- Hétérozygotie attendue He = 1 − Σpᵢ² (gènes neutres)

### 7.4 Épidémiologie (SEIR)
```
Susceptible → Exposed (incubation_ticks) → Infected (infectious_ticks) → Recovered
R₀ empirique = mean(nb_infectés_par_source)
```

### 7.5 Cycle des nutriments
```
consommation: nutrients[y,x] -= 0.00005  (par croissance de plante)
décomposition: nutrients[y,x] += 0.002   (à la mort d'une plante)
nutrient restocked by dead cadavers (animals via engine)
```

---

## Références

- Grimm, V. et al. (2006). A standard protocol for describing individual-based and
  agent-based models. *Ecological Modelling*, 198, 115–126.
- Grimm, V. et al. (2020). The ODD protocol for describing agent-based and other
  simulation models: A second update to improve clarity, replication, and structural
  realism. *JASSS*, 23(2), 7.
- Nei, M. (1973). Analysis of gene diversity in subdivided populations.
- Wright, S. (1951). The genetical structure of populations. *Annals of Eugenics*, 15, 323–354.
