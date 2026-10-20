"""Build the collector catalog from the player's own TF2 files.

Inputs (from the local TF2 install, or the SteamDatabase mirror of the same files):
  tf/scripts/items/items_game.txt              item schema
  tf/resource/tf_english.txt                   item names and descriptions
  tf/resource/tf_proto_obj_defs_english.txt    war paint names
plus the curation lists in data/ that the game files can't express
(unreleased items, untradable items that are still earnable, known release dates).
"""
import bisect
import collections
import datetime
import json
import os
import re

from .kv import decode_text, parse_kv, parse_loc

CATALOG_VERSION = 13
CLASSES = ["scout", "soldier", "pyro", "demoman", "heavy", "engineer", "medic", "sniper", "spy"]
WEAPON_SLOTS = {"primary", "secondary", "melee", "pda", "pda2", "building", "utility"}
RARITY = {"common": 1, "uncommon": 2, "rare": 3, "mythical": 4, "legendary": 5, "ancient": 6, "immortal": 7, "unusual": 8}
MEDAL_TYPES = ("Tournament Medal", "Community Medal", "Func_Medal")


def source_files(tf_dir):
    return {"items_game": os.path.join(tf_dir, "scripts", "items", "items_game.txt"),
            "english": os.path.join(tf_dir, "resource", "tf_english.txt"),
            "proto": os.path.join(tf_dir, "resource", "tf_proto_obj_defs_english.txt")}


def signature(sources, data_dir):
    parts = ["v%d" % CATALOG_VERSION]
    for p in list(sources.values()) + [os.path.join(data_dir, n) for n in ("curation.json", "release_dates.json", "crates.json")]:
        try:
            st = os.stat(p)
            parts.append("%d:%d" % (st.st_size, int(st.st_mtime)))
        except OSError:
            parts.append("-")
    return "|".join(parts)


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _ids(spec):
    """Curation lists accept "123" or "100-120" keys."""
    out = set()
    for k in spec:
        if "-" in k:
            a, b = k.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(k))
    return out


RESKIN_IGNORE = ("kill eater", "cannot trade", "always tradable", "special taunt", "allowed in medieval mode",
                 "disable fancy class select anim", "turn to gold", "ragdolls become ash", "is_festivized", "item style",
                 "set item tint", "attach particle", "limited quantity", "disable weapon hiding", "min_viewmodel_offset",
                 "inspect_viewmodel_offset", "weapon_uses_stattrack", "weapon_stattrak", "weapon_allow_inspect",
                 "is australium", "loot rarity", "item slot criteria", "cannot giftwrap", "tool target item",
                 "never craftable", "decoded by", "paintkit", "has team color", "meter_label", "show paint description",
                 "crit_vs_burning_flares_display_only", "override projectile type", "is_operation_pass",
                 "store sort override", "cosmetic", "custom", "unusual", "texture_wear", "display", "item_meter",
                 "wide item level", "deactive date", "gifter account", "event date", "kill_eater", "hide", "ragdoll",
                 "gib", "decapitate type", "mvm", "set_item", "random drop", "force", "saxxy", "set employee number",
                 "is marketable", "is giger counter", "breadgloves", "sapper voice", "pyrovision", "vision opt in")
ITEM_CLASS_SAME = {"tf_weapon_builder": "tf_weapon_sapper"}


def find_reskins(R, weapon_ids, slots):
    """Weapons whose stats are identical to an earlier weapon (or the stock one): {defindex: original}."""
    def sig(k):
        r = R[k]
        attrs = []
        for src in (r.get("attributes") or {}, r.get("static_attrs") or {}):
            if not isinstance(src, dict):
                continue
            for n, v in src.items():
                if n.lower().startswith(RESKIN_IGNORE):
                    continue
                attrs.append((n.lower(), str(v.get("value") if isinstance(v, dict) else v)))
        ic = r.get("item_class")
        cls = r.get("used_by_classes") or {}
        cls = tuple(sorted(c.lower() for c in cls)) if isinstance(cls, dict) else ()
        if ic == "saxxy":   # all-class melee: a stat clone of each class's stock melee
            cls = ()
        return (ITEM_CLASS_SAME.get(ic, ic), r.get("item_slot"), cls, tuple(sorted(attrs)))
    stock = [k for k, r in R.items() if r.get("baseitem") == "1" and r.get("item_slot") in slots]
    first, out = {}, {}
    for k in sorted(stock):
        first.setdefault(sig(k), k)
    for k in sorted(weapon_ids):
        s = sig(k)
        if s[0] == "saxxy" and not s[3]:
            out[k] = 0
            continue
        o = first.setdefault(s, k)
        if o != k:
            out[k] = o
    return out


