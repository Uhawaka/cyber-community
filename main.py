#!/usr/bin/env python3
"""Compatibility-free entry point for the directory world-package CLI."""

from scripts.world import main


if __name__ == "__main__":
    raise SystemExit(main())
