"""Find the Team Fortress 2 'tf' folder on Windows, macOS and Linux."""
import os
import re
import sys

MARKER = os.path.join("scripts", "items", "items_game.txt")


def is_tf_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, MARKER))


def normalize(path):
    """Accept the Steam library, the 'Team Fortress 2' folder or the 'tf' folder."""
    if not path:
        return None
    path = os.path.expanduser(path.strip().strip('"'))
    for cand in (path, os.path.join(path, "tf"),
                 os.path.join(path, "Team Fortress 2", "tf"),
                 os.path.join(path, "steamapps", "common", "Team Fortress 2", "tf")):
        if is_tf_dir(cand):
            return os.path.abspath(cand)
    return None


def _steam_roots():
    roots = []
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for val in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(winreg.QueryValueEx(k, val)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    home = os.path.expanduser("~")
    roots += [os.path.join(home, "Library", "Application Support", "Steam"),
              os.path.join(home, ".steam", "steam"),
              os.path.join(home, ".local", "share", "Steam"),
              os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")]
    return [r for r in roots if r and os.path.isdir(r)]


def find_tf_dir():
    env = normalize(os.environ.get("TF2_DIR"))
    if env:
        return env
    seen = set()
    for root in _steam_roots():
        libs = [root]
        lf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(lf):
            try:
                with open(lf, encoding="utf-8", errors="replace") as f:
                    libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
            except OSError:
                pass
        for lib in libs:
            key = os.path.normcase(os.path.abspath(lib))
            if key in seen:
                continue
            seen.add(key)
            hit = normalize(os.path.join(lib, "steamapps", "common", "Team Fortress 2", "tf"))
            if hit:
                return hit
    return None
