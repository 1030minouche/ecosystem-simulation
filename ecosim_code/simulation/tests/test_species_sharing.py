"""
Invariant : un objet `Species` est partagé immuable.

Avant la suppression de `blend_species()`, chaque naissance créait
un nouvel objet Species (mesure d'audit du 12 juin 2026 : 554 objets
distincts pour 8 espèces vivantes après 1 200 ticks). Ce test
garantit que les bébés héritent du Species de leur parent par
référence et que la variation phénotypique passe désormais
exclusivement par le Genome.
"""
import pytest
from entities.animal import Individual
from entities.rng import rng
from helpers import MockGrid, make_animal_species


@pytest.fixture
def grid_50():
    """MockGrid 50×50 sans eau, plat, modéré."""
    g = MockGrid(width=50, height=50)
    g.soil_type[:, :] = "clay"
    g.water_depth[:, :] = 0.0
    g.altitude[:, :]    = 0.5
    g.temperature[:, :] = 20.0
    g.humidity[:, :]    = 0.5
    return g


def test_blend_species_is_gone():
    """Le symbole `blend_species` ne doit plus exister dans entities.species."""
    from entities import species as species_mod
    assert not hasattr(species_mod, "blend_species"), (
        "blend_species supprimé : toute variation passe par le Genome"
    )


def test_babies_share_parent_species_object(grid_50):
    """Après une naissance instantanée, le baby.species IS parent.species."""
    Individual._uid_counter = 0
    rng.reset(42)
    sp = make_animal_species(
        gestation_ticks=0,       # naissance instantanée
        reproduction_rate=1.0,
        sexual_maturity_ticks=0,
        litter_size_min=1,
        litter_size_max=3,
    )
    mom = Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                     sex="female", wander_angle=0.0,
                     home_x=25.0, home_y=25.0)
    dad = Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                     sex="male", wander_angle=0.0,
                     home_x=25.0, home_y=25.0)
    babies = mom._try_reproduce([mom, dad], grid_50, n_predators=0)
    assert len(babies) > 0, "Au moins un baby attendu avec reproduction_rate=1.0"
    for baby in babies:
        assert baby.species is sp, (
            "Baby doit pointer sur le MÊME objet Species, pas une copie"
        )


def test_species_object_count_stays_one_after_many_births(grid_50):
    """Après 10 naissances successives, il y a toujours 1 seul objet Species."""
    Individual._uid_counter = 0
    rng.reset(42)
    sp = make_animal_species(
        gestation_ticks=0,
        reproduction_rate=1.0,
        sexual_maturity_ticks=0,
        litter_size_min=1,
        litter_size_max=1,
        reproduction_cooldown_length=0,
    )
    pop = [
        Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                   sex="female", wander_angle=0.0, home_x=25.0, home_y=25.0),
        Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                   sex="male", wander_angle=0.0, home_x=25.0, home_y=25.0),
    ]
    for _ in range(10):
        babies = pop[0]._try_reproduce(pop, grid_50, n_predators=0)
        pop.extend(babies)

    distinct_species = {id(ind.species) for ind in pop}
    assert len(distinct_species) == 1, (
        f"Un seul objet Species attendu, trouvé {len(distinct_species)} — "
        "blend_species réintroduit ?"
    )


def test_babies_have_distinct_genomes(grid_50):
    """La variation passe désormais par le Genome : les babies héritent
    de génomes distincts (recombinaison mendélienne)."""
    Individual._uid_counter = 0
    rng.reset(42)
    sp = make_animal_species(
        gestation_ticks=0,
        reproduction_rate=1.0,
        sexual_maturity_ticks=0,
        litter_size_min=3,
        litter_size_max=3,
        mutation_rate=0.1,
    )
    mom = Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                     sex="female", wander_angle=0.0, home_x=25.0, home_y=25.0)
    dad = Individual(species=sp, x=25.0, y=25.0, energy=100.0,
                     sex="male", wander_angle=0.0, home_x=25.0, home_y=25.0)
    babies = mom._try_reproduce([mom, dad], grid_50, n_predators=0)
    assert len(babies) >= 2, "litter_size=3 attendu"
    # Au moins deux babies doivent avoir un génome distinct entre eux
    genomes = [tuple(b.genome.genes) for b in babies]
    assert len(set(genomes)) > 1 or len(babies) == 1, (
        "Les babies doivent avoir des génomes distincts (mendel + mutation)"
    )
