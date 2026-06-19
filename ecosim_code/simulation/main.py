"""
EcoSim — point d'entrée.

Usage:
  python main.py                             # Interface web localhost:9000
  python main.py --headless --ticks N        # Mode headless CLI
  python main.py --port 8765                 # Port custom
  python main.py --purge-runs --keep 5       # Nettoie runs/ (garde 5 derniers)
"""
import argparse
import logging
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--headless",    action="store_true")
parser.add_argument("--ticks",       type=int,  default=10000)
parser.add_argument("--seed",        type=int,  default=None)
parser.add_argument("--out",         type=str,  default=None)
parser.add_argument("--config",      type=str,  default=None)
parser.add_argument("--progress",    action="store_true")
parser.add_argument("--port",        type=int,  default=9000)
parser.add_argument("--purge-runs",  action="store_true",
                    help="Supprime les .db de runs/ sauf les N plus récents")
parser.add_argument("--keep",        type=int,  default=5,
                    help="Nombre de runs à conserver (utilisé avec --purge-runs)")
args, _ = parser.parse_known_args()

if args.purge_runs:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from engine.maintenance import purge_runs
    kept, deleted = purge_runs("runs", keep=args.keep)
    print(f"[purge] gardés={kept}  supprimés={deleted}")
    sys.exit(0)

if args.headless:
    from engine.headless import run_headless
    run_headless(
        ticks=args.ticks,
        seed=args.seed,
        config_path=args.config,
        out_path=args.out,
        progress=args.progress,
    )
    sys.exit(0)

# Default: web UI
from web.server import run as run_web
run_web(port=args.port)
