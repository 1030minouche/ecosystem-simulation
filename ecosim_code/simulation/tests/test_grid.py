"""
Tests pour world/grid.py et world/cell.py
"""
import pytest
from world.grid import Grid
from world.cell import Cell


# ── Grid ─────────────────────────────────────────────────────────────────────

class TestGrid:

    def test_dimensions_stored_correctly(self):
        g = Grid(30, 20)
        assert g.width == 30
        assert g.height == 20

    def test_cells_array_shape(self):
        g = Grid(30, 20)
        assert len(g.cells) == 20           # height lignes
        assert len(g.cells[0]) == 30        # width colonnes

    def test_numpy_altitude_shape(self):
        g = Grid(15, 25)
        assert g.altitude.shape == (25, 15)

    def test_numpy_temperature_shape(self):
        g = Grid(15, 25)
        assert g.temperature.shape == (25, 15)

    def test_default_temperature(self):
        g = Grid(10, 10)
        assert g.temperature[5][5] == 15.0

    def test_default_altitude_zero(self):
        g = Grid(10, 10)
        assert g.altitude[0][0] == 0.0

    def test_get_cell_returns_cell_at_correct_position(self):
        g = Grid(10, 10)
        cell = g.get_cell(3, 7)
        assert cell.x == 3
        assert cell.y == 7

    def test_all_cells_are_cell_instances(self):
        g = Grid(5, 5)
        for row in g.cells:
            for cell in row:
                assert isinstance(cell, Cell)

    # ── get_neighbors ─────────────────────────────────────────────────────────

    def test_neighbors_center_has_eight(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(5, 5)) == 8

    def test_neighbors_top_left_corner_has_three(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(0, 0)) == 3

    def test_neighbors_top_right_corner_has_three(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(9, 0)) == 3

    def test_neighbors_bottom_left_corner_has_three(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(0, 9)) == 3

    def test_neighbors_bottom_right_corner_has_three(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(9, 9)) == 3

    def test_neighbors_left_edge_has_five(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(0, 5)) == 5

    def test_neighbors_top_edge_has_five(self):
        g = Grid(10, 10)
        assert len(g.get_neighbors(5, 0)) == 5

    def test_neighbors_cell_not_its_own_neighbor(self):
        g = Grid(10, 10)
        cell = g.get_cell(5, 5)
        neighbors = g.get_neighbors(5, 5)
        assert cell not in neighbors

    def test_neighbors_are_adjacent(self):
        g = Grid(10, 10)
        neighbors = g.get_neighbors(5, 5)
        for n in neighbors:
            assert abs(n.x - 5) <= 1
            assert abs(n.y - 5) <= 1

    def test_minimal_1x1_grid_has_no_neighbors(self):
        g = Grid(1, 1)
        assert len(g.get_neighbors(0, 0)) == 0


# ── Cell ──────────────────────────────────────────────────────────────────────

class TestCell:

    def test_cell_stores_position(self):
        c = Cell(x=3, y=7)
        assert c.x == 3
        assert c.y == 7

    def test_default_soil_type(self):
        c = Cell(0, 0)
        assert c.soil_type == "clay"

    def test_default_temperature(self):
        c = Cell(0, 0)
        assert c.temperature == 15.0

    def test_default_humidity(self):
        c = Cell(0, 0)
        assert c.humidity == 0.5

    def test_water_depth_default(self):
        c = Cell(0, 0)
        assert c.water_depth == 0.0
