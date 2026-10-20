"""Facts the game files don't carry, read from the Team Fortress Wiki's public API.

* which items exist in Vintage / Genuine / Strange / Haunted / Collector's quality
  (the wiki's "List of ... quality items" tables)
* whether an item can be traded or sold on the Steam Community Market
  (the "trade" and "marketable" fields of each item's infobox)

The repo ships a snapshot of both in data/wiki_items.json, so the app works offline.
While running, the app refreshes it in the background about once a week, so new
items pick these facts up without a new release. No API key is involved.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://wiki.teamfortress.com/w/api.php"
UA = {"User-Agent": "TF2-Catalog (+https://github.com/)"}
TTL = 7 * 24 * 3600
CLASSES = ["Scout", "Soldier", "Pyro", "Demoman", "Heavy", "Engineer", "Medic", "Sniper", "Spy", "All classes"]

# quality -> wiki pages (templates or articles) whose item links make up the list
QUALITY_PAGES = {
    "vintage": ["Template:Vintage quality table"],
    "genuine": ["Template:Genuine quality table"],
    "haunted": ["Template:Haunted quality table"],
    "collectors": ["Template:Weapon collector's quality table", "Template:Cosmetic item collector's quality table"],
    "strange": ["List of %s Strange quality items" % c for c in CLASSES],
}


def _api(params):
    q = dict(params, format="json")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def norm(name):
    """Loose key so 'Taunt: The Boiling Point', 'Boiling Point' and 'Force-A-Nature' all match."""
    n = (name or "").lower().replace("_", " ")
    n = re.sub(r"^taunt: ", "", n)
    n = re.sub(r"^the ", "", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def page_links(page):
    d = _api({"action": "parse", "prop": "links", "page": page})
    return [l["*"] for l in d.get("parse", {}).get("links", []) if l.get("ns") == 0]


def fetch_qualities(progress=lambda m: None):
    out = {}
    for q, pages in QUALITY_PAGES.items():
        names = []
        for p in pages:
            progress("Reading the wiki's %s item list" % q)
            try:
                names += page_links(p)
            except Exception:
                continue
            time.sleep(0.2)
        out[q] = sorted(set(names))
    return out


def _field(text, key):
    m = re.search(r"^\s*\|\s*%s\s*=\s*([^\n]*)" % re.escape(key), text, re.M)
    return m.group(1).strip().lower() if m else None


def fetch_item_flags(names, progress=lambda m: None):
    """{wiki title: {"t": tradable, "m": marketable, "a": availability}} read from item infoboxes."""
    out, names = {}, list(dict.fromkeys(names))
    for i in range(0, len(names), 50):
        progress("Reading item details from the wiki (%d of %d)" % (min(i + 50, len(names)), len(names)))
        batch = names[i:i + 50]
        try:
            d = _api({"action": "query", "prop": "revisions", "rvprop": "content", "rvsection": "0",
                      "redirects": "1", "titles": "|".join(batch)})
        except Exception:
            continue
        q = d.get("query", {})
        back = {}
        for r in (q.get("normalized") or []) + (q.get("redirects") or []):
            back.setdefault(r["to"], []).append(r["from"])
        for p in q.get("pages", {}).values():
            revs = p.get("revisions") or []
            text = revs[0].get("*", "") if revs else ""
            if "{{Item infobox" not in text:
                continue
            trade, market = _field(text, "trade"), _field(text, "marketable")
            flags = _field(text, "item-flags") or ""
            avail = re.findall(r"avail\|([^}]*)", _field(text, "availability") or "")
            row = {"t": 0 if trade == "no" or "not tradable" in flags else 1,
                   "m": 1 if market == "yes" else 0, "a": "|".join(avail)}
            q = re.sub(r"[^a-z']", "", (_field(text, "quality") or "").split("<")[0])
            if q and q != "unique":
                row["q"] = q   # the only quality this item comes in (e.g. Genuine promos)
            if market is None and row["t"] and "marketable" not in flags:
                row["m"] = None  # infobox doesn't say
            for title in [p["title"]] + back.get(p["title"], []):
                out[title] = row
                for t2 in back.get(title, []):
                    out[t2] = row
        time.sleep(0.3)
    return out


def load(bundled_path, cache_path):
    """Newest of the bundled snapshot and the background-refreshed cache."""
    best = {}
    for p in (bundled_path, cache_path):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("checked", 0) >= best.get("checked", 0):
            best = d
    return best


def refresh(bundled_path, cache_path, item_names, progress=lambda m: None, force=False):
    cur = load(bundled_path, cache_path)
    if cur and not force and time.time() - cur.get("checked", 0) < TTL:
        return cur
    qual = fetch_qualities(progress)
    flags = fetch_item_flags(item_names, progress)
    if not any(qual.values()) or not flags:
        return cur  # wiki unreachable: keep what we have
    data = {"checked": time.time(), "qualities": qual, "items": flags}
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def apply(catalog, data):
    """Map wiki names onto catalog defindexes: {"q": {quality: [ids]}, "nomarket": [ids]}."""
    by = {}
    for it in catalog["items"]:
        by.setdefault(norm(it[1]), []).append(it[0])
    qual = {}
    for q, names in (data.get("qualities") or {}).items():
        ids = set()
        for n in names:
            ids.update(by.get(norm(n), []))
        qual[q] = sorted(ids)
    flags = {}
    for title, row in (data.get("items") or {}).items():
        for k in by.get(norm(title), []):
            flags[k] = row
    nomarket = sorted(k for k, r in flags.items() if r.get("m") == 0 or r.get("t") == 0)
    keys = {"genuine": "genuine", "vintage": "vintage", "haunted": "haunted", "strange": "strange",
            "collector's": "collectors", "collectors": "collectors", "unusual": "unusual",
            "selfmade": "selfmade", "community": "community", "valve": "valve"}
    only = {}
    genuine = set(qual.get("genuine", []))
    for k, r in flags.items():
        q = keys.get(r.get("q", ""))
        if not q and r.get("q", "").startswith("strange"):
            q = "strange"
        tags = [t for t in (r.get("a") or "").split("|") if t]
        if not q and k in genuine and tags and all(t.startswith("promotional") for t in tags):
            q = "genuine"   # promo handed out only in Genuine quality: no Unique copy exists
        if q:
            only[k] = q
            if q in qual and k not in qual[q]:
                qual[q].append(k)
    medals = [it[0] for it in catalog["items"] if len(it) > 7 and it[7] & 256]
    for k in medals:
        only.setdefault(k, "genuine")
    qual["genuine"] = sorted(set(qual.get("genuine", [])) | set(medals))
    return {"q": qual, "nomarket": nomarket, "only": only}