def _read(path):
    with open(path, "rb") as f:
        return decode_text(f.read())


def build(sources, data_dir, firstseen=None, progress=lambda m: None):
    """Returns the catalog dict. `firstseen` maps defindex -> date the app first
    saw an item; it is updated in place for items with no other date."""
    firstseen = firstseen if firstseen is not None else {}
    cur = json.load(open(os.path.join(data_dir, "curation.json"), encoding="utf-8"))
    try:
        known_dates = {int(k): v for k, v in json.load(open(os.path.join(data_dir, "release_dates.json"), encoding="utf-8")).items()}
    except (OSError, ValueError):
        known_dates = {}
    hidden = _ids(cur.get("hidden", {}))
    earnable = _ids(cur.get("still_earnable", {}))
    always_unob = _ids(cur.get("unobtainable", {}))
    force_reskin = _ids(cur.get("reskins", {}))
    not_reskin = _ids(cur.get("not_reskins", {}))
    not_genuine = _ids(k for k in cur.get("not_genuine", {}) if not k.startswith("_"))
    try:
        wiki_crates = json.load(open(os.path.join(data_dir, "crates.json"), encoding="utf-8"))
    except (OSError, ValueError):
        wiki_crates = {}
    fixed = {}
    for k, v in cur.get("fixed_dates", {}).items():
        for i in _ids([k]):
            fixed[i] = v

    progress("Reading items_game.txt")
    ig_path, en_path, proto_path = sources["items_game"], sources["english"], sources["proto"]
    ig = parse_kv(_read(ig_path))["items_game"]
    progress("Reading localization")
    loc = parse_loc(_read(en_path))
    if os.path.exists(proto_path):
        loc.update(parse_loc(_read(proto_path)))

    prefabs = ig.get("prefabs", {})
    pcache = {}

    def resolve_prefab(name, depth=0):
        if name in pcache:
            return pcache[name]
        p = prefabs.get(name, {})
        base = {}
        if depth < 16:
            for parent in p.get("prefab", "").split():
                base = _merge(base, resolve_prefab(parent, depth + 1))
        pcache[name] = _merge(base, p)
        return pcache[name]

    progress("Resolving item definitions")
    RAW, R = {}, {}
    for k, v in ig.get("items", {}).items():
        if k.isdigit() and isinstance(v, dict):
            k = int(k)
            RAW[k] = v
            base = {}
            for parent in v.get("prefab", "").split():
                base = _merge(base, resolve_prefab(parent))
            R[k] = _merge(base, v)

    def L(key, default=""):
        if not key:
            return default
        if key.startswith("#"):
            return loc.get(key[1:].lower(), default or key)
        return loc.get(key.lower(), key)

    def prefab_str(k):
        return RAW[k].get("prefab", "") + " " + R[k].get("prefab", "")

    def tname(k):
        return L(R[k].get("item_type_name"), "")

    def display_name(k):
        r = R[k]
        base = L(r.get("item_name"), r.get("name", str(k)))
        if base.startswith("#"):
            base = r.get("name", str(k))
        base = re.sub(r"\s+", " ", base.replace("\\n", " ")).strip()
        pk = (r.get("static_attrs") or {}).get("paintkit_proto_def_index")
        if pk is not None:
            kit = loc.get("9_%s_field { field_number: 2 }" % pk)
            if kit:
                if "paintkit_tool" in prefab_str(k):
                    return kit + " War Paint"
                if pk != "0" or "paintkit_weapon" in RAW[k].get("prefab", ""):
                    return "%s %s" % (kit, base)
        return base

    def desc(k):
        t = L(R[k].get("item_description"), "")
        if not t or t.startswith("#"):
            return ""
        t = re.sub(r"<[^>]+>", "", t.replace("\\n", "\n"))
        return re.sub(r"[ \t]+", " ", t).strip()[:400]

    def untradable(k):
        r = R[k]
        return bool((r.get("attributes") or {}).get("cannot trade") or (r.get("static_attrs") or {}).get("cannot trade"))

    def category(k):
        r = R[k]
        if k in hidden or not r.get("image_inventory") or r.get("name", "").endswith("(Armory)"):
            return None
        slot = r.get("item_slot")
        pf = prefab_str(k)
        if "paintkit_tool" in pf:
            pk = (r.get("static_attrs") or {}).get("paintkit_proto_def_index")
            return "w" if pk not in (None, "0") and loc.get("9_%s_field { field_number: 2 }" % pk) else None
        if slot in ("head", "misc"):
            if r.get("show_in_armory") == "0" and not untradable(k) and k not in earnable:
                return None
            return "m" if tname(k) in MEDAL_TYPES else "c"
        if slot == "taunt":
            return "t"
        if slot in WEAPON_SLOTS:
            if r.get("item_class") in ("slot_token", "class_token"):
                return None
            if r.get("baseitem") == "1" or k <= 30 or 190 <= k <= 212:
                return None
            nm = display_name(k)
            if nm.startswith(("Upgradeable ", "TF_", "#")):
                return None
            if r.get("show_in_armory") == "0" and not untradable(k) and "paintkit" not in pf:
                return None
            return "w"
        return None

    # ---- collections, grades and cases -----------------------------------
    progress("Reading collections and cases")
    by_name = {}
    for k, r in R.items():
        if "name" in r:
            by_name.setdefault(r["name"], k)
            by_name.setdefault(r["name"].lower(), k)
    rarity = {}
    collections_ = {}
    for cid, c in ig.get("item_collections", {}).items():
        if not isinstance(c, dict) or c.get("is_reference_collection") == "1":
            continue
        members = []
        for key, v in (c.get("items") or {}).items():
            if isinstance(v, dict):
                for nm in v:
                    k = by_name.get(nm) or by_name.get(nm.lower())
                    if k:
                        members.append(k)
                        if key in RARITY:
                            rarity[k] = RARITY[key]
            else:
                k = by_name.get(key) or by_name.get(key.lower())
                if k:
                    members.append(k)
        if not members:
            continue
        name = L(c.get("name"), cid)
        if name == cid or name.startswith("#"):
            name = re.sub(r"_?collection(_lootlist)?$", "", cid, flags=re.I).replace("_", " ") + " Collection"
        collections_[cid] = {"id": cid, "n": name, "k": "collection", "i": list(dict.fromkeys(members)), "c": []}

    lootlists = ig.get("client_loot_lists", {})
    series_to_list = {}
    for a, b in ig.get("revolving_loot_lists", {}).items():
        if b.lstrip("-").isdigit():
            series_to_list[b] = a
        elif a.lstrip("-").isdigit():
            series_to_list[a] = b

    def lootlist_contents(name, seen=None, depth=0):
        seen = seen if seen is not None else set()
        if name in seen or depth > 8:
            return [], None
        seen.add(name)
        ll = lootlists.get(name) or {}
        found, coll = [], ll.get("loot_list_collection")
        for k, v in ll.items():
            if isinstance(v, dict) or k.startswith("loot_list") or k in ("hide_lootlist", "public_list_contents", "rarity", "is_rare_item"):
                continue
            if k in lootlists:
                sub, sc = lootlist_contents(k, seen, depth + 1)
                found += sub
                coll = coll or sc
            else:
                d = by_name.get(k) or by_name.get(k.lower())
                if d:
                    found.append(d)
        return found, coll

    crate_def = {}
    for k, r in R.items():
        if r.get("item_class") != "supply_crate":
            continue
        sa, at = r.get("static_attrs") or {}, r.get("attributes") or {}
        series = sa.get("set supply crate series")
        if series is None and isinstance(at.get("set supply crate series"), dict):
            series = at["set supply crate series"].get("value")
        if series is not None and str(series).isdigit():
            crate_def.setdefault(str(series), k)

    # Old event crates (Robo Community Crate, summer coolers...) carry no series
    # number in the client schema; the wiki snapshot names them and, where the
    # schema has no loot list either, says what was inside.
    by_display = {}
    for k, r in R.items():
        if r.get("item_slot") in ("head", "misc", "taunt") or r.get("item_slot") in WEAPON_SLOTS:
            by_display.setdefault(display_name(k).lower(), k)
    crate_by_name = {}
    for k, r in R.items():
        if r.get("item_class") == "supply_crate":
            crate_by_name.setdefault(display_name(k).lower(), k)
    cases = []
    for series in sorted(set(s for s in series_to_list if s.isdigit()) | set(crate_def) | set(wiki_crates), key=int):
        k = crate_def.get(series)
        wc = wiki_crates.get(series) or {}
        if not k and wc.get("n") and wc["n"].lower() != "mann co. supply crate":
            k = crate_by_name.get(wc["n"].lower())
        lst = series_to_list.get(series)
        contents, coll = lootlist_contents(lst) if lst else ([], None)
        if not contents and not coll and wc.get("i"):
            contents = [by_display[n.lower()] for n in wc["i"] if n.lower() in by_display]
        if k:
            cname = display_name(k)
            pf = prefab_str(k)
            low = (cname + " " + json.dumps(R[k].get("tool", {}))).lower()
        else:
            cname, pf, low = wc.get("n") or "Mann Co. Supply Crate", "", "crate"
        if "halloween" in low or "scream" in low:
            kind = "halloween"
        elif "keyless" in low:
            kind = "keyless"
        elif "weapon_case" in pf or "war paint" in low:
            kind = "warpaint"
        elif "cosmetic_case" in pf or "cosmetic" in low:
            kind = "cosmetic"
        else:
            kind = "case" if "case" in low else "crate"
        case = {"id": k or -int(series), "s": int(series), "n": cname, "kind": kind,
                "d": wc.get("d") or (R[k].get("first_sale_date", "") if k else "").replace("/", "-"), "col": None}
        if coll and coll in collections_:
            case["col"] = coll
        elif contents:
            cid = "crate_%s" % series
            collections_[cid] = {"id": cid, "n": "%s #%s" % (cname, series), "k": "crate", "i": list(dict.fromkeys(contents)), "c": []}
            case["col"] = cid
        if case["col"]:
            collections_[case["col"]]["c"].append(case["id"])
            cases.append(case)
    newest = {}
    for c in cases:
        if c["kind"] in ("cosmetic", "warpaint", "halloween"):
            newest[c["kind"]] = max(newest.get(c["kind"], -1), c["s"])
    for c in cases:
        c["r"] = 0 if newest.get(c["kind"]) == c["s"] else 1

    # ---- the checklist itself ---------------------------------------------
    progress("Building the checklist")
    cat = {k: category(k) for k in R}
    ids = sorted(k for k, c in cat.items() if c)

    coldate = {}
    casedate = {c["id"]: c["d"] for c in cases if c["d"]}
    for c in collections_.values():
        ds = [casedate[x] for x in c["c"] if x in casedate]
        if ds:
            for i in c["i"]:
                coldate[i] = min(coldate.get(i, "9999"), min(ds))

    today = datetime.date.today().isoformat()
    dates = {}
    for k in ids:
        if k in fixed:
            dates[k] = fixed[k]
        elif k in known_dates:
            dates[k] = known_dates[k]
        elif k in coldate:
            dates[k] = coldate[k]
        else:
            s = R[k].get("first_sale_date", "")
            if s and s > "2010/10/05":
                dates[k] = s.replace("/", "-")
            elif cat[k] == "m" and re.search(r"\b(20[0-3]\d)\b", display_name(k)):
                dates[k] = re.search(r"\b(20[0-3]\d)\b", display_name(k)).group(1)
    # Items this app has never seen before and that carry no date: they are
    # new since the bundled date list, so the day we first see them is close.
    if known_dates:
        for k in ids:
            if k not in dates:
                dates[k] = firstseen.setdefault(str(k), today)
    anchors = sorted((k, v) for k, v in dates.items())
    keys = [a[0] for a in anchors]
    for k in ids:
        if k not in dates:
            i = bisect.bisect_left(keys, k)
            cand = [anchors[j] for j in (i - 1, i) if 0 <= j < len(anchors)]
            dates[k] = min(cand, key=lambda x: abs(x[0] - k))[1] if cand else today

    year_ago = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    reskin_of = find_reskins(R, [k for k in ids if cat[k] == "w"], WEAPON_SLOTS)
    imgs, items, sounds = {}, [], {}
    for k in ids:
        r = R[k]
        img = (r.get("image_inventory") or "").lower()
        ii = imgs.setdefault(img, len(imgs))
        classes = r.get("used_by_classes") or {}
        classes = {c.lower() for c in classes} if isinstance(classes, dict) else set()
        mask = sum(1 << i for i, c in enumerate(CLASSES) if c in classes)
        if not mask and cat[k] in ("c", "m", "t"):
            mask = 511
        unt = untradable(k)
        unob = k in always_unob or (k not in earnable and (cat[k] == "m" or
                (unt and (tname(k) == "Community Medal" or dates[k] < year_ago))))
        warp = any(t.startswith("paintkit") and t != "paintkit_base" for t in prefab_str(k).split())
        t = tname(k) or ("War Paint" if warp else "")
        if t.startswith(("#", "TF_")):
            t = "Cosmetic"
        nm = display_name(k)
        flags = (1 if warp else 0) | (2 if unob else 0) | (4 if unt else 0) | (8 if r.get("holiday_restriction") else 0)
        if "paintkit_tool" in prefab_str(k):
            flags |= 128   # the War Paint itself, as opposed to a decorated weapon
            mask = 511     # any class can use one
        if cat[k] == "m" and k not in not_genuine:
            flags |= 256   # medals are handed out in Genuine quality
        if cat[k] == "w" and not warp:
            if "Botkiller" in nm:
                flags |= 32
            elif nm.startswith("Festive "):
                flags |= 64
            if (k in force_reskin or k in reskin_of) and k not in not_reskin:
                flags |= 16
        er = r.get("equip_region") or r.get("equip_regions") or ""
        if isinstance(er, dict):
            er = sorted(er)[0] if er else ""
        region = str(er).replace("_", " ").strip().title() if cat[k] in ("c", "m") else ""
        # the item's own backpack sounds (hat rustle, gun clack, medal clink...)
        pair = tuple(os.path.splitext(os.path.basename((r.get(f) or "").replace("\\", "/")))[0].lower()
                     for f in ("mouse_pressed_sound", "drop_sound"))
        si = sounds.setdefault(pair, len(sounds)) if pair[0] else -1
        items.append([k, display_name(k), t, cat[k], mask, rarity.get(k, 0), ii, flags, dates[k],
                      desc(k) if cat[k] != "m" else "", region, si])

    # The same item listed twice under two defindexes (e.g. the two Pyrovision
    # Goggles): show it once, and count either copy as owning it.
    dup, first_of = {}, {}
    for it in items:
        if it[3] == "m":
            continue
        key = (it[1].lower(), it[3])
        if key in first_of:
            f = first_of[key]
            dup[it[0]] = f[0]
            if not it[7] & 2:
                f[7] &= ~2          # obtainable if either copy still is
            if not it[7] & 4:
                f[7] &= ~4
            f[8] = min(f[8], it[8])
        else:
            first_of[key] = it
    items = [it for it in items if it[0] not in dup]
    keep = set(ids) - set(dup)
    cols = []
    for c in collections_.values():
        members = list(dict.fromkeys(dup.get(i, i) for i in c["i"] if dup.get(i, i) in keep))
        if members:
            cols.append({"id": c["id"], "n": c["n"], "k": c["k"], "i": members, "c": c["c"]})
    colids = {c["id"] for c in cols}
    case_out = [{"id": c["id"], "s": c["s"], "n": c["n"], "col": c["col"], "r": c["r"], "d": c["d"]}
                for c in cases if c["col"] in colids]

    byname = {}
    for it in items:
        byname.setdefault((it[1], it[3]), it[0])
    alias = {str(k): v for k, v in dup.items()}
    for k, r in R.items():
        if k in keep or k in dup or k in hidden or not r.get("image_inventory"):
            continue
        slot = r.get("item_slot")
        c2 = "w" if slot in WEAPON_SLOTS else ("t" if slot == "taunt" else ("c" if slot in ("head", "misc") else None))
        if c2 and (display_name(k), c2) in byname:
            alias[str(k)] = byname[(display_name(k), c2)]

    return {"built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "imgs": list(imgs), "items": items,
            "cols": cols, "cases": case_out, "alias": alias,
            "sounds": [list(p) for p, _ in sorted(sounds.items(), key=lambda x: x[1])]}
