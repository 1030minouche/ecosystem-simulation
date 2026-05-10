"""
Module-level numpy RNG wrapper partagé par tous les modules d'entités.

Le moteur appelle rng.reset(seed) à l'initialisation pour garantir
le déterminisme : une seule source d'aléa, propagée depuis le seed initial.

Interface identique au module `random` pour faciliter la migration.
"""

from __future__ import annotations
import numpy as np


class _RNGWrapper:
    def __init__(self, seed: int | None = None) -> None:
        self._g: np.random.Generator = np.random.default_rng(seed)

    def reset(self, seed: int | None = None) -> None:
        self._g = np.random.default_rng(seed)

    def fork(self, seed: int | None = None) -> "_RNGWrapper":
        """Crée un nouveau wrapper indépendant (pour les simulations parallèles)."""
        child_seed = seed if seed is not None else int(self._g.integers(0, 2**31))
        return _RNGWrapper(child_seed)

    @property
    def generator(self) -> np.random.Generator:
        return self._g

    def random(self) -> float:
        return float(self._g.random())

    def uniform(self, low: float = 0.0, high: float = 1.0) -> float:
        return float(self._g.uniform(low, high))

    def choice(self, seq: list):
        return seq[int(self._g.integers(0, len(seq)))]

    def randint(self, low: int, high: int) -> int:
        return int(self._g.integers(low, high + 1))

    def gauss(self, mu: float, sigma: float) -> float:
        return float(self._g.normal(mu, sigma))

    def shuffle(self, lst: list) -> None:
        arr = self._g.permuted(lst)
        lst[:] = list(arr)


rng = _RNGWrapper()
