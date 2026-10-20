"""Item icon URLs. No API key is involved anywhere.

Order of preference for each item:
  1. local TF2 install           decoded in the browser from the game's own textures
  2. TF2 Wiki                    "Item icon <name>.png" files, looked up through the wiki's public API
                                 (war paints and decorated weapons use the wiki's painted
                                 "Backpack <name> Factory New.png", which beat the local icon)
  3. icons seen while syncing    Steam's images of items in your backpack (fills gaps like war paints)
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

WIKI_API = "https://wiki.teamfortress.com/w/api.php"
UA = {"User-Agent": "TF2-Catalog (+https://github.com/)"}
WIKI_TTL = 3 * 24 * 3600


def wiki_name(item):
    """Wiki file title for a catalog item row."""
    name = item[1]
    if item[3] == "t":
        name = re.sub(r"^Taunt: (The )?", "", name)
    return "Item icon %s.png" % name


def _norm(title):
    t = title[5:] if title.startswith("File:") else title
    t = t.replace("_", " ")
    return t[:1].upper() + t[1:]


def refresh_wiki(cache_path, progress=lambda m: None, force=False):
    """Fetch the list of every 'Item icon …' image on the TF2 Wiki (about 20 requests)."""
    try:
        cached = json.load(open(cache_path, encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if cached.get("files") and not force and time.time() - cached.get("checked", 0) < WIKI_TTL:
        return cached["files"]
    files, cont, page = {}, {}, 0
    while True:
        page += 1
        progress("Looking up item icons on the TF2 Wiki (page %d)" % page)
        q = {"action": "query", "format": "json", "list": "allimages", "aiprefix": "Item_icon_",
             "ailimit": "500", "aiprop": "url"}
        q.update(cont)
        req = urllib.request.Request(WIKI_API + "?" + urllib.parse.urlencode(q), headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read())
        for im in j.get("query", {}).get("allimages", []):
            files[_norm(im.get("name") or im.get("title", ""))] = im.get("url")
        if "continue" in j:
            cont = {k: v for k, v in j["continue"].items()}
            time.sleep(0.3)
        else:
            break
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"checked": time.time(), "files": files}, f)
    return files


def refresh_paints(cache_path, catalog, progress=lambda m: None, force=False):
    """War paints and decorated weapons: the wiki's "Backpack <name> Factory New.png" images,
    the same painted icons the Steam Community Market shows."""
    try:
        cached = json.load(open(cache_path, encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    files = cached.get("files", {})
    want = [it[1] for it in catalog["items"] if it[7] & 1 and it[1] not in files]
    fresh = time.time() - cached.get("checked", 0) < WIKI_TTL
    if not want or (fresh and not force):
        return files
    for wear in ("Factory New", "Field-Tested"):
        todo = [n for n in want if n not in files]
        for i in range(0, len(todo), 50):
            progress("Looking up war paint icons on the TF2 Wiki (%d of %d)" % (min(i + 50, len(todo)), len(todo)))
            titles = {"File:Backpack %s %s.png" % (n, wear): n for n in todo[i:i + 50]}
            q = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "titles": "|".join(titles)}
            req = urllib.request.Request(WIKI_API + "?" + urllib.parse.urlencode(q), headers=UA)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.loads(r.read())
            except Exception:
                continue
            norm = {x["to"]: x["from"] for x in j.get("query", {}).get("normalized", [])}
            for p in j.get("query", {}).get("pages", {}).values():
                info = p.get("imageinfo") or []
                name = titles.get(norm.get(p.get("title"), p.get("title")))
                if info and name:
                    files[name] = info[0].get("url")
            time.sleep(0.3)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"checked": time.time(), "files": files}, f)
    return files


def merge(catalog, local_available, seen, wiki_files, paint_files=None):
    """defindex -> URL (or 'local' when the browser should decode it from the TF2 install)."""
    out = {}
    for it in catalog["items"]:
        k = str(it[0])
        if it[7] & 1 and paint_files and paint_files.get(it[1]):
            out[k] = paint_files[it[1]]   # painted icon beats the game's unpainted one
        elif local_available and it[6] >= 0:
            out[k] = "local"
        else:
            u = wiki_files.get(_norm(wiki_name(it))) if wiki_files else None
            if u:
                out[k] = u
            elif seen.get(k):
                out[k] = seen[k]
    return out
