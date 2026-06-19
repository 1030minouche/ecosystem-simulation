"""Tests pour research/analysis/genetics_metrics.py — Fst, He, π, Ne.

Tests structurels (les valeurs reflètent les définitions, pas des constantes
arbitraires). Construit des populations synthétiques sans toucher au moteur.
"""
import math

import pytest

from ecosim.entities.genetics import Genome
from ecosim.entities.rng import rng
from ecosim.research.analysis.genetics_metrics import (
    effective_population_size,
    fst,
    heterozygosity_expected,
    nucleotide_diversity,
)


def _identical_pop(size: int = 10) -> list[Genome]:
    """Population où tous les individus partagent le même génome (He=0, π=0)."""
    rng.reset(0)
    g = Genome.random()
    return [g for _ in range(size)]


def _diverse_pop(size: int = 20, seed: int = 42) -> list[Genome]:
    """Population avec génomes aléatoires (He et π > 0)."""
    rng.reset(seed)
    return [Genome.random() for _ in range(size)]


# ── He (hétérozygotie attendue) ───────────────────────────────────────────────

def test_he_empty_population_returns_zero():
    assert heterozygosity_expected([]) == 0.0


def test_he_identical_population_is_zero():
    assert heterozygosity_expected(_identical_pop()) == 0.0


def test_he_diverse_population_is_positive():
    he = heterozygosity_expected(_diverse_pop())
    assert he > 0.0
    assert he <= 1.0


# ── π (nucleotide diversity) ──────────────────────────────────────────────────

def test_pi_singleton_is_zero():
    assert nucleotide_diversity(_diverse_pop(size=1)) == 0.0


def test_pi_identical_population_is_zero():
    assert nucleotide_diversity(_identical_pop()) == 0.0


def test_pi_diverse_population_is_positive():
    assert nucleotide_diversity(_diverse_pop()) > 0.0


# ── Fst ────────────────────────────────────────────────────────────────────────

def test_fst_two_empty_populations_is_zero():
    assert fst([], []) == 0.0


def test_fst_identical_populations_is_zero():
    """Fst entre deux échantillons de la même distribution → ~0."""
    pop_a = _diverse_pop(size=50, seed=10)
    pop_b = _diverse_pop(size=50, seed=10)  # même seed → mêmes génomes
    assert fst(pop_a, pop_b) == pytest.approx(0.0, abs=1e-9)


def test_fst_disjoint_populations_is_positive():
    """Fst entre deux populations divergentes (seeds différentes) > 0."""
    pop_a = _diverse_pop(size=50, seed=10)
    pop_b = _diverse_pop(size=50, seed=999)
    assert fst(pop_a, pop_b) > 0.0


# ── Ne (effective population size) ────────────────────────────────────────────

def test_ne_zero_delta_t_is_infinite():
    assert effective_population_size([0.5], [0.5], delta_t=0) == math.inf


def test_ne_no_drift_is_infinite():
    """Si les fréquences n'ont pas changé entre t0 et t1, Ne = ∞."""
    freqs = [0.3, 0.7]
    assert effective_population_size(freqs, freqs, delta_t=10) == math.inf


def test_ne_with_drift_is_finite_and_positive():
    """Avec une dérive non nulle, Ne doit être fini et > 0."""
    ne = effective_population_size([0.5, 0.5], [0.6, 0.4], delta_t=10)
    assert math.isfinite(ne)
    assert ne > 0
