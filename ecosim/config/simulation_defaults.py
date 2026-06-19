"""
Constantes globales de la simulation — source unique de vérité.
Importez depuis ce module plutôt que de dupliquer dans chaque fichier.
"""

from ecosim.engine.engine_const import DAY_LENGTH, SIM_YEAR  # noqa: F401 — ré-export
from ecosim.entities.genetics import GENE_INFLUENCE, N_GENES  # noqa: F401 — ré-export

# ── Rendu web ─────────────────────────────────────────────────────────────────
RENDER_W: int = 700
RENDER_H: int = 560
