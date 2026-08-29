"""Single entry point for HIDGuard, exposed as the `hidguard` console script.

    hidguard                 # start the daemon AND the live dashboard together
    hidguard --headless      # daemon only, printing status (no dashboard)
    hidguard dashboard       # attach a dashboard to an already-running daemon
    hidguard simulate ...    # replay a harmless HID-injection payload

`run` is the default, so a bare `hidguard` is the single command that starts the
program with its dashboard. Each subcommand reuses the flags its own module
defines, so `hidguard simulate --help` and the standalone
`python -m hidguard.simulate --help` list exactly the same options.
"""

import argparse
import sys

from hidguard import dashboard, main, simulate
from hidguard.errors import HidGuardError


def main_cli() -> None:
    """Parses the arguments and runs the chosen subcommand.

    The one place HidGuardError is turned into output: every layer below raises
    with a message written for the person running the program, and this catches
    them all so a missing privilege or an unreadable database leaves one line
    and exit code 1 rather than a traceback. Anything else still propagates --
    a bug should look like a bug.
    """
    try:
        _dispatch(_parse_args())
    except HidGuardError as error:
        print(f"hidguard: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        raise SystemExit(130) from None


def _parse_args() -> argparse.Namespace:
    """Builds the parser and reads sys.argv.

    Bad flag values never reach the program: each one is validated by its
    argparse type, so argparse itself reports them with usage and exit code 2.
    """
    # The run options live on a parent parser so they work both bare
    # (`hidguard --headless`) and under the explicit subcommand (`hidguard run
    # --headless`); a bare invocation and `run` share one namespace this way.
    run_options = argparse.ArgumentParser(add_help=False)
    run_options.add_argument(
        "--headless",
        action="store_true",
        help="daemon only, print status instead of a dashboard",
    )
    dashboard.add_arguments(run_options)  # --limit / --interval for the built-in dashboard

    parser = argparse.ArgumentParser(
        prog="hidguard", description=__doc__.splitlines()[0], parents=[run_options]
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "run",
        parents=[run_options],
        help="start the daemon with its dashboard (default)",
    )

    dashboard_parser = subparsers.add_parser("dashboard", help="dashboard for a running daemon")
    dashboard.add_arguments(dashboard_parser)

    simulate_parser = subparsers.add_parser("simulate", help="replay a HID-injection payload")
    simulate.add_arguments(simulate_parser)

    return parser.parse_args()


def _dispatch(args: argparse.Namespace) -> None:
    """Runs the subcommand the parsed arguments name."""
    if args.command == "dashboard":
        dashboard.dispatch(args)
    elif args.command == "simulate":
        simulate.dispatch(args)
    elif args.headless:
        main.run_headless()
    else:  # None (bare `hidguard`) or "run"
        main.run(limit=args.limit, interval=args.interval)


if __name__ == "__main__":
    main_cli()
