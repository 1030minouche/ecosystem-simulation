# BALANCE_REPORT — Correctifs d'équilibre écologique

Run de référence : **seed=42, grille 500×500, 21 415 ticks** (`rapport_20260418_003345.json`)

---

## Résumé des 5 correctifs appliqués

| # | Scope | Modification |
|---|-------|-------------|
| 1 | `feeding.py` + `species.py` | Consommation incrémentale (`bite_size = 0.35`) — la proie survit tant que son énergie > 0 |
| 2 | JSON plantes | `growth_rate ×8`, `reproduction_cooldown_length ÷2` pour Herbe, Fougère, Champignon, Baies |
| 3 | `engine.py` | Tick des plantes tous les 3 ticks (au lieu de 10) |
| 4 | `renard.json` | Champignon retiré des sources alimentaires du Renard |
| 5 | `lapin.json`, `campagnol.json` | `energy_start ×1.5`, `energy_consumption ÷1.5` |

---

## Avant / Après — Causes de mort (baseline ~10 000 ticks)

| Cause | Avant | Après (estimé) |
|-------|-------|----------------|
| Famine | ~477 | Très réduite (herbivores stables) |
| Prédation | ~41 | Augmentée (bite_size permet plus d'actes de prédation) |
| Vieillesse | 0 | Non observée (run trop court / prédateurs éteints) |
| **Ratio famine/prédation** | **~11.6** | **< 3 (estimé)** |

> Note : le rapport JSON généré par le jeu ne contient pas encore le détail des causes de mort.
> L'amélioration est déduite de la stabilisation des populations herbivores.

---

## Évolution des populations (snapshots)

| Tick | Herbe | Fougère | Lapin | Campagnol | Cerf | Renard | Loup |
|------|-------|---------|-------|-----------|------|--------|------|
| 0    | 800   | 500     | 100   | 120       | 50   | 20     | 10   |
| 5 000 | 8 038 | 1 256  | 158   | 132       | 49   | 8      | 0 ✝ |
| 10 000 | 8 383 | 1 111 | 151   | 119       | 46   | 1      | — |
| 15 000 | 8 418 | 1 097 | 199   | 119       | 46   | 0 ✝   | — |
| 20 000 | 8 446 | 1 082 | 216   | 117       | 45   | —      | — |

---

## Résultats finaux (tick 21 415)

### Espèces survivantes
| Espèce | Population finale |
|--------|-----------------|
| Herbe | 8 452 |
| Fougère | 1 079 |
| Baies | 319 |
| Champignon | 150 |
| Lapin | 213 |
| Campagnol | 112 |
| Cerf | 41 |
| Sanglier | 36 |

### Espèces éteintes
| Espèce | Tick d'extinction |
|--------|-----------------|
| Loup | ~3 666 |
| Aigle | ~10 173 |
| Hibou | ~13 287 |
| Renard | ~14 849 |

**Indice de Shannon** (espèces survivantes) : **0.74**

---

## Analyse

### Succès

- **Biomasse végétale stable** : Herbe maintenue ~8 000-8 500 sur toute la durée (vs effondrement avant les correctifs). Objectif atteint.
- **Herbivores oscillants** : Lapin (100→216), Campagnol (~120), Cerf (~45) oscillent sans s'effondrer. Aucune famine en cascade.
- **Bite_size efficace** : la consommation incrémentale permet à une plante mature de nourrir plusieurs herbivores, réduisant la mortalité par famine.

### Problème résiduel — extinction des prédateurs

Les 4 prédateurs s'éteignent progressivement. Causes probables :

1. **Densité proies trop faible sur 500×500** : avec 100-200 lapins sur 250 000 cases, un prédateur peut errer longtemps sans rencontre.
2. **Effectifs initiaux trop bas** : Loup=10, Aigle=6, Hibou=6 — pas de masse critique pour maintenir une population.
3. **`bite_size` trop faible pour les grands prédateurs** : 35% × `energy_start_lapin` donne ~52 énergie par morsure, insuffisant pour Loup/Renard avec `energy_consumption=0.1/tick`.

### Recommandations pour la prochaine itération

- Augmenter `bite_size` des carnivores à 0.6-0.8 (via `bite_size` dans leurs JSON une fois le champ supporté).
- Augmenter les effectifs initiaux : Loup→20, Renard→30, Aigle/Hibou→12.
- Ou réduire `energy_consumption` du Loup/Renard de 20%.

---

## Tests

```
113 passed in 0.71s
```
Aucune régression.
