"""
Structure of Arrays (SoA) maintenue en parallèle des listes d'entités.

Étape 1 du plan de vectorisation (TODO.txt → PERF). Ce module fournit une
représentation NumPy de l'état des individus et des plantes — `x`, `y`,
`energy`, `age`, `alive` (bool), `species_id` (int32). À ce stade, AUCUNE
logique métier ne lit depuis la SoA : c'est uniquement un miroir destiné
à valider l'invariant de synchronisation avant qu'on vectorise tour à tour
les calculs du hot path (spatial_grid.query, _check_environment, etc.).

Usage :
    arr = StateArrays()
    arr.sync_from(engine.individuals, engine.plants)
    # arr.ind_x, arr.ind_y, arr.ind_energy, arr.ind_alive, arr.ind_species_id
    # arr.plant_x, arr.plant_y, arr.plant_energy, arr.plant_alive, arr.plant_species_id

Le mapping nom → species_id est stable au sein d'une instance (un nouveau
nom rencontré → nouvel id). Pour réinitialiser, créer une nouvelle instance.
"""
from __future__ import annotations

import numpy as np


class StateArrays:
    """Vue NumPy synchronisée des entités vivantes du moteur."""

    def __init__(self) -> None:
        # Animaux (Individual)
        self.ind_x:          np.ndarray = np.empty(0, dtype=np.float64)
        self.ind_y:          np.ndarray = np.empty(0, dtype=np.float64)
        self.ind_energy:     np.ndarray = np.empty(0, dtype=np.float64)
        self.ind_age:        np.ndarray = np.empty(0, dtype=np.int32)
        self.ind_alive:      np.ndarray = np.empty(0, dtype=bool)
        self.ind_species_id: np.ndarray = np.empty(0, dtype=np.int32)

        # Plantes
        self.plant_x:          np.ndarray = np.empty(0, dtype=np.float64)
        self.plant_y:          np.ndarray = np.empty(0, dtype=np.float64)
        self.plant_energy:     np.ndarray = np.empty(0, dtype=np.float64)
        self.plant_age:        np.ndarray = np.empty(0, dtype=np.int32)
        self.plant_alive:      np.ndarray = np.empty(0, dtype=bool)
        self.plant_species_id: np.ndarray = np.empty(0, dtype=np.int32)

        # Mapping nom d'espèce → id int32 stable (croissant au fil des rencontres).
        self._species_id: dict[str, int] = {}

    # ── Mapping species_id ────────────────────────────────────────────────────

    def species_id_for(self, name: str) -> int:
        sid = self._species_id.get(name)
        if sid is None:
            sid = len(self._species_id)
            self._species_id[name] = sid
        return sid

    @property
    def species_ids(self) -> dict[str, int]:
        return dict(self._species_id)

    # ── Synchronisation ───────────────────────────────────────────────────────

    def sync_from(self, individuals: list, plants: list) -> None:
        """Reconstruit les tableaux depuis les listes courantes du moteur.

        On reconstruit à chaque appel plutôt que d'essayer un append/remove
        incrémental — c'est ce que tous les pas vectorisés futurs feront
        de toute façon, et c'est trivialement correct.
        """
        n_ind = len(individuals)
        if n_ind != self.ind_x.size:
            self.ind_x          = np.empty(n_ind, dtype=np.float64)
            self.ind_y          = np.empty(n_ind, dtype=np.float64)
            self.ind_energy     = np.empty(n_ind, dtype=np.float64)
            self.ind_age        = np.empty(n_ind, dtype=np.int32)
            self.ind_alive      = np.empty(n_ind, dtype=bool)
            self.ind_species_id = np.empty(n_ind, dtype=np.int32)

        for i, ind in enumerate(individuals):
            self.ind_x[i]          = ind.x
            self.ind_y[i]          = ind.y
            self.ind_energy[i]     = ind.energy
            self.ind_age[i]        = ind.age
            self.ind_alive[i]      = ind.alive
            self.ind_species_id[i] = self.species_id_for(ind.species.name)

        n_plant = len(plants)
        if n_plant != self.plant_x.size:
            self.plant_x          = np.empty(n_plant, dtype=np.float64)
            self.plant_y          = np.empty(n_plant, dtype=np.float64)
            self.plant_energy     = np.empty(n_plant, dtype=np.float64)
            self.plant_age        = np.empty(n_plant, dtype=np.int32)
            self.plant_alive      = np.empty(n_plant, dtype=bool)
            self.plant_species_id = np.empty(n_plant, dtype=np.int32)

        for i, p in enumerate(plants):
            self.plant_x[i]          = p.x
            self.plant_y[i]          = p.y
            self.plant_energy[i]     = p.energy
            self.plant_age[i]        = p.age
            self.plant_alive[i]      = p.alive
            self.plant_species_id[i] = self.species_id_for(p.species.name)

    # ── Vérif d'invariant (réservée aux tests) ───────────────────────────────

    def assert_matches(self, individuals: list, plants: list) -> None:
        """Lève AssertionError si la SoA ne reflète pas exactement les listes."""
        assert self.ind_x.size == len(individuals), (
            f"ind_x.size={self.ind_x.size} but len(individuals)={len(individuals)}"
        )
        for i, ind in enumerate(individuals):
            assert self.ind_x[i] == ind.x, f"ind_x[{i}]={self.ind_x[i]} != {ind.x}"
            assert self.ind_y[i] == ind.y, f"ind_y[{i}]={self.ind_y[i]} != {ind.y}"
            assert self.ind_energy[i] == ind.energy, (
                f"ind_energy[{i}]={self.ind_energy[i]} != {ind.energy}"
            )
            assert self.ind_age[i] == ind.age, f"ind_age[{i}]={self.ind_age[i]} != {ind.age}"
            assert bool(self.ind_alive[i]) == ind.alive, (
                f"ind_alive[{i}]={self.ind_alive[i]} != {ind.alive}"
            )
            assert self.ind_species_id[i] == self._species_id[ind.species.name]

        assert self.plant_x.size == len(plants)
        for i, p in enumerate(plants):
            assert self.plant_x[i] == p.x
            assert self.plant_y[i] == p.y
            assert self.plant_energy[i] == p.energy
            assert self.plant_age[i] == p.age
            assert bool(self.plant_alive[i]) == p.alive
            assert self.plant_species_id[i] == self._species_id[p.species.name]
