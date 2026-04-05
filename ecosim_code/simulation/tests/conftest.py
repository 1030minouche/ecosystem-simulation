"""
Configuration pytest : ajoute ecosim_code/simulation/ et tests/ au sys.path
pour que les imports (entities, world, simulation...) et (helpers) fonctionnent.
"""
import sys
import os

_here = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_here, ".."))   # simulation/
sys.path.insert(0, _here)                        # tests/
