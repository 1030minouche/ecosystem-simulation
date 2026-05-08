"""
Validation du dictionnaire config avant démarrage de la simulation.
"""
from __future__ import annotations

from pathlib import Path


def validate_config(config: dict) -> list[str]:
    """
    Valide config et retourne une liste d'erreurs lisibles (vide = OK).
    """
    errors: list[str] = []

    grid_size = config.get("grid_size", 0)
    if not isinstance(grid_size, int) or not (20 <= grid_size <= 500):
        errors.append(f"grid_size doit être un entier entre 20 et 500 (reçu : {grid_size!r})")

    ticks = config.get("ticks", 0)
    if not isinstance(ticks, int) or ticks <= 0:
        errors.append(f"ticks doit être un entier > 0 (reçu : {ticks!r})")

    species = config.get("species", [])
    enabled = [s for s in species if s.get("enabled", True)]
    if not enabled:
        errors.append("Au moins une espèce doit être activée")

    out_path = config.get("out_path", "")
    if out_path:
        p = Path(out_path)
        if p.suffix.lower() != ".db":
            errors.append(f"out_path doit avoir l'extension .db (reçu : {out_path!r})")
        if not p.parent.exists() and not p.parent == Path("."):
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(f"Impossible de créer le dossier de sortie : {exc}")

    return errors
