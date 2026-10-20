"""Where the item files come from: the local TF2 install when there is one,
otherwise SteamDatabase's public mirror of the same files (updated within hours
of every TF2 patch). Downloads are cached and only re-fetched when they change."""
import json
import os
import time
import urllib.error
import urllib.request

MIRROR = "https://raw.githubusercontent.com/SteamDatabase/GameTracking-TF2/master/tf/"
FILES = {"items_game": "scripts/items/items_game.txt",
         "english": "resource/tf_english.txt",
         "proto": "resource/tf_proto_obj_defs_english.txt"}
UA = {"User-Agent": "TF2-Catalog"}
CHECK_EVERY = 6 * 3600


def mirror_paths(cache_dir):
    return {k: os.path.join(cache_dir, "schema", os.path.basename(v)) for k, v in FILES.items()}


def refresh_mirror(cache_dir, progress=lambda m: None, force=False):
    """Download changed files. Returns True if anything changed."""
    meta_path = os.path.join(cache_dir, "schema", "meta.json")
    try:
        meta = json.load(open(meta_path, encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    paths = mirror_paths(cache_dir)
    have_all = all(os.path.exists(p) for p in paths.values())
    if have_all and not force and time.time() - meta.get("checked", 0) < CHECK_EVERY:
        return False
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    changed = False
    for key, rel in FILES.items():
        progress("Checking for TF2 item updates (%s)" % os.path.basename(rel))
        headers = dict(UA)
        etag = meta.get("etag_" + key)
        if etag and os.path.exists(paths[key]):
            headers["If-None-Match"] = etag
        try:
            with urllib.request.urlopen(urllib.request.Request(MIRROR + rel, headers=headers), timeout=120) as r:
                data = r.read()
                meta["etag_" + key] = r.headers.get("ETag", "")
            tmp = paths[key] + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, paths[key])
            changed = True
        except urllib.error.HTTPError as e:
            if e.code != 304:
                if not have_all:
                    raise
        except urllib.error.URLError:
            if not have_all:
                raise
    meta["checked"] = time.time()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return changed
