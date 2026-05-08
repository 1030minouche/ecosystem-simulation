"""
Tests pour simulation/recording/resume.py — reprise de simulation.
"""
import tempfile
from pathlib import Path
import pytest

from world.grid import Grid
from simulation.engine import SimulationEngine
from simulation.runner import EngineRunner
from simulation.recording.recorder import Recorder
from simulation.recording.resume import load_engine_from_db
from entities.rng import rng


_HERBE = {
    "name": "Herbe", "type": "plant",
    "color": (0.2, 0.8, 0.1),
    "temp_min": 0.0, "temp_max": 40.0,
    "humidity_min": 0.0, "humidity_max": 1.0,
    "altitude_min": 0.0, "altitude_max": 1.0,
    "reproduction_rate": 0.8, "reproduction_rate_std": 0.0,
    "max_age": 876_000, "max_age_std": 0,
    "max_population": 10_000,
    "energy_start": 100.0, "energy_start_std": 0.0,
    "energy_consumption": 0.0, "energy_consumption_std": 0.0,
    "energy_from_food": 0.0, "energy_from_food_std": 0.0,
    "speed": 0.0, "speed_std": 0.0,
    "perception_radius": 0.0, "perception_radius_std": 0.0,
    "food_sources": [],
    "growth_rate": 3e-5, "growth_rate_std": 0.0,
    "dispersal_radius": 6,
    "activity_pattern": "diurnal",
    "can_swim": False,
    "reproduction_cooldown_length": 1200, "reproduction_cooldown_length_std": 0,
    "litter_size_min": 1, "litter_size_max": 4,
    "sexual_maturity_ticks": 0, "sexual_maturity_ticks_std": 0,
    "gestation_ticks": 0, "gestation_ticks_std": 0,
    "juvenile_mortality_rate": 0.0, "juvenile_mortality_rate_std": 0.0,
    "fear_factor": 0.0, "fear_factor_std": 0.0,
}

_LAPIN = {
    "name": "Lapin", "type": "herbivore",
    "color": (0.9, 0.9, 0.8),
    "temp_min": 0.0, "temp_max": 40.0,
    "humidity_min": 0.0, "humidity_max": 1.0,
    "altitude_min": 0.0, "altitude_max": 1.0,
    "reproduction_rate": 0.9, "reproduction_rate_std": 0.0,
    "max_age": 1_314_000, "max_age_std": 0,
    "max_population": 200,
    "energy_start": 100.0, "energy_start_std": 0.0,
    "energy_consumption": 0.05, "energy_consumption_std": 0.0,
    "energy_from_food": 65.0, "energy_from_food_std": 0.0,
    "speed": 1.2, "speed_std": 0.0,
    "perception_radius": 12.0, "perception_radius_std": 0.0,
    "food_sources": ["Herbe"],
    "growth_rate": 0.0, "growth_rate_std": 0.0,
    "dispersal_radius": 0,
    "activity_pattern": "crepuscular",
    "can_swim": False,
    "reproduction_cooldown_length": 61_200, "reproduction_cooldown_length_std": 0,
    "litter_size_min": 3, "litter_size_max": 8,
    "sexual_maturity_ticks": 10_000, "sexual_maturity_ticks_std": 0,
    "gestation_ticks": 1_000, "gestation_ticks_std": 0,
    "juvenile_mortality_rate": 1.28e-5, "juvenile_mortality_rate_std": 0.0,
    "fear_factor": 3.0, "fear_factor_std": 0.0,
    "mutation_rate": 0.05,
}


def _make_engine(seed=42):
    rng.reset(seed)
    g = Grid(40, 40)
    g.soil_type[:] = "clay"
    g.temperature[:] = 20.0
    g.humidity[:] = 0.5
    g.altitude[:] = 0.5
    engine = SimulationEngine(g, seed=seed)
    engine.add_species(_HERBE, count=20)
    engine.add_species(_LAPIN, count=10)
    return engine


class TestResume:

    def test_tick_count_continues_from_saved_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sim.db"
            engine = _make_engine()
            kf = 10
            recorder = Recorder(db, keyframe_every=kf)
            recorder.write_engine_meta(engine)
            recorder.write_species_params(engine.species_list)
            runner = EngineRunner(engine, recorder=recorder)
            runner.run(max_ticks=100)
            saved_tick = engine.tick_count
            recorder.close()

            engine2 = load_engine_from_db(db)
            # La dernière keyframe est au plus kf ticks avant la fin
            assert engine2.tick_count <= saved_tick
            assert engine2.tick_count >= saved_tick - kf

    def test_continued_simulation_tick_count_reaches_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sim.db"
            engine = _make_engine()
            kf = 10
            recorder = Recorder(db, keyframe_every=kf)
            recorder.write_engine_meta(engine)
            recorder.write_species_params(engine.species_list)
            runner = EngineRunner(engine, recorder=recorder)
            runner.run(max_ticks=100)
            recorder.close()

            engine2 = load_engine_from_db(db)
            resume_tick = engine2.tick_count
            recorder2 = Recorder(db, keyframe_every=kf, append=True)
            runner2 = EngineRunner(engine2, recorder=recorder2)
            runner2.run(max_ticks=100)
            recorder2.close()

            assert engine2.tick_count == resume_tick + 100

    def test_resumed_populations_are_plausible(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sim.db"
            engine = _make_engine()
            recorder = Recorder(db, keyframe_every=10)
            recorder.write_engine_meta(engine)
            recorder.write_species_params(engine.species_list)
            runner = EngineRunner(engine, recorder=recorder)
            runner.run(max_ticks=100)
            recorder.close()

            engine2 = load_engine_from_db(db)
            total = len(engine2.plants) + len(engine2.individuals)
            assert total > 0

    def test_new_keyframe_appended_not_overwritten(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sim.db"
            engine = _make_engine()
            recorder = Recorder(db, keyframe_every=10)
            recorder.write_engine_meta(engine)
            recorder.write_species_params(engine.species_list)
            runner = EngineRunner(engine, recorder=recorder)
            runner.run(max_ticks=50)
            recorder.close()

            conn = sqlite3.connect(str(db))
            ticks_before = set(r[0] for r in conn.execute("SELECT tick FROM keyframes"))
            conn.close()

            engine2 = load_engine_from_db(db)
            recorder2 = Recorder(db, keyframe_every=10, append=True)
            runner2 = EngineRunner(engine2, recorder=recorder2)
            runner2.run(max_ticks=50)
            recorder2.close()

            conn = sqlite3.connect(str(db))
            ticks_after = set(r[0] for r in conn.execute("SELECT tick FROM keyframes"))
            conn.close()

            assert ticks_before.issubset(ticks_after)
            assert len(ticks_after) >= len(ticks_before)
