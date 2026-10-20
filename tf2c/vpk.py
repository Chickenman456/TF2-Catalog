"""Read files out of TF2's VPK archives (tf2_textures_dir.vpk, tf2_misc_dir.vpk)."""
import os
import struct
import threading


class VPK:
    def __init__(self, dir_path: str):
        self.dir_path = dir_path
        self.prefix = dir_path[: -len("_dir.vpk")]
        self.entries = {}
        self._end = 0
        self._lock = threading.Lock()
        self._handles = {}
        self._load()

    def _load(self):
        with open(self.dir_path, "rb") as f:
            data = f.read()
        sig, ver, tree = struct.unpack_from("<III", data, 0)
        if sig != 0x55AA1234:
            raise ValueError("Not a VPK directory file: %s" % self.dir_path)
        p = 12 if ver == 1 else 28
        self._end = p + tree

        def cstr():
            nonlocal p
            e = data.index(b"\0", p)
            s = data[p:e].decode("utf-8", "replace")
            p = e + 1
            return s

        while True:
            ext = cstr()
            if not ext:
                break
            while True:
                folder = cstr()
                if not folder:
                    break
                while True:
                    name = cstr()
                    if not name:
                        break
                    _crc, pre, arch, off, length, _term = struct.unpack_from("<IHHIIH", data, p)
                    p += 18
                    preload = data[p:p + pre]
                    p += pre
                    path = (folder + "/" if folder != " " else "") + name + "." + ext
                    self.entries[path.lower()] = (arch, off, length, preload)

    def __contains__(self, path):
        return path.lower() in self.entries

    def read(self, path: str) -> bytes:
        arch, off, length, preload = self.entries[path.lower()]
        if length == 0:
            return preload
        if arch == 0x7FFF:
            fn, off = self.dir_path, off + self._end
        else:
            fn = "%s_%03d.vpk" % (self.prefix, arch)
        with self._lock:
            fh = self._handles.get(fn)
            if fh is None:
                fh = self._handles[fn] = open(fn, "rb")
            fh.seek(off)
            body = fh.read(length)
        return preload + body


class TF2Files:
    """Looks up a game path in the loose tf/ folder first, then in the VPKs."""

    def __init__(self, tf_dir: str):
        self.tf_dir = tf_dir
        self.vpks = []
        for name in ("tf2_textures_dir.vpk", "tf2_misc_dir.vpk"):
            p = os.path.join(tf_dir, name)
            if os.path.exists(p):
                self.vpks.append(VPK(p))

    def read(self, path: str):
        path = path.replace("\\", "/").lstrip("/")
        if ".." in path.split("/"):
            return None
        loose = os.path.join(self.tf_dir, *path.split("/"))
        if os.path.isfile(loose):
            with open(loose, "rb") as f:
                return f.read()
        for v in self.vpks:
            if path in v:
                try:
                    return v.read(path)
                except OSError:
                    return None   # archive missing (e.g. a partial install)
        return None
