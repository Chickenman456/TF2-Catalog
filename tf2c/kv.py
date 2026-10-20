"""Valve KeyValues (VDF) and localization file parsing."""
import re

_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|(//[^\n]*)|([^\s{}"]+)')


def decode_text(raw: bytes) -> str:
    """TF2 ships some files as UTF-16 (with BOM) and some as UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return raw.decode("utf-8", "replace")


def parse_kv(text: str) -> dict:
    """Parse KeyValues text into nested dicts. Duplicate keys keep the first
    value (scalars) or merge (blocks); platform conditionals are ignored."""
    root = {}
    stack = [root]
    key = None
    for m in _TOK.finditer(text):
        s, br, com, bare = m.groups()
        if com is not None:
            continue
        if br == "{":
            cur = stack[-1]
            d = cur[key] if isinstance(cur.get(key), dict) else {}
            cur[key] = d
            stack.append(d)
            key = None
        elif br == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            v = s if s is not None else bare
            if key is None:
                key = v
            else:
                if v.startswith("[$") and v.endswith("]"):
                    continue
                stack[-1].setdefault(key, v)
                key = None
    return root


def parse_loc(text: str) -> dict:
    """Flat token -> string map from a resource/*_english.txt file (lower-case keys)."""
    out = {}
    for m in re.finditer(r'"([^"\n]+)"\s+"((?:[^"\\\n]|\\.)*)"', text):
        out.setdefault(m.group(1).lower(), m.group(2).replace('\\"', '"'))
    return out
