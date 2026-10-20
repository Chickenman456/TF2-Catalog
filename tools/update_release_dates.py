#!/usr/bin/env python3
"""Maintainer tool: add release dates for items that appeared since the last run.

It walks the public history of TF2's items_game.txt in the SteamDatabase
GameTracking-TF2 repository and records the first day each item defindex shows
up, then adds any new ones to data/release_dates.json. Existing dates are kept.

    python tools/update_release_dates.py            # needs git on PATH
"""
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = "https://github.com/SteamDatabase/GameTracking-TF2.git"
PATH = "tf/scripts/items/items_game.txt"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "release_dates.json")


def main():
    dates = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.check_call(["git", "clone", "--filter=blob:none", "--no-checkout", "-q", REPO, tmp])
        revs = subprocess.check_output(["git", "log", "--reverse", "--format=%H %ad", "--date=short", "--", PATH], cwd=tmp).decode().split("\n")
        revs = [r.split() for r in revs if r.strip()]
        first = {}
        start = revs[0][1] if revs else ""
        rx = re.compile(rb'^\t\t"(\d+)"\s*$', re.M)
        cat = subprocess.Popen(["git", "cat-file", "--batch"], cwd=tmp, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        for i, (h, day) in enumerate(revs):
            cat.stdin.write(("%s:%s\n" % (h, PATH)).encode())
            cat.stdin.flush()
            size = int(cat.stdout.readline().split()[2])
            blob = cat.stdout.read(size)
            cat.stdout.read(1)
            a, b = blob.find(b'\n\t"items"\n'), blob.find(b'\n\t"attributes"\n')
            for m in rx.finditer(blob[a:b] if 0 < a < b else blob):
                first.setdefault(m.group(1).decode(), day)
            print("\r%d/%d commits" % (i + 1, len(revs)), end="", file=sys.stderr)
        cat.stdin.close()
    added = 0
    for k, day in first.items():
        if k not in dates and day > start:   # items present at the first tracked commit have no reliable date
            dates[k] = day
            added += 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dates, f, separators=(",", ":"))
    print("\nAdded %d new release dates (%d total)." % (added, len(dates)))


if __name__ == "__main__":
    main()
