"""
EcoSim — point d'entrée.

Usage:
  python main.py                             # Interface web localhost:8765
  python main.py --tk                        # Ancien GUI tkinter
  python main.py --headless --ticks N        # Headless CLI
  python main.py --port 9000                 # Port custom
"""
import argparse
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--headless",  action="store_true")
parser.add_argument("--tk",        action="store_true", help="Ancien GUI tkinter")
parser.add_argument("--ticks",     type=int,  default=10000)
parser.add_argument("--seed",      type=int,  default=None)
parser.add_argument("--out",       type=str,  default=None)
parser.add_argument("--config",    type=str,  default=None)
parser.add_argument("--progress",  action="store_true")
parser.add_argument("--port",      type=int,  default=9000)
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

if args.tk:
    from gui.app import EcoSimApp
    EcoSimApp().run()
    sys.exit(0)

# Default: web UI
from web.server import run as run_web
run_web(port=args.port)
