"""Command-line entry point.

    python -m relief_kitchen.run --scenario configs/scenarios/infeasible.yaml
    python -m relief_kitchen.run --scenario configs/scenarios/road_closure.yaml --gui
"""

from __future__ import annotations

import argparse

from ..algorithms.planner import run_timeline
from .report import format_result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Relief kitchen - Module 1 (search and CSP)")
    ap.add_argument("--scenario", default="configs/scenarios/base.yaml")
    ap.add_argument("--gui", action="store_true", help="open the Pygame visualiser")
    args = ap.parse_args(argv)
    if args.gui:
        from ..viz.app import main as gui_main

        gui_main(["--scenario", args.scenario])
        return
    for r in run_timeline(args.scenario):
        print(format_result(r))
        print()


if __name__ == "__main__":
    main()
