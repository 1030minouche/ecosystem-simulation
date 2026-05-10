_STRIDE = 1 << 14   # 16384 — largement > 500/cell_size cells max en une direction


class SpatialGrid:
    """Grille spatiale pour accélérer la recherche de voisins de O(n²) à O(n).

    Divise le monde en cellules carrées. Chaque entité est insérée dans la
    cellule correspondant à sa position. Une requête en rayon r ne consulte
    que les cellules qui intersectent le carré englobant.

    Optimisations clés :
    - Clé entière ``c * _STRIDE + r`` au lieu d'un tuple ``(c, r)`` : évite
      l'allocation heap + hachage multi-étapes des tuples Python dans le hot path.
    - ``try/except KeyError`` à l'insertion plutôt qu'un double lookup ``in``+``[]``.
    - ``clear`` recrée le dict (libération C-level plus rapide que dict.clear).
    - Variables locales dans ``query`` pour éviter la résolution d'attributs.
    """

    __slots__ = ("cell_size", "_cells", "_inv_cell")

    def __init__(self, cell_size: float) -> None:
        self.cell_size = max(cell_size, 1.0)
        self._inv_cell = 1.0 / self.cell_size
        self._cells: dict = {}

    def clear(self) -> None:
        self._cells = {}

    def insert(self, entity) -> None:
        inv = self._inv_cell
        key = int(entity.x * inv) * _STRIDE + int(entity.y * inv)
        try:
            self._cells[key].append(entity)
        except KeyError:
            self._cells[key] = [entity]

    def query(self, x: float, y: float, radius: float) -> list:
        """Retourne toutes les entités dont la cellule intersecte le carré
        englobant le cercle de centre (x, y) et de rayon radius."""
        inv    = self._inv_cell
        c0     = int((x - radius) * inv)
        c1     = int((x + radius) * inv)
        r0     = int((y - radius) * inv)
        r1     = int((y + radius) * inv)
        cells  = self._cells
        stride = _STRIDE
        result: list = []
        extend = result.extend
        for c in range(c0, c1 + 1):
            base = c * stride
            for r in range(r0, r1 + 1):
                bucket = cells.get(base + r)
                if bucket:
                    extend(bucket)
        return result

    def query_radius(self, x: float, y: float, radius: float) -> list:
        """Comme query() mais filtre exactement dans le cercle (pas la bounding box)."""
        candidates = self.query(x, y, radius)
        r2 = radius * radius
        return [e for e in candidates if (e.x - x) ** 2 + (e.y - y) ** 2 <= r2]
