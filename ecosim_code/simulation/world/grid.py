import numpy as np
from world.cell import Cell


class _CellView:
    """Vue légère (property-based) sur les tableaux numpy d'une cellule."""
    __slots__ = ("_g", "_x", "_y")

    def __init__(self, grid: "Grid", x: int, y: int):
        self._g, self._x, self._y = grid, x, y

    @property
    def soil_type(self) -> str:
        return self._g.soil_type[self._y, self._x]

    @property
    def temperature(self) -> float:
        return float(self._g.temperature[self._y, self._x])

    @property
    def humidity(self) -> float:
        return float(self._g.humidity[self._y, self._x])

    @property
    def altitude(self) -> float:
        return float(self._g.altitude[self._y, self._x])

    @property
    def water_depth(self) -> float:
        return float(self._g.water_depth[self._y, self._x])


class Grid:
    def __init__(self, width: int, height: int):
        self.width  = width
        self.height = height

        # Tableaux NumPy — source de vérité unique pour l'état du terrain
        self.altitude    = np.zeros((height, width))
        self.temperature = np.full((height, width), 15.0)
        self.humidity    = np.zeros((height, width))
        self.water_depth = np.zeros((height, width))
        self.soil_type   = np.full((height, width), "clay", dtype=object)

        # Grille d'objets Cell — conservée pour les accès legacy (éditeur de terrain)
        self.cells = [[Cell(x, y) for x in range(width)]
                                  for y in range(height)]

    def cell_view(self, x: int, y: int) -> _CellView:
        """Retourne une vue légère (property-based) sur la cellule (x, y)."""
        return _CellView(self, x, y)

    def get_cell(self, x: int, y: int) -> Cell:
        return self.cells[y][x]

    def nearest_non_water(self, cx: int, cy: int, max_radius: int) -> tuple[int, int] | None:
        """Retourne la cellule non-eau la plus proche dans un rayon donné."""
        best_x, best_y, best_d2 = -1, -1, float("inf")
        for dy in range(-max_radius, max_radius + 1):
            for dx in range(-max_radius, max_radius + 1):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                if self.soil_type[ny, nx] == "water":
                    continue
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2 = d2
                    best_x, best_y = nx, ny
        return (best_x, best_y) if best_x >= 0 else None

    def get_neighbors(self, x: int, y: int) -> list:
        neighbors = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    neighbors.append(self.cells[ny][nx])
        return neighbors
