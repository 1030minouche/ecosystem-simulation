"""
Tests pour entities/genetics.py
"""
import json
import pytest
from entities.genetics import Genome, N_GENES, GENE_INFLUENCE, GENE_TRAITS
from entities.rng import rng


class TestGenomeCreation:

    def test_random_genome_has_n_genes(self):
        rng.reset(42)
        g = Genome.random()
        assert len(g.genes) == N_GENES

    def test_random_genes_in_range(self):
        rng.reset(1)
        g = Genome.random()
        for gene in g.genes:
            assert -1.0 <= gene <= 1.0

    def test_default_genome_all_zeros(self):
        g = Genome()
        assert all(v == 0.0 for v in g.genes)


class TestRecombination:

    def test_child_genes_come_from_parents(self):
        rng.reset(0)
        pa = Genome(genes=[1.0] * N_GENES)
        pb = Genome(genes=[-1.0] * N_GENES)
        child = Genome.from_parents(pa, pb, mutation_rate=0.0)
        for gene in child.genes:
            assert gene in (1.0, -1.0)

    def test_mutation_rate_zero_is_exact_copy(self):
        rng.reset(7)
        pa = Genome.random()
        pb = Genome.random()
        children = [Genome.from_parents(pa, pb, mutation_rate=0.0) for _ in range(20)]
        for child in children:
            for gene, a, b in zip(child.genes, pa.genes, pb.genes):
                assert gene == a or gene == b

    def test_mutation_rate_one_modifies_all_genes(self):
        rng.reset(99)
        pa = Genome(genes=[0.0] * N_GENES)
        pb = Genome(genes=[0.0] * N_GENES)
        child = Genome.from_parents(pa, pb, mutation_rate=1.0)
        changed = sum(abs(g) > 1e-10 for g in child.genes)
        assert changed > 0

    def test_mutated_genes_stay_in_range(self):
        rng.reset(42)
        pa = Genome(genes=[1.0] * N_GENES)
        pb = Genome(genes=[1.0] * N_GENES)
        for _ in range(50):
            child = Genome.from_parents(pa, pb, mutation_rate=1.0)
            for gene in child.genes:
                assert -1.0 <= gene <= 1.0


class TestApplyToParams:

    def test_positive_gene_increases_param(self):
        g = Genome(genes=[1.0] + [0.0] * (N_GENES - 1))
        base = {"max_speed": 10.0}
        result = g.apply_to_params(base)
        assert result["max_speed"] > 10.0

    def test_negative_gene_decreases_param(self):
        g = Genome(genes=[-1.0] + [0.0] * (N_GENES - 1))
        base = {"max_speed": 10.0}
        result = g.apply_to_params(base)
        assert result["max_speed"] < 10.0

    def test_influence_respects_bound(self):
        g = Genome(genes=[1.0] * N_GENES)
        base = {t: 100.0 for t in GENE_TRAITS}
        result = g.apply_to_params(base)
        for trait in GENE_TRAITS:
            expected = 100.0 * (1.0 + GENE_INFLUENCE)
            assert abs(result[trait] - expected) < 1e-9

    def test_zero_gene_unchanged(self):
        g = Genome(genes=[0.0] * N_GENES)
        base = {"max_speed": 5.0}
        result = g.apply_to_params(base)
        assert result["max_speed"] == 5.0

    def test_unknown_trait_ignored(self):
        g = Genome()
        base = {"unknown_trait": 42.0}
        result = g.apply_to_params(base)
        assert result["unknown_trait"] == 42.0


class TestGeneticDistance:

    def test_distance_with_itself_is_zero(self):
        rng.reset(5)
        g = Genome.random()
        assert g.genetic_distance(g) == 0.0

    def test_distance_symmetric(self):
        rng.reset(3)
        a = Genome.random()
        b = Genome.random()
        assert abs(a.genetic_distance(b) - b.genetic_distance(a)) < 1e-10

    def test_distance_bounded_between_0_and_1(self):
        rng.reset(11)
        a = Genome.random()
        b = Genome.random()
        d = a.genetic_distance(b)
        assert 0.0 <= d <= 1.0


class TestSerialization:

    def test_to_json_from_json_roundtrip(self):
        rng.reset(20)
        g = Genome.random()
        restored = Genome.from_json(g.to_json())
        assert restored.genes == g.genes

    def test_to_list_from_list_roundtrip(self):
        rng.reset(21)
        g = Genome.random()
        restored = Genome.from_list(g.to_list())
        assert restored.genes == g.genes

    def test_to_json_is_valid_json(self):
        rng.reset(22)
        g = Genome.random()
        parsed = json.loads(g.to_json())
        # Format actuel : {"g": [...], "n": [...]}
        assert isinstance(parsed, dict)
        assert "g" in parsed and "n" in parsed
        assert len(parsed["g"]) == N_GENES
