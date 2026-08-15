"""CLI: ``python -m tkipw doctor``."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tkipw")
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("doctor", help="Diagnose packages, WebView engine, and JS runtime")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        from .doctor import run_doctor

        return run_doctor()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
