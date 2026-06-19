"""
Constantes globales de la simulation — source unique de vérité.
Importez depuis ce module plutôt que de dupliquer dans chaque fichier.
"""

# ── Temps ─────────────────────────────────────────────────────────────────────
from engine.engine_const import DAY_LENGTH, SIM_YEAR  # noqa: F401 — ré-export

# ── Rendu web ─────────────────────────────────────────────────────────────────
RENDER_W: int = 700
RENDER_H: int = 560

# ── Génétique ────────────────────────────────────────────────────────────────
from entities.genetics import N_GENES, GENE_INFLUENCE  # noqa: F401 — ré-export
