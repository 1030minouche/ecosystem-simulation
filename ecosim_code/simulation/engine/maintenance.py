"""Petits utilitaires de maintenance du dépôt : purge des runs, etc."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def purge_runs(runs_dir: Path | str = "runs", *, keep: int = 5) -> tuple[int, int]:
    """
    Supprime les `.db` de `runs/` en conservant les `keep` plus récents
    (mtime décroissant). Retourne (kept, deleted).
    """
    runs = Path(runs_dir)
    if not runs.exists():
        logger.info("purge_runs: %s n'existe pas, rien à faire", runs)
        return (0, 0)

    dbs = sorted(runs.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    to_keep = dbs[:keep]
    to_delete = dbs[keep:]

    freed = 0
    for p in to_delete:
        size = p.stat().st_size
        try:
            p.unlink()
            freed += size
        except OSError as exc:
            logger.warning("purge_runs: impossible de supprimer %s (%s)", p, exc)

    if to_delete:
        logger.info(
            "purge_runs: gardés=%d  supprimés=%d  libérés=%.1f Mo",
            len(to_keep), len(to_delete), freed / (1024 * 1024),
        )
    else:
        logger.info("purge_runs: rien à supprimer (%d .db ≤ keep=%d)", len(dbs), keep)
    return (len(to_keep), len(to_delete))
