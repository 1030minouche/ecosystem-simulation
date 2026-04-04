import numpy as np
from world.cell import Cell

class Grid:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

        # Tableaux NumPy — pour les calculs physiques rapides sur tout le monde
        self.altitude    = np.zeros((height, width))
        self.temperature = np.full((height, width), 15.0)
        self.humidity    = np.zeros((height, width))
        self.water_depth = np.zeros((height, width))
        self.wind_vx     = np.zeros((height, width))
        self.wind_vy     = np.zeros((height, width))

        # Grille d'objets Cell — pour la logique biologique
        self.cells = [[Cell(x, y) for x in range(width)]
                                  for y in range(height)]

    def get_cell(self, x: int, y: int) -> Cell:
        return self.cells[y][x]

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