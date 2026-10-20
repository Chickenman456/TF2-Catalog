#!/usr/bin/env python3
"""TF2 Catalog. Run:  python tf2_catalog.py  [--tf "path/to/Team Fortress 2/tf"] [--no-browser]"""
import sys

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required.")

from tf2c.server import main

if __name__ == "__main__":
    sys.exit(main())
