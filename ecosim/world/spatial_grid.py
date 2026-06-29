"""
Hash spatial pour requêtes de voisinage en O(n).

ÉTAPE 2 du plan de vectorisation : la grille stocke des INDICES entiers
(int32) au lieu d'objets Entity. `query` et `query_radius` renvoient des
np.ndarray d'indices ; les appelants matérialisent les entités via leurs
listes (`engine.individuals[i]`) — ce qui permet, dans les étapes
suivantes, de remplacer la résolution par des slices NumPy.

Pour préserver `query_radius` (filtrage strict du cercle) sans dépendre
d'un lookup externe, chaque insert stocke (x, y, idx) — la position est
nécessaire au filtre. Le coût mémoire est proche du précédent (un tuple
de 3 valeurs au lieu d'un pointeur d'objet), et l'avantage est que les
indices sont directement utilisables côté SoA.
"""
from __future__ import annotations

import numpy as np

_STRIDE = 1 << 14   # 16384 — > 500/cell_size cells max en une direction
_EMPTY = np.empty(0, dtype=np.int32)


class SpatialGrid:
    """Grille spatiale pour la recherche de voisins, stockée en indices.

    Voisinage en O(n) sur la taille de la grille, et O(k) sur le nombre
    d'entités dans le voisinage. La clé entière ``c * _STRIDE + r`` évite
    l'allocation et le hachage multi-étapes des tuples Python dans le hot
    path.
    """

    __slots__ = ("cell_size", "_cells", "_inv_cell")

    def __init__(self, cell_size: float) -> None:
        self.cell_size = max(cell_size, 1.0)
        self._inv_cell = 1.0 / self.cell_size
        self._cells: dict = {}

    def clear(self) -> None:
        self._cells = {}

    def insert(self, x: float, y: float, idx: int) -> None:
        """Insère une entité à la position (x, y) avec son indice `idx`.

        L'indice fait référence à la liste de vérité du moteur
        (`engine.individuals[idx]` ou `engine.plants[idx]`).
        """
        key = int(x * self._inv_cell) * _STRIDE + int(y * self._inv_cell)
        try:
            self._cells[key].append((x, y, idx))
        except KeyError:
            self._cells[key] = [(x, y, idx)]

    def query(self, x: float, y: float, radius: float) -> np.ndarray:
        """Indices des entités dont la cellule intersecte le carré englobant
        le cercle de centre (x, y) et de rayon `radius`. dtype int32.
        """
        inv    = self._inv_cell
        c0     = int((x - radius) * inv)
        c1     = int((x + radius) * inv)
        r0     = int((y - radius) * inv)
        r1     = int((y + radius) * inv)
        cells  = self._cells
        stride = _STRIDE
        out: list[int] = []
        append = out.append
        for c in range(c0, c1 + 1):
            base = c * stride
            for r in range(r0, r1 + 1):
                bucket = cells.get(base + r)
                if bucket:
                    for _ex, _ey, i in bucket:
                        append(i)
        if not out:
            return _EMPTY
        return np.asarray(out, dtype=np.int32)

    def query_radius(self, x: float, y: float, radius: float) -> np.ndarray:
        """Comme `query` mais filtre exactement dans le cercle (pas le carré).

        Le filtre utilise les (x, y) stockés à l'insertion — pas de lookup
        externe. dtype int32.
        """
        inv    = self._inv_cell
        c0     = int((x - radius) * inv)
        c1     = int((x + radius) * inv)
        r0     = int((y - radius) * inv)
        r1     = int((y + radius) * inv)
        cells  = self._cells
        stride = _STRIDE
        r2     = radius * radius
        out: list[int] = []
        append = out.append
        for c in range(c0, c1 + 1):
            base = c * stride
            for r in range(r0, r1 + 1):
                bucket = cells.get(base + r)
                if bucket:
                    for ex, ey, i in bucket:
                        dx = ex - x
                        dy = ey - y
                        if dx * dx + dy * dy <= r2:
                            append(i)
        if not out:
            return _EMPTY
        return np.asarray(out, dtype=np.int32)
