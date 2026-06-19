"""
Configuration pytest : ajoute la racine du dépôt et le dossier tests/
au sys.path pour que `import ecosim` et `from helpers import ...` marchent
quand on lance pytest depuis n'importe où.
"""
import os
import sys

_here = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_here, ".."))   # racine du dépôt → import ecosim
sys.path.insert(0, _here)                        # tests/ → from helpers import ...
