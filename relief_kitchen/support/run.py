"""Command-line entry point.

    python -m relief_kitchen.run --scenario configs/scenarios/infeasible.yaml
    python -m relief_kitchen.run --scenario configs/scenarios/road_closure.yaml --gui
    python -m relief_kitchen.run --module m2
    python -m relief_kitchen.run --module m3 --scenario configs/scenarios/stove_failure.yaml
"""

from __future__ import annotations

import argparse


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Collaborative Relief Kitchen")
    ap.add_argument("--scenario", default="configs/scenarios/base.yaml")
    ap.add_argument("--module", choices=["m1", "m2", "m3"], default="m1", help="which module to run (default: m1)")
    ap.add_argument("--gui", action="store_true", help="open the Pygame visualiser (M1 only)")
    args = ap.parse_args(argv)

    if args.module == "m1":
        if args.gui:
            from ..viz.app import main as gui_main

            gui_main(["--scenario", args.scenario])
            return
        from ..algorithms.planner import run_timeline
        from .report import format_result

        for r in run_timeline(args.scenario):
            print(format_result(r))
            print()
    elif args.module == "m2":
        from ..planning.__main__ import main as m2_main

        m2_main(["--scenario", args.scenario])
    elif args.module == "m3":
        from ..uncertainty.__main__ import main as m3_main

        m3_main(["--scenario", args.scenario])


if __name__ == "__main__":
    main()
