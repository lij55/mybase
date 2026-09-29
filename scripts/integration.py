#!/usr/bin/env python3
"""Run local, stateful acceptance tests; never silently skip unavailable services."""
from pathlib import Path
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parents[1] / 'tests' / 'integration'))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
