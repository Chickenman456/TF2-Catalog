"""Refresh data/crates.json from the Team Fortress Wiki.

The client item schema leaves out the series number for many old event crates
(Robo Community Crate, summer coolers, winter crates...), and for a few of them
(Robo Community Crate) the loot list too. This pulls each retired/active crate
series' name, release date and contents from the wiki so the app can show them.

Run it from the repo root:  python tools/update_crates.py
"""
import json
import os
import re
import urllib.parse
import urllib.request

API = "https://wiki.teamfortress.com/w/api.php?action=parse&prop=wikitext&format=json&page="
PAGES = ["Mann_Co._Supply_Crate/Retired_series", "Mann_Co._Supply_Crate/Active_series"]
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "crates.json")


def wikitext(page):
    req = urllib.request.Request(API + urllib.parse.quote(page), headers={"User-Agent": "tf2-catalog"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return data.get("parse", {}).get("wikitext", {}).get("*", "")


def contents(series):
    t = wikitext("Template:Crate_series/%s" % series)
    names = []
    for row in re.findall(r"\{\{Store row noprice\|([^}]*)\}\}", t):
        names += [n.strip() for n in row.split("|") if n.strip()]
    return names


def main():
    out = {}
    for page in PAGES:
        t = wikitext(page)
        for sec in re.split(r"\n=== ", t)[1:]:
            m = re.match(r"\{\{anchor\|(\d+)", sec)
            if not m:
                continue
            s = m.group(1)
            name = re.search(r"item-name\s*=\s*([^\n|]+)", sec)
            date = re.search(r"\{\{Patch name\|(\d+)\|(\d+)\|(\d+)", sec)
            row = {"n": name.group(1).strip() if name else "Mann Co. Supply Crate"}
            if date:
                row["d"] = "%s-%02d-%02d" % (date.group(3), int(date.group(1)), int(date.group(2)))
            row["i"] = contents(s)
            out.setdefault(s, row)
            print(s, row["n"], row.get("d"), len(row["i"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({k: out[k] for k in sorted(out, key=int)}, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
