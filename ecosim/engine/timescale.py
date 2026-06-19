"""
Découplage du temps biologique et du temps de calcul.

Le moteur reste calibré en « ticks » fins (DAY_LENGTH = 1 200 ticks/jour).
Pour observer un cycle proie–prédateur ou de la dérive génétique sans
attendre des heures, on accélère **la biologie** : toutes les durées des
espèces (`*_ticks`, `*_age`, `*_cooldown_length`) sont divisées par un
facteur `time_acceleration` au chargement.

Limites :
- Les rates *par tick* (vitesse, consommation d'énergie, gain alimentaire)
  ne sont **pas** modifiés. Une espèce accélérée mange/bouge à la même
  vitesse instantanée mais arrive à la maturité, gestation et mort
  beaucoup plus tôt — c'est volontaire, on veut compresser le cycle
  démographique sans dénaturer le pas de simulation.
- `time_acceleration = 1.0` (défaut) ⇒ aucune modification.

Usage :
    from ecosim.engine.timescale import apply_time_acceleration
    scaled_params = apply_time_acceleration(params, time_acceleration=10.0)
"""

from __future__ import annotations

# Suffixes des champs qui désignent une durée en ticks.
_DURATION_SUFFIXES = (
    "_ticks",
    "_age",
    "_cooldown_length",
)


def is_duration_field(key: str) -> bool:
    """Vrai si `key` désigne une durée exprimée en ticks de simulation."""
    return any(key.endswith(s) for s in _DURATION_SUFFIXES)


def apply_time_acceleration(params: dict, time_acceleration: float) -> dict:
    """
    Retourne une copie de `params` avec toutes les durées divisées
    par `time_acceleration`. Préserve la nature numérique (int/float)
    et conserve les écarts-types (`*_std`).
    """
    if time_acceleration == 1.0 or time_acceleration <= 0:
        return params
    scaled = dict(params)
    for k, v in params.items():
        if not is_duration_field(k):
            continue
        if not isinstance(v, (int, float)):
            continue
        new_v = v / time_acceleration
        scaled[k] = max(1, int(new_v)) if isinstance(v, int) else new_v
    return scaled
