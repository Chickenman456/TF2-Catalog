"""Local web server: serves the checklist UI and reads everything else from the
player's own TF2 install. Nothing is uploaded anywhere; Steam is only contacted
to read the public backpack of the ID you type in."""
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/ttf", ".ttf")
from . import catalog as catalog_mod
from . import icons as icons_mod
from . import locate, steam, wikidata
from . import sources as sources_mod
from .vpk import TF2Files

if getattr(sys, "frozen", False):          # packaged .exe: bundled files live in a temp dir
    ROOT = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    HOME = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    HOME = ROOT
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
USER = os.environ.get("TF2C_USER_DIR") or os.path.join(HOME, "userdata")   # your settings + cache, git-ignored
CACHE = os.path.join(USER, "cache")


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.config = jload(os.path.join(USER, "config.json"), {})
        self.tf_dir = locate.normalize(self.config.get("tf_dir")) or locate.find_tf_dir()
        self.files = None
        self.catalog = None
        self.catalog_json = None
        self.icons_json = None
        self.extra_json = None
        self.wiki_files = jload(os.path.join(CACHE, "wiki_icons.json"), {}).get("files", {})
        self.paint_files = jload(os.path.join(CACHE, "wiki_paints.json"), {}).get("files", {})
        self.job = {"msg": ""}

    def progress(self, msg):
        self.job["msg"] = msg

    # -- where the item files come from ------------------------------------
    def source(self):
        return "local" if self.tf_dir else "online"

    def sources(self):
        if self.tf_dir:
            return catalog_mod.source_files(self.tf_dir)
        sources_mod.refresh_mirror(CACHE, progress=self.progress)
        return sources_mod.mirror_paths(CACHE)

    def set_tf_dir(self, path):
        if not path:
            self.tf_dir = None
            self.config.pop("tf_dir", None)
        else:
            tf = locate.normalize(path)
            if not tf:
                raise ValueError("Couldn't find TF2 there. Pick the folder that contains 'tf' (or the 'tf' folder itself).")
            self.tf_dir = tf
            self.config["tf_dir"] = tf
        self.files, self.catalog, self.catalog_json, self.icons_json = None, None, None, None
        jsave(os.path.join(USER, "config.json"), self.config)

    def game_files(self):
        if self.files is None and self.tf_dir:
            self.files = TF2Files(self.tf_dir)
        return self.files

    # -- catalog ---------------------------------------------------------
    def get_catalog(self):
        with self.lock:
            srcs = self.sources()
            sig = catalog_mod.signature(srcs, DATA)
            if self.catalog_json and self.catalog.get("sig") == sig:
                return self.catalog_json
            cache_path = os.path.join(CACHE, "catalog.json")
            cached = jload(cache_path, None)
            if not cached or cached.get("sig") != sig:
                firstseen_path = os.path.join(USER, "firstseen.json")
                firstseen = jload(firstseen_path, {})
                t = time.time()
                cached = catalog_mod.build(srcs, DATA, firstseen, progress=self.progress)
                cached["sig"] = sig
                jsave(cache_path, cached)
                jsave(firstseen_path, firstseen)
                print("Built item list: %d items in %.1fs (%s files)" % (len(cached["items"]), time.time() - t, self.source()))
            cached["source"] = self.source()
            self.catalog, self.icons_json, self.extra_json = cached, None, None
            self.catalog_json = json.dumps(cached, separators=(",", ":")).encode()
            self.progress("")
            return self.catalog_json

    # -- icons -----------------------------------------------------------
    def refresh_wiki(self):
        try:
            self.wiki_files = icons_mod.refresh_wiki(os.path.join(CACHE, "wiki_icons.json"), progress=self.progress)
            if self.catalog:
                self.paint_files = icons_mod.refresh_paints(os.path.join(CACHE, "wiki_paints.json"), self.catalog, progress=self.progress)
            self.icons_json = None
        except Exception as e:
            print("TF2 Wiki icon lookup failed: %s" % e)
        self.progress("")

    def get_icons(self):
        if self.icons_json is None and self.catalog:
            m = icons_mod.merge(self.catalog, bool(self.tf_dir),
                                jload(os.path.join(USER, "icons_seen.json"), {}), self.wiki_files, self.paint_files)
            self.icons_json = json.dumps(m, separators=(",", ":")).encode()
        return self.icons_json or b"{}"

    def remember_icons(self, icons):
        if icons:
            path = os.path.join(USER, "icons_seen.json")
            seen = jload(path, {})
            seen.update({str(k): v for k, v in icons.items()})
            jsave(path, seen)
            self.icons_json = None

    # -- qualities and market flags from the wiki ----------------------------
    def wiki_paths(self):
        return os.path.join(DATA, "wiki_items.json"), os.path.join(CACHE, "wiki_items.json")

    def get_extra(self):
        if self.extra_json is None and self.catalog:
            m = wikidata.apply(self.catalog, wikidata.load(*self.wiki_paths()))
            self.extra_json = json.dumps(m, separators=(",", ":")).encode()
        return self.extra_json or b"{}"

    def refresh_wikidata(self):
        try:
            names = [it[1] for it in self.catalog["items"] if it[3] != "m"] if self.catalog else []
            wikidata.refresh(*self.wiki_paths(), names, progress=self.progress)
            self.extra_json = None
        except Exception as e:
            print("TF2 Wiki item details lookup failed: %s" % e)
        self.progress("")

    def warm_up(self):
        try:
            self.get_catalog()
            self.refresh_wiki()
            self.refresh_wikidata()
        except Exception as e:
            self.progress("")
            print("Couldn't load the item list: %s" % e)

    def state_path(self):
        return os.path.join(USER, "state.json")


