"""Refresh the bundled wiki snapshot (data/wiki_items.json): quality lists and trade/market flags.

Run from the repo root:  python tools/update_wiki_data.py
The app also refreshes this by itself about once a week while it runs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tf2c import catalog, sources, wikidata  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main():
    cache = os.path.join(ROOT, "userdata", "cache")
    sources.refresh_mirror(cache)
    cat = catalog.build(sources.mirror_paths(cache), os.path.join(ROOT, "data"), {}, print)
    names = [it[1] for it in cat["items"] if it[3] != "m"]
    out = os.path.join(ROOT, "data", "wiki_items.json")
    data = wikidata.refresh(out, out + ".tmp", names, print, force=True)
    os.replace(out + ".tmp", out)
    m = wikidata.apply(cat, data)
    print({q: len(v) for q, v in m["q"].items()}, "not marketable:", len(m["nomarket"]))


if __name__ == "__main__":
    main()
