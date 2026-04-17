from collections import Counter
from typing import Iterable


def count_by_species(entities: Iterable) -> dict[str, int]:
    """Retourne le nombre d'entités vivantes par nom d'espèce."""
    return dict(Counter(e.species.name for e in entities if e.alive))
