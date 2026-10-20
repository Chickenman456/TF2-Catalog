"""Fetch a public TF2 backpack from Steam (works for any account with a public inventory)."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (TF2 Catalog; +https://github.com/)",
      "Accept": "application/json,text/xml;q=0.9,*/*;q=0.5"}
WIKI_ID = re.compile(r"itemredirect\.php\?id=(\d+)")


class SteamError(Exception):
    pass


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolve_steamid(text):
    """Accepts a SteamID64, a /profiles/ or /id/ link, or a bare custom URL name."""
    t = (text or "").strip().rstrip("/")
    m = re.search(r"(7656\d{13})", t)
    if m:
        return m.group(1)
    m = re.search(r"/id/([^/?#\s]+)", t)
    vanity = m.group(1) if m else t
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", vanity or ""):
        raise SteamError("That doesn't look like a Steam ID or profile link.")
    try:
        xml = _get("https://steamcommunity.com/id/%s/?xml=1" % urllib.parse.quote(vanity)).decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise SteamError("Couldn't reach Steam (%s)." % getattr(e, "reason", e))
    m = re.search(r"<steamID64>\s*(\d{17})\s*</steamID64>", xml)
    if not m:
        raise SteamError("No Steam profile is called “%s”." % vanity)
    return m.group(1)


def defindex_of(desc, names=None):
    for a in desc.get("actions") or []:
        m = WIKI_ID.search(str(a.get("link", "")))
        if m:
            return int(m.group(1))
    ad = desc.get("app_data") or {}
    if ad.get("def_index"):
        return int(ad["def_index"])
    if names:
        nm = desc.get("market_hash_name") or desc.get("name") or ""
        return names.get(nm.lower())
    return None


QUALITY_TAGS = {"vintage": "vintage", "genuine": "genuine", "strange": "strange", "haunted": "haunted",
                "collector's": "collectors", "unusual": "unusual"}


def qualities_of(desc):
    """Quality keys of one backpack item, e.g. {"strange", "genuine"} for a Strange Genuine item."""
    out = set()
    for t in desc.get("tags") or []:
        if t.get("category") == "Quality":
            q = QUALITY_TAGS.get((t.get("localized_tag_name") or t.get("name") or "").lower())
            if q:
                out.add(q)
    name = desc.get("market_hash_name") or desc.get("name") or ""
    if out and "strange" not in out and name.startswith("Strange "):
        out.add("strange")      # elevated quality, e.g. "Strange Unusual" or "Strange Genuine"
    return out


ECON_IMG = "https://community.akamai.steamstatic.com/economy/image/%s/128fx128f"


def fetch_backpack(steamid, progress=lambda m: None, names=None):
    """Returns ({defindex: count}, total_items, {defindex: official icon URL}, {quality: {defindex: count}})."""
    owned, icons, quals, start, page, total = {}, {}, {}, None, 0, 0
    while True:
        page += 1
        progress("Reading backpack page %d" % page)
        url = "https://steamcommunity.com/inventory/%s/440/2?l=english&count=2000" % steamid
        if start:
            url += "&start_assetid=" + start
        data = None
        for attempt in range(4):
            try:
                data = json.loads(_get(url, 60) or b"null")
                break
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    raise SteamError("This backpack is private. In Steam, set Profile > Edit Profile > Privacy Settings > Inventory to Public, then sync again.")
                if e.code == 429 and attempt < 3:
                    progress("Steam asked us to slow down, waiting…")
                    time.sleep(8 * (attempt + 1))
                    continue
                if e.code == 429:
                    raise SteamError("Steam is rate-limiting requests right now. Wait a minute and sync again.")
                raise SteamError("Steam returned an error (HTTP %d)." % e.code)
            except urllib.error.URLError as e:
                raise SteamError("Couldn't reach Steam (%s)." % getattr(e, "reason", e))
        if not data:
            raise SteamError("Steam didn't return a backpack for this account. It may be private or have no TF2 items.")
        descs = {(d.get("classid"), d.get("instanceid")): d for d in data.get("descriptions") or []}
        for a in data.get("assets") or []:
            d = descs.get((a.get("classid"), a.get("instanceid")))
            if d:
                k = defindex_of(d, names)
                if k:
                    owned[k] = owned.get(k, 0) + 1
                    for q in qualities_of(d):
                        qd = quals.setdefault(q, {})
                        qd[k] = qd.get(k, 0) + 1
                    # plain (unpainted, non-wear) copies give the cleanest icon
                    if d.get("icon_url") and (k not in icons or not d.get("descriptions")):
                        icons[k] = ECON_IMG % d["icon_url"]
        total = data.get("total_inventory_count") or total + len(data.get("assets") or [])
        if data.get("more_items") and data.get("last_assetid"):
            start = data["last_assetid"]
            time.sleep(1.5)
        else:
            return owned, total, icons, quals
