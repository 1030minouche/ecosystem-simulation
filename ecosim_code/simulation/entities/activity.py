"""
Rythmes d'activité circadiens.

tod (time_of_day) ∈ [0, 1)
  0.00 = minuit  |  0.25 = aube  |  0.50 = midi  |  0.75 = crépuscule
"""

TICKS_PER_SECOND = 50   # cadence cible pour le calcul de déplacement

_PRE_REST_BUFFER = 0.06   # fenêtre de "recherche d'abri" avant le repos


def _is_resting(tod: float, pattern: str) -> bool:
    """True si l'individu devrait se reposer selon son rythme d'activité."""
    if pattern == "nocturnal":
        return 0.18 <= tod < 0.82          # dort le jour
    elif pattern == "crepuscular":
        # Actif à l'aube (0.18-0.38) et au crépuscule (0.62-0.82)
        # Repos en pleine nuit et en pleine journée
        return not ((0.18 <= tod < 0.38) or (0.62 <= tod < 0.82))
    else:  # diurnal
        return tod >= 0.82 or tod < 0.18   # dort la nuit


def _is_pre_rest(tod: float, pattern: str) -> bool:
    """True si l'individu entre dans sa phase de recherche d'abri."""
    if pattern == "diurnal":
        return (0.82 - _PRE_REST_BUFFER) <= tod < 0.82
    elif pattern == "nocturnal":
        return (0.18 - _PRE_REST_BUFFER) <= tod < 0.18
    elif pattern == "crepuscular":
        # Avant le repos de pleine journée et avant le repos de pleine nuit
        return ((0.38 - _PRE_REST_BUFFER) <= tod < 0.38 or
                (0.82 - _PRE_REST_BUFFER) <= tod < 0.82)
    return False
