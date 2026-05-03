"""
Tests pour monitoring/death_log.py — vérification de cause_counts.
"""
import types
import pytest
from monitoring.death_log import DeathLogger


def _make_mock_ind(cause: str) -> types.SimpleNamespace:
    species = types.SimpleNamespace(name="TestSpecies")
    return types.SimpleNamespace(
        species=species,
        age=10,
        energy=5.0,
        x=5.0,
        y=5.0,
        death_cause=cause,
        death_state="wander",
        death_tod=0.5,
        death_is_night=False,
        death_on_water=False,
    )


@pytest.fixture
def death_log():
    dl = DeathLogger()
    yield dl
    dl.close()


class TestDeathLog:

    def test_predation_increments_cause_counts(self, death_log):
        """Après une mort par prédation, cause_counts['predation'] == 1."""
        death_log.record(_make_mock_ind("predation"), tick=1)
        assert death_log.cause_counts.get("predation", 0) == 1

    def test_famine_jour_increments_cause_counts(self, death_log):
        """Après une mort par famine de jour, cause_counts['famine_jour'] == 1."""
        death_log.record(_make_mock_ind("famine_jour"), tick=1)
        assert death_log.cause_counts.get("famine_jour", 0) == 1

    def test_famine_nuit_increments_cause_counts(self, death_log):
        """Après une mort par famine de nuit, cause_counts['famine_nuit'] == 1."""
        death_log.record(_make_mock_ind("famine_nuit"), tick=1)
        assert death_log.cause_counts.get("famine_nuit", 0) == 1

    def test_multiple_deaths_accumulate(self, death_log):
        """Plusieurs morts s'accumulent correctement dans cause_counts."""
        for _ in range(3):
            death_log.record(_make_mock_ind("predation"), tick=1)
        death_log.record(_make_mock_ind("famine_jour"), tick=2)
        assert death_log.cause_counts["predation"] == 3
        assert death_log.cause_counts["famine_jour"] == 1

    def test_cause_counts_starts_empty(self):
        """cause_counts est vide à l'initialisation."""
        dl = DeathLogger()
        assert dl.cause_counts == {}
        dl.close()