APP = None


class Handler(BaseHTTPRequestHandler):
    server_version = "TF2Catalog/" + __version__

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        try:
            if path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/status":
                return self.send(200, {"version": __version__, "tf_dir": APP.tf_dir, "source": APP.source(), "job": APP.job})
            if path == "/api/catalog":
                try:
                    return self.send(200, APP.get_catalog())
                except Exception as e:
                    return self.send(503, {"error": "Couldn't load the TF2 item list: %s. Check your internet connection, or point the app at your TF2 install." % e})
            if path == "/api/extra":
                return self.send(200, APP.get_extra())
            if path == "/api/icons":
                return self.send(200, APP.get_icons())
            if path == "/api/state":
                return self.send(200, jload(APP.state_path(), {}))
            if path.startswith("/game/"):
                # raw game files (textures, fonts) straight from the local install
                rel = path[len("/game/"):]
                if not rel.startswith(("materials/", "resource/")) or not rel.endswith((".vtf", ".ttf")):
                    return self.send(403, {"error": "not allowed"})
                files = APP.game_files()
                data = files.read(rel) if files else None
                if data is None:
                    return self.send(404, {"error": "missing"})
                ctype = "font/ttf" if rel.endswith(".ttf") else "application/octet-stream"
                return self.send(200, data, ctype, cache=True)
            if path.startswith(("/static/", "/ui/", "/fonts/", "/sounds/")):
                rel = path[len("/static/"):] if path.startswith("/static/") else path.lstrip("/")
                fp = os.path.normpath(os.path.join(WEB, rel))
                if fp.startswith(WEB) and os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        return self.send(200, f.read(), mimetypes.guess_type(fp)[0] or "application/octet-stream", cache=True)
            return self.send(404, {"error": "not found"})
        except Exception as e:
            traceback.print_exc()
            return self.send(500, {"error": str(e)})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        b = self.body()
        try:
            if path == "/api/tfdir":
                APP.set_tf_dir(b.get("path", ""))
                threading.Thread(target=APP.warm_up, daemon=True).start()
                return self.send(200, {"tf_dir": APP.tf_dir})
            if path == "/api/state":
                if not isinstance(b, dict):
                    return self.send(400, {"error": "bad state"})
                jsave(APP.state_path(), b)
                return self.send(200, {"ok": True})
            if path == "/api/sync":
                sid = steam.resolve_steamid(b.get("id", ""))
                names = None
                if APP.catalog:
                    names = {it[1].lower(): it[0] for it in APP.catalog["items"]}
                owned, total, icons, quals = steam.fetch_backpack(sid, progress=APP.progress, names=names)
                APP.progress("")
                APP.remember_icons(icons)
                return self.send(200, {"steamid": sid, "owned": owned, "total": total, "quality": quals})
            return self.send(404, {"error": "not found"})
        except (ValueError, steam.SteamError) as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self.send(500, {"error": str(e)})


def main(argv=None):
    global APP
    argv = sys.argv[1:] if argv is None else argv
    APP = App()
    if "--tf" in argv:
        APP.set_tf_dir(argv[argv.index("--tf") + 1])
    srv, port = None, 8440
    for p in range(8440, 8470):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print("Couldn't open a local port between 8440 and 8469.")
        return 1
    url = "http://127.0.0.1:%d/" % port
    print("TF2 Catalog %s" % __version__)
    print("Item data: %s" % (APP.tf_dir or "online (TF2 install not found, that's fine)"))
    print("Open %s  (Ctrl+C to quit)" % url)
    threading.Thread(target=APP.warm_up, daemon=True).start()
    if "--no-browser" not in argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
