"""
Système de génétique simple pour EcoSim.
Un génome = vecteur de N_GENES flottants dans [-1.0, 1.0].
Chaque gène module un paramètre phénotypique de l'espèce.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from entities.rng import rng

# circular-import-guard: Species uses genetics.Genome; genetics references Species for hints only.
if TYPE_CHECKING:
    from entities.species import Species

N_GENES         = 8   # gènes à effet phénotypique
N_NEUTRAL_GENES = 20  # gènes neutres (sans effet, pour mesurer la dérive)

# Mapping indice → paramètre modulé (facteur : base × (1 + gene × GENE_INFLUENCE))
GENE_TRAITS = [
    "max_speed",           # 0
    "max_energy",          # 1
    "energy_per_food",     # 2
    "reproduction_rate",   # 3
    "perception_radius",   # 4
    "aggression",          # 5
    "disease_resistance",  # 6
    "longevity",           # 7
]

GENE_INFLUENCE = 0.30


_TOTAL_GENES = N_GENES + N_NEUTRAL_GENES


@dataclass
class Genome:
    genes:         list[float] = field(default_factory=lambda: [0.0] * N_GENES)
    neutral_genes: list[float] = field(default_factory=lambda: [0.0] * N_NEUTRAL_GENES)

    @classmethod
    def random(cls) -> "Genome":
        return cls(
            genes         = [rng.uniform(-1.0, 1.0) for _ in range(N_GENES)],
            neutral_genes = [rng.uniform(-1.0, 1.0) for _ in range(N_NEUTRAL_GENES)],
        )

    @classmethod
    def from_parents(cls, parent_a: "Genome", parent_b: "Genome",
                     mutation_rate: float) -> "Genome":
        """Recombinaison mendélienne uniforme + mutation gaussienne."""
        child_genes = []
        for a, b in zip(parent_a.genes, parent_b.genes):
            gene = a if rng.random() < 0.5 else b
            if rng.random() < mutation_rate:
                gene += rng.gauss(0.0, 0.15)
                gene = max(-1.0, min(1.0, gene))
            child_genes.append(gene)
        # Gènes neutres : même recombinaison, mutation légèrement plus élevée
        child_neutral = []
        for a, b in zip(parent_a.neutral_genes, parent_b.neutral_genes):
            gene = a if rng.random() < 0.5 else b
            if rng.random() < mutation_rate * 1.5:
                gene += rng.gauss(0.0, 0.10)
                gene = max(-1.0, min(1.0, gene))
            child_neutral.append(gene)
        return cls(genes=child_genes, neutral_genes=child_neutral)

    def apply_to_params(self, base_params: dict) -> dict:
        """Retourne une copie des params avec les modifications génétiques."""
        params = dict(base_params)
        for i, trait in enumerate(GENE_TRAITS):
            if trait in params:
                factor = 1.0 + self.genes[i] * GENE_INFLUENCE
                params[trait] = params[trait] * factor
        return params

    def genetic_distance(self, other: "Genome") -> float:
        """Distance euclidienne normalisée entre deux génomes (0=identique, 1=max)."""
        diffs = [(a - b) ** 2 for a, b in zip(self.genes, other.genes)]
        return (sum(diffs) / N_GENES) ** 0.5 / (2 ** 0.5)

    def to_list(self) -> list[float]:
        return list(self.genes)

    @classmethod
    def from_list(cls, lst: list[float]) -> "Genome":
        return cls(genes=list(lst))

    def to_json(self) -> str:
        return json.dumps({"g": self.genes, "n": self.neutral_genes})

    @classmethod
    def from_json(cls, s: str) -> "Genome":
        if not s:
            return cls.random()
        data = json.loads(s)
        if isinstance(data, list):
            # rétrocompatibilité : ancien format sans gènes neutres
            return cls(genes=data,
                       neutral_genes=[0.0] * N_NEUTRAL_GENES)
        return cls(
            genes         = data.get("g", [0.0] * N_GENES),
            neutral_genes = data.get("n", [0.0] * N_NEUTRAL_GENES),
        )
