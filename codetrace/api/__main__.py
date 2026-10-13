"""Run the CodeTrace HTTP API: ``python3 -m codetrace.api [options]``."""

from __future__ import annotations

import argparse

from .server import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CodeTrace analysis API and interface")
    parser.add_argument("--host", default="0.0.0.0", help="interface to bind (default: all interfaces)")
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000)")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
