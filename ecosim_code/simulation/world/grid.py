import numpy as np
from world.cell import Cell


class Grid:
    def __init__(self, width: int, height: int):
        self.width  = width
        self.height = height

        # Tableaux NumPy — calculs vectorisés sur tout le terrain
        self.altitude    = np.zeros((height, width))
        self.temperature = np.full((height, width), 15.0)
        self.humidity    = np.zeros((height, width))
        self.water_depth = np.zeros((height, width))

        # Grille d'objets Cell — logique biologique (synchronisée par terrain.py)
        self.cells = [[Cell(x, y) for x in range(width)]
                                  for y in range(height)]

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
                if self.cells[ny][nx].soil_type == "water":
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
