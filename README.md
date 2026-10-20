# TF2 Catalog

> **Disclaimer: this is mostly AI slop**, minus some code borrowed from the TF2 SDK. It was built mostly for my own convenience. Please forgive me. Item data comes from TF2's own files, but the rules on top of it (release years, what counts as unobtainable, hidden items) can be wrong, so double-check before you trade, and send a pull request when you spot a mistake.

A checklist for Team Fortress 2 collectors. Type in any Steam ID and see every cosmetic, taunt, weapon and medal you own and are missing, laid out like the in-game backpack.

- **Every item, always current.** The item list is built from TF2's own item files: your local install if you have one, otherwise the public SteamDatabase mirror, which updates within hours of every TF2 patch. New cases and cosmetics show up without waiting for this project to update.
- **Any account.** Sync with a SteamID64, a custom URL name, or a profile link. The backpack has to be public.
- **Single-quality items stand out.** Items that only exist in one quality, like the Genuine-only Boiling Point taunt, show their name in that quality's color. Community and tournament medals count as Genuine; list any exceptions under `not_genuine` in `curation.json`.
- **Every quality.** Switch the checklist to Vintage, Genuine, Strange, Haunted or Collector's to see every item that exists in that quality and which ones you have. Strange Unusuals, Strange Genuines and so on count for both qualities.
- **Browse it your way.** By class, by release year, or by case and collection (a case and the collection it unlocks share one section, numbered by case). Sort by grade, class, equip region or name. Filters fold away behind one Filters button, with a one-line summary of what's active and a Reset. Filter by class, grade, owned or missing, obtainable or unobtainable, Halloween-restricted, and multi-class items. War paints and decorated (war-painted) weapons are their own item types, and weapons can hide reskins, Botkillers and Festives.
- **Unobtainable items flagged.** Items that can't be traded and aren't given out any more (Tux, old promo hats, community and tournament medals) are marked, and you can override any call.
- **Wishlist**, plus manual "I own this" marks for items held elsewhere.
- **Looks and sounds like TF2.** It uses TF2's real fonts, backpack borders, rarity colors, class art and item icons, plus the game's own UI sounds: button clicks, panel slides, and each item's own backpack pickup and drop sound when you tick it off. The megaphone button next to Sync mutes them.
- **Wiki and Market links** on every item (Market only when the item can be sold there).

## Run it

You need either **Python 3.8+** or the Windows .exe from the Releases page. TF2 doesn't have to be installed.

**Windows, no Python:** download `TF2-Catalog-windows.zip` from Releases, unzip, and run the .exe.

**With Python (any OS):**

```
git clone https://github.com/<you>/tf2-catalog.git
cd tf2-catalog
python tf2_catalog.py          # Windows: double-click run.bat
```

Your browser opens at `http://127.0.0.1:8440`. There's nothing to install: the app uses only Python's standard library.

If TF2 is installed, the app finds it through Steam and reads the item list and icons straight from your game files. Without it, the app downloads TF2's item files instead. Use the ⚙ button to switch, or pass the folder directly:

```
python tf2_catalog.py --tf "D:\SteamLibrary\steamapps\common\Team Fortress 2"
```

## Privacy

- Everything runs on your computer. Outside requests go only to `steamcommunity.com` (the public backpack of the ID you enter), Steam's image servers, `raw.githubusercontent.com` (TF2 item files, when TF2 isn't installed) and `wiki.teamfortress.com` (icons, quality lists, and which items can be sold on the Market). No Steam API key is needed.
- Your wishlist, sync results and settings are saved in `userdata/` next to the app. That folder is git-ignored and never leaves your machine.

## Keeping it up to date

There's nothing to do. The app checks for changed TF2 item files when it starts (and every few hours) and rebuilds the list if they changed. That takes about a second.

### Icons

Each item's icon comes from the first of these that has it. No Steam API key is needed for any of them:

1. Your local TF2 install, decoded in the browser.
2. The TF2 Wiki's "Item icon" images (about 99% of cosmetics and taunts).
3. Steam's images of items in your backpack, picked up when you sync. These fill gaps like medals.

War paints and decorated weapons use the TF2 Wiki's painted backpack images (the same pictures the Steam Community Market shows), so you see the actual paint instead of the plain weapon.

Some facts aren't in the game files, so they live in `data/`:

| File | What it holds |
|---|---|
| `data/curation.json` | Items to hide (unreleased, robot-only, placeholders), untradable items that are still earnable, and fixed release dates. Edit by defindex, ranges allowed (`"100-120"`). |
| `data/wiki_items.json` | Which items exist in each quality, and which can be traded or sold on the Market, from the TF2 Wiki. The app refreshes this by itself about once a week; `tools/update_wiki_data.py` refreshes the bundled copy. |
| `data/crates.json` | Names, dates and contents of old crates whose series number or contents are missing from the game files (the Robo Community Crate, for example), from the TF2 Wiki. `tools/update_crates.py` refreshes it. New crates and cases don't need it. |
| `data/release_dates.json` | Release dates for existing items. Items newer than this list are dated by their case, store date, or the day the app first saw them. Maintainers can run `tools/update_release_dates.py` to add exact dates. |

Pull requests to `curation.json` are the easiest way to help, for example when an item is wrongly marked obtainable.

## Reskins, Botkillers and Festives

A weapon counts as a reskin when its stats are identical to an earlier weapon or the stock one (the Frying Pan, Saxxy, Nessie's Nine Iron, the Big Kill...). That's checked automatically from the game files; `reskins` and `not_reskins` in `curation.json` fix the cases it gets wrong. "Hide Festives" hides every Festive weapon.

## How "unobtainable" is decided

An item counts as unobtainable when it **can't be traded** and **isn't given out any more**:

- Every community and tournament medal is unobtainable.
- An untradable cosmetic or taunt released more than a year ago is unobtainable, unless `curation.json` lists it as still earnable. Gibuses, dueling badges, MvM badges, achievement hats like the JACK hats, and the Birthday Hat are on that list.
- Tradable items always count as obtainable, because you can trade for them, even from retired cases.

## Project layout

```
tf2_catalog.py      entry point
tf2c/catalog.py       builds the item list from items_game.txt + localization
tf2c/vpk.py           reads textures out of TF2's VPK archives
tf2c/locate.py        finds the TF2 install on Windows/macOS/Linux
tf2c/steam.py         reads a public backpack from Steam
tf2c/server.py        local web server
tf2c/sources.py       downloads TF2 item files when TF2 isn't installed
tf2c/icons.py         picks an icon source per item
tf2c/wikidata.py      quality lists and Market flags from the TF2 Wiki
web/index.html        the interface
web/ui, web/fonts     TF2 interface art and fonts
web/sounds            TF2 UI and backpack sounds
data/                 curation lists and release dates
assets/tf2catalog.ico the app / .exe icon
tools/                maintainer scripts for release dates, wiki data and old crates
```

## Legal

The interface art in `web/ui/`, the fonts in `web/fonts/` and the sounds in `web/sounds/` come from Team Fortress 2 and belong to Valve. They're included under the Source SDK 2013 license terms, which only cover free, non-commercial projects, so keep it free. Item icons aren't bundled: they load from Steam, the TF2 Wiki or your own install. Team Fortress, Steam and their logos are trademarks of Valve Corporation. This project isn't affiliated with or endorsed by Valve. The code is MIT licensed.
