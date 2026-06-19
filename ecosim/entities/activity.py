"""
Rythmes d'activité circadiens.

tod (time_of_day) ∈ [0, 1)
  0.00 = minuit  |  0.25 = aube  |  0.50 = midi  |  0.75 = crépuscule

Perf : `_is_resting` et `_is_pre_rest` sont appelées des centaines de
milliers de fois par tick (une fois par individu, plus une fois par
candidat dans `_nearest_predator`). Pour un même tick, `tod` est constant
et il n'existe que 3 patterns possibles. On garde donc un petit cache
module-level invalidé dès que `tod` change.
"""

TICKS_PER_SECOND = 10   # cadence cible pour le calcul de déplacement

_PRE_REST_BUFFER = 0.06   # fenêtre de "recherche d'abri" avant le repos

# ── Cache par tick ────────────────────────────────────────────────────────────
# Au sein d'un tick, tod est constant. On garde 3 entrées max (une par pattern).
_resting_tod: float = -1.0
_resting_cache: dict = {}
_pre_rest_tod: float = -1.0
_pre_rest_cache: dict = {}


def _compute_resting(tod: float, pattern: str) -> bool:
    if pattern == "nocturnal":
        return 0.18 <= tod < 0.82          # dort le jour
    if pattern == "crepuscular":
        # Actif à l'aube (0.18-0.38) et au crépuscule (0.62-0.82)
        return not ((0.18 <= tod < 0.38) or (0.62 <= tod < 0.82))
    # diurnal
    return tod >= 0.82 or tod < 0.18       # dort la nuit


def _is_resting(tod: float, pattern: str) -> bool:
    """True si l'individu devrait se reposer selon son rythme d'activité."""
    global _resting_tod
    if tod != _resting_tod:
        _resting_cache.clear()
        _resting_tod = tod
    try:
        return _resting_cache[pattern]
    except KeyError:
        result = _compute_resting(tod, pattern)
        _resting_cache[pattern] = result
        return result


def _compute_pre_rest(tod: float, pattern: str) -> bool:
    if pattern == "diurnal":
        return (0.82 - _PRE_REST_BUFFER) <= tod < 0.82
    if pattern == "nocturnal":
        return (0.18 - _PRE_REST_BUFFER) <= tod < 0.18
    if pattern == "crepuscular":
        return ((0.38 - _PRE_REST_BUFFER) <= tod < 0.38 or
                (0.82 - _PRE_REST_BUFFER) <= tod < 0.82)
    return False


def _is_pre_rest(tod: float, pattern: str) -> bool:
    """True si l'individu entre dans sa phase de recherche d'abri."""
    global _pre_rest_tod
    if tod != _pre_rest_tod:
        _pre_rest_cache.clear()
        _pre_rest_tod = tod
    try:
        return _pre_rest_cache[pattern]
    except KeyError:
        result = _compute_pre_rest(tod, pattern)
        _pre_rest_cache[pattern] = result
        return result
