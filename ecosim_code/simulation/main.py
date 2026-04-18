"""
EcoSim — point d'entrée.

Usage:
  python main.py                        # GUI (setup → run → replay)
  python main.py --headless --ticks N   # headless CLI
"""
import argparse
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--headless",  action="store_true")
parser.add_argument("--ticks",     type=int,  default=10000)
parser.add_argument("--seed",      type=int,  default=None)
parser.add_argument("--out",       type=str,  default=None)
parser.add_argument("--config",    type=str,  default=None)
parser.add_argument("--progress",  action="store_true")
args, _ = parser.parse_known_args()

if args.headless:
    from simulation.headless import run_headless
    run_headless(
        ticks=args.ticks,
        seed=args.seed,
        config_path=args.config,
        out_path=args.out,
        progress=args.progress,
    )
    sys.exit(0)

from gui.app import EcoSimApp
EcoSimApp().run()
