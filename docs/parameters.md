# Paramètres EcoSim — Référence et Calibration

Ce document décrit chaque paramètre du modèle, son unité, ses valeurs par défaut,
et les sources ou justifications biologiques lorsqu'elles existent.

---

## Paramètres de l'espèce (Species)

### Conditions de survie

| Paramètre | Unité | Défaut | Description | Source |
|---|---|---|---|---|
| `temp_min` | °C | 0.0 | Température minimale de survie | Ecophysiologie standard |
| `temp_max` | °C | 40.0 | Température maximale de survie | |
| `humidity_min` | [0,1] | 0.0 | Humidité minimale | |
| `humidity_max` | [0,1] | 1.0 | Humidité maximale | |
| `altitude_min` | [0,1] | 0.0 | Altitude minimale | |
| `altitude_max` | [0,1] | 1.0 | Altitude maximale | |

### Énergie

| Paramètre | Unité | Défaut | Description | Source |
|---|---|---|---|---|
| `energy_start` | E | 100.0 | Énergie initiale et maximale | Arbitraire |
| `energy_consumption` | E/tick | 1.0 | Coût métabolique de base | Arbitraire |
| `energy_from_food` | E | 50.0 | Gain par acte alimentaire | |
| `bite_size` | fraction | 0.35 | Part d'énergie prélevée à la proie | |

### Reproduction

| Paramètre | Unité | Défaut | Description | Source |
|---|---|---|---|---|
| `reproduction_rate` | prob/tick | 0.1 | Probabilité de reproduction par tick | |
| `reproduction_cooldown_length` | ticks | 15 | Délai post-naissance | |
| `litter_size_min` | n | 1 | Nombre minimum de petits | |
| `litter_size_max` | n | 1 | Nombre maximum de petits | |
| `sexual_maturity_ticks` | ticks | 0 | Maturité sexuelle | |
| `gestation_ticks` | ticks | 0 | Durée de gestation | |
| `juvenile_mortality_rate` | prob/tick | 0.0 | Mortalité juvénile | Albon et al. 1987 (cerfs) |
| `fear_factor` | [0,∞] | 0.0 | Réduction de reprod. par prédateur proche | Lima & Dill 1990 |

### Comportement

| Paramètre | Unité | Défaut | Description | Source |
|---|---|---|---|---|
| `speed` | u/tick | 1.0 | Vitesse de déplacement | |
| `perception_radius` | u | 5.0 | Rayon de perception sensorielle | |
| `activity_pattern` | str | "diurnal" | "diurnal" \| "nocturnal" \| "crepuscular" | |
| `herd_cohesion` | [0,1] | 0.0 | Force du comportement grégaire | Hamilton 1971 |

### Mortalité sénescente (Gompertz)

| Paramètre | Unité | Défaut | Description | Source |
|---|---|---|---|---|
| `gompertz_a` | prob/tick | 0.0001 | Taux de mortalité basal | Gompertz 1825 |
| `gompertz_b` | adim | 5.0 | Accélération de la mortalité avec l'âge | |
| `max_age` | ticks | 100 | Limite dure d'âge | |

> **Calibration** : avec `a=0.0001, b=5.0`, `p_mort(max_age) ≈ 0.05/tick` (mort quasi-certaine).
> Pour des espèces à longue durée de vie (oiseaux), réduire `b` à 3.0–4.0.
> Pour des rongeurs à courte vie, `b=6.0–8.0`.

### Dimorphisme sexuel

| Paramètre | Unité | Défaut | Description |
|---|---|---|---|
| `male_speed_factor` | ×base | 1.0 | Vitesse relative des mâles |
| `female_speed_factor` | ×base | 1.0 | Vitesse relative des femelles |
| `male_max_age_factor` | ×base | 1.0 | Longévité relative des mâles |
| `female_max_age_factor` | ×base | 1.0 | Longévité relative des femelles |

> **Exemple lions** : `male_speed_factor=0.9`, `female_speed_factor=1.1`,
> `male_max_age_factor=0.85`, `female_max_age_factor=1.0` (Packer et al. 1998).

### Génétique

| Paramètre | Unité | Défaut | Description |
|---|---|---|---|
| `mutation_rate` | [0,1] | 0.0 | Probabilité de mutation par gène |

> Valeur typique : `0.01–0.05`. Au-delà de `0.10`, erreur catastrophique possible.

### Maladies

| Paramètre | Unité | Défaut | Description |
|---|---|---|---|
| `disease_resistance` | [0,1] | 0.5 | Résistance innée aux pathogènes |

### Territoire

| Paramètre | Unité | Défaut | Description |
|---|---|---|---|
| `territory_radius` | u | 0.0 | Rayon du territoire natal |
| `home_protection` | [0,1] | 0.0 | Protection contre les prédateurs sur territoire |

### Capacité de charge

| Paramètre | str | Défaut | Description |
|---|---|---|---|
| `carrying_capacity_mode` | str | "hard" | "hard" = plafond dur \| "emergent" = ressources |
| `max_population` | n | 200 | Plafond (mode hard) |

---

## Paramètres de la maladie (DiseaseSpec)

| Paramètre | Unité | Description |
|---|---|---|
| `transmission_rate` | prob | Probabilité de transmission par contact |
| `transmission_radius` | u | Rayon de contagion |
| `incubation_ticks` | ticks | Durée de latence (E→I) |
| `infectious_ticks` | ticks | Durée contagieuse (I→R) |
| `energy_drain` | E/tick | Coût énergétique de l'infection |
| `speed_penalty` | [0,1] | Réduction de vitesse (non encore implémenté physiquement) |
| `mortality_chance` | prob/tick | Probabilité de mort par tick infectieux |
| `immunity_ticks` | ticks | Durée de l'immunité (R→S, 0 = sans immunité) |
| `mutation_rate_pathogen` | [0,1] | Probabilité de mutation à chaque transmission |

> **R₀ attendu** : R₀ ≈ `transmission_rate × (1 − resistance × 0.4) × infectious_ticks × n_contacts/tick`.
> Pour R₀ > 1 (épidémie) avec 10 voisins/tick : `transmission_rate > 0.1`.

---

## Paramètres du terrain (Grid)

| Paramètre | Défaut | Description |
|---|---|---|
| `width, height` | 500 | Dimensions de la grille |
| `nutrients` | 1.0 partout | Richesse initiale du sol |

---

## Constantes du moteur

| Constante | Valeur | Description |
|---|---|---|
| `DAY_LENGTH` | 1 200 ticks | Durée d'un jour simulé |
| `SIM_YEAR` | 438 000 ticks | Durée d'une année (365 × 1 200) |
| `GENE_INFLUENCE` | 0.30 | Amplitude max de modification phénotypique par gène |
| `N_GENES` | 8 | Gènes fonctionnels |
| `N_NEUTRAL_GENES` | 20 | Gènes neutres (dérive) |

---

## Références

- Albon, S.D. et al. (1987). Early development and population dynamics in Red Deer.
- Gompertz, B. (1825). On the nature of the function expressive of the law of human mortality.
- Hamilton, W.D. (1971). Geometry for the selfish herd. *Journal of Theoretical Biology*.
- Lima, S.L. & Dill, L.M. (1990). Behavioral decisions made under the risk of predation.
- Packer, C. et al. (1998). Reproductive cessation in female mammals. *Nature*.
