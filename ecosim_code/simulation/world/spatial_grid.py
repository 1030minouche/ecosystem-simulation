class SpatialGrid:
    """Grille spatiale pour accélérer la recherche de voisins de O(n²) à O(n).

    Divise le monde en cellules carrées. Chaque entité est insérée dans la
    cellule correspondant à sa position. Une requête en rayon r ne consulte
    que les cellules qui intersectent le carré englobant — au plus 9 cellules
    au lieu de la totalité des entités.
    """

    def __init__(self, cell_size: float) -> None:
        self.cell_size = max(cell_size, 1.0)
        self._cells: dict = {}

    def clear(self) -> None:
        self._cells.clear()

    def insert(self, entity) -> None:
        key = (int(entity.x / self.cell_size), int(entity.y / self.cell_size))
        if key not in self._cells:
            self._cells[key] = []
        self._cells[key].append(entity)

    def query(self, x: float, y: float, radius: float) -> list:
        """Retourne toutes les entités dont la cellule intersecte le carré
        englobant le cercle de centre (x, y) et de rayon radius."""
        c0 = int((x - radius) / self.cell_size)
        c1 = int((x + radius) / self.cell_size)
        r0 = int((y - radius) / self.cell_size)
        r1 = int((y + radius) / self.cell_size)
        result = []
        for c in range(c0, c1 + 1):
            for r in range(r0, r1 + 1):
                bucket = self._cells.get((c, r))
                if bucket:
                    result.extend(bucket)
        return result

    def query_radius(self, x: float, y: float, radius: float) -> list:
        """Comme query() mais filtre exactement dans le cercle (pas la bounding box)."""
        candidates = self.query(x, y, radius)
        r2 = radius * radius
        return [e for e in candidates if (e.x - x) ** 2 + (e.y - y) ** 2 <= r2]
