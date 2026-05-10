"""
Métriques de génétique des populations pour EcoSim.

Fonctions utilisables en post-traitement (depuis un .db) ou en live
sur une liste d'Individual.

Références :
  - Nei, M. (1973). Analysis of gene diversity in subdivided populations.
  - Wright, S. (1951). The genetical structure of populations.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence


# ── Helpers ────────────────────────────────────────────────────────────────────

def _allele_freqs(values: list[float], n_bins: int = 10) -> list[float]:
    """Discrétise les valeurs continues [-1,1] en n_bins classes d'allèles
    et retourne les fréquences relatives (somme = 1)."""
    counts = [0] * n_bins
    for v in values:
        idx = min(n_bins - 1, int((v + 1.0) / 2.0 * n_bins))
        counts[idx] += 1
    total = sum(counts)
    return [c / total for c in counts] if total else [1.0 / n_bins] * n_bins


def _shannon(freqs: list[float]) -> float:
    return -sum(p * math.log(p + 1e-12) for p in freqs if p > 0)


# ── Métriques individuelles / population ──────────────────────────────────────

def heterozygosity_expected(genomes: list) -> float:
    """He = 1 - Σ(pi²) moyenné sur tous les loci.

    Calculé sur les gènes neutres pour éviter le biais de sélection.
    """
    if not genomes:
        return 0.0
    n_loci = len(genomes[0].neutral_genes)
    he_sum = 0.0
    for locus in range(n_loci):
        vals  = [g.neutral_genes[locus] for g in genomes]
        freqs = _allele_freqs(vals)
        he_sum += 1.0 - sum(p * p for p in freqs)
    return he_sum / n_loci if n_loci else 0.0


def nucleotide_diversity(genomes: list) -> float:
    """π = diversité nucléotidique : distance génomique moyenne entre paires.

    Utilise les gènes fonctionnels + neutres.
    """
    if len(genomes) < 2:
        return 0.0
    n = len(genomes)
    total_dist = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            g1, g2 = genomes[i], genomes[j]
            all_genes_1 = g1.genes + g1.neutral_genes
            all_genes_2 = g2.genes + g2.neutral_genes
            dist = sum((a - b) ** 2 for a, b in zip(all_genes_1, all_genes_2))
            total_dist += math.sqrt(dist / len(all_genes_1))
            count += 1
    return total_dist / count if count else 0.0


def fst(pop_a: list, pop_b: list) -> float:
    """Fst de Wright entre deux groupes (basé sur la variance des fréquences alléliques).

    Utilise les gènes neutres. Fst = 0 → populations identiques,
    Fst = 1 → populations complètement différenciées.
    """
    if not pop_a or not pop_b:
        return 0.0
    n_loci = len(pop_a[0].neutral_genes)
    fst_sum = 0.0
    for locus in range(n_loci):
        va = [g.neutral_genes[locus] for g in pop_a]
        vb = [g.neutral_genes[locus] for g in pop_b]
        fa = _allele_freqs(va)
        fb = _allele_freqs(vb)
        # Fréquences agrégées (taille égale)
        f_total = [(a + b) / 2.0 for a, b in zip(fa, fb)]
        ht = 1.0 - sum(p * p for p in f_total)
        hs = 0.5 * (
            (1.0 - sum(p * p for p in fa)) +
            (1.0 - sum(p * p for p in fb))
        )
        if ht > 0:
            fst_sum += (ht - hs) / ht
    return fst_sum / n_loci if n_loci else 0.0


def effective_population_size(allele_freqs_t0: list[float],
                               allele_freqs_t1: list[float],
                               delta_t: int) -> float:
    """Ne estimé par la méthode de la variance temporelle des fréquences alléliques.

    delta_t : nombre de générations entre t0 et t1.
    Retourne Ne ou inf si la dérive est nulle.
    """
    if delta_t <= 0:
        return float("inf")
    # Variance de Fc (Waples 1989)
    fc_vals = []
    for p0, p1 in zip(allele_freqs_t0, allele_freqs_t1):
        if 0 < p0 < 1 and 0 < p1 < 1:
            fc = (p1 - p0) ** 2 / ((p0 + p1) / 2 * (1 - (p0 + p1) / 2) + 1e-9)
            fc_vals.append(fc)
    if not fc_vals:
        return float("inf")
    fc_mean = sum(fc_vals) / len(fc_vals)
    if fc_mean <= 0:
        return float("inf")
    ne = delta_t / (2.0 * fc_mean)
    return ne


# ── Interface haut niveau depuis un .db ───────────────────────────────────────

def compute_diversity_at_tick(db_path: Path, tick: int,
                               species: str | None = None) -> dict:
    """Calcule les métriques génétiques depuis une keyframe SQLite.

    Retourne un dict avec He, π, et Fst (si species=None, toutes espèces confondues).
    """
    from simulation.recording.replay import ReplayReader
    from entities.genetics import Genome

    reader = ReplayReader(db_path)
    snap   = reader.state_at(tick)
    reader.close()

    if snap is None:
        return {"error": "no snapshot"}

    inds = [e for e in snap.individuals if e.alive]
    if species:
        inds = [e for e in inds if e.species == species]

    genomes = []
    for e in inds:
        if e.genome_json:
            try:
                genomes.append(Genome.from_json(e.genome_json))
            except Exception:
                pass

    if not genomes:
        return {"n": 0, "He": 0.0, "pi": 0.0}

    return {
        "n":       len(genomes),
        "He":      round(heterozygosity_expected(genomes), 4),
        "pi":      round(nucleotide_diversity(genomes), 4),
        "species": species or "all",
        "tick":    tick,
    }


def compute_fst_spatial(db_path: Path, tick: int,
                         species: str, n_quadrants: int = 4) -> dict:
    """Fst entre quadrants spatiaux (nord-ouest, nord-est, sud-ouest, sud-est)."""
    from simulation.recording.replay import ReplayReader
    from entities.genetics import Genome

    reader  = ReplayReader(db_path)
    snap    = reader.state_at(tick)
    meta    = reader.meta
    reader.close()

    world_w = int(meta.get("world_width", 500))
    world_h = int(meta.get("world_height", 500))
    mid_x, mid_y = world_w / 2, world_h / 2

    groups: dict[str, list] = {"NW": [], "NE": [], "SW": [], "SE": []}
    for e in snap.individuals:
        if not e.alive or e.species != species or not e.genome_json:
            continue
        try:
            g = Genome.from_json(e.genome_json)
        except Exception:
            continue
        key = ("N" if e.y < mid_y else "S") + ("W" if e.x < mid_x else "E")
        groups[key].append(g)

    results = {}
    keys = [k for k, v in groups.items() if v]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ka, kb = keys[i], keys[j]
            results[f"Fst_{ka}_{kb}"] = round(fst(groups[ka], groups[kb]), 4)

    return {"tick": tick, "species": species, **results}
