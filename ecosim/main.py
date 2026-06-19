"""
EcoSim — point d'entrée CLI.

Usage:
  ecosim                                          # Interface web localhost:9000
  ecosim --headless --ticks N                     # Mode headless CLI
  ecosim --headless --ticks N --time-acceleration 10
                                                  # Biologie 10x plus rapide
  ecosim --port 8765                              # Port custom
  ecosim --purge-runs --keep 5                    # Nettoie runs/ (garde 5 derniers)

Alternative sans entry-point installé : `python -m ecosim ...`.
"""
import argparse
import logging
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ecosim", description="EcoSim — simulateur d'écosystème")
    p.add_argument("--headless",    action="store_true")
    p.add_argument("--ticks",       type=int,  default=10000)
    p.add_argument("--seed",        type=int,  default=None)
    p.add_argument("--out",         type=str,  default=None)
    p.add_argument("--config",      type=str,  default=None)
    p.add_argument("--progress",    action="store_true")
    p.add_argument("--port",        type=int,  default=9000)
    p.add_argument("--purge-runs",  action="store_true",
                   help="Supprime les .db de runs/ sauf les N plus récents")
    p.add_argument("--keep",        type=int,  default=5,
                   help="Nombre de runs à conserver (utilisé avec --purge-runs)")
    p.add_argument("--time-acceleration", type=float, default=1.0,
                   help="Compresse les durées biologiques (max_age, gestation, "
                        "cooldowns) par ce facteur. 10.0 = cycles ~10x plus courts. "
                        "Défaut: 1.0 (pas d'accélération).")
    return p


def main(argv: list[str] | None = None) -> int:
    args, _ = _build_parser().parse_known_args(argv)

    if args.purge_runs:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        from ecosim.engine.maintenance import purge_runs
        kept, deleted = purge_runs("runs", keep=args.keep)
        print(f"[purge] gardés={kept}  supprimés={deleted}")
        return 0

    if args.headless:
        from ecosim.engine.headless import run_headless
        run_headless(
            ticks=args.ticks,
            seed=args.seed,
            config_path=args.config,
            out_path=args.out,
            progress=args.progress,
            time_acceleration=args.time_acceleration,
        )
        return 0

    # Default: web UI
    from ecosim.web.server import run as run_web
    run_web(port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
