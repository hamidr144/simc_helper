"""Season-aware gear-upgrade data for Midnight.

All track ladders, ascension (Voidforged/Venomforged) transforms, crest
currency ids, and per-rank costs live in ``data/upgrade_seasons.json`` —
one entry per season — so a new season is a data-file change, not a code
change.  The SimC engine resolves item stats from its own game data via
``bonus_id``/``ilevel``; this module only powers the UI ladders and the
``ilevel=`` overrides we inject into generated profiles.

Sources (verified 2026-10-13):
- S2 ladders + above-6/6 ilvls (337/340/344): live game DB configs embedded
  in SimC (engine/dbc/generated/item_scaling.inc, build 12.1.0.69933) and
  https://www.wowhead.com/guide/midnight/item-level-gear-upgrades-dawncrests
- Ascendant Venomforged results (Hero 328 / Myth 340, crafted 325/338,
  Venomstone item 280562, cost 10, necklaces added):
  https://www.wowhead.com/guide/midnight/bonus-rolls-item-upgrades
- Crest currency ids: https://github.com/simulationcraft/simc-addon extras.lua
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DATA_FILE = Path(__file__).resolve().parent / "data" / "upgrade_seasons.json"


@lru_cache(maxsize=1)
def load_upgrade_seasons(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or DATA_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_season(season_id: Optional[str] = None) -> Dict[str, Any]:
    """Return the season dataset for *season_id*, defaulting to the active one."""
    data = load_upgrade_seasons()
    seasons: List[Dict[str, Any]] = data.get("seasons", [])
    if season_id:
        for season in seasons:
            if season.get("id") == season_id:
                return season
    for season in seasons:
        if season.get("id") == data.get("active_season"):
            return season
    return seasons[-1] if seasons else {}


def detect_season(ilvls: Iterable[Optional[int]]) -> Dict[str, Any]:
    """Pick the season that best explains the observed item levels.

    Live-first: if the top ilvl falls inside the *active* season's band,
    that season wins (live players wear current-season gear; overlapping
    ilvls like 276 exist in both S1 and S2 ladders).  Only when the top
    ilvl sits below the active band do we resolve against older seasons,
    so archived exports keep working.  Unknown values fall back to active.
    """
    values = [int(level) for level in ilvls if isinstance(level, (int, float)) or (
        isinstance(level, str) and str(level).isdigit())]
    values = [int(v) for v in values]
    data = load_upgrade_seasons()
    seasons: List[Dict[str, Any]] = data.get("seasons", [])
    if values and seasons:
        top = max(values)
        active = get_season()
        band = active.get("ilvl_band") or [0, 0]
        if band[0] <= top <= band[1]:
            return active
        matches = [s for s in seasons if (s.get("ilvl_band") or [0, 0])[0] <= top <= s["ilvl_band"][1]]
        if matches:
            return max(matches, key=lambda s: s["ilvl_band"][1])
    return get_season()


def track_levels(season: Dict[str, Any], track: Optional[str]) -> List[int]:
    if not season or not track:
        return []
    return list((season.get("tracks") or {}).get(str(track).lower(), []))


def track_level(season: Dict[str, Any], track: Optional[str], rank: Any) -> Optional[int]:
    levels = track_levels(season, track)
    if not levels:
        return None
    try:
        rank_int = int(rank)
    except (TypeError, ValueError):
        return None
    if rank_int < 1 or rank_int > len(levels):
        return None
    return levels[rank_int - 1]


def find_track_for_level(season: Dict[str, Any], level: int) -> Optional[Dict[str, Any]]:
    """Inverse lookup: which track/rank does this ilvl correspond to?"""
    for track, levels in (season.get("tracks") or {}).items():
        if level in levels:
            return {"track": track, "rank": levels.index(level) + 1, "item_level": level}
    return None


def ascension_for(season: Dict[str, Any]) -> Dict[str, Any]:
    return season.get("ascension") or {}


def is_ascension_eligible_slot(season: Dict[str, Any], slot: Optional[str]) -> bool:
    ascension = ascension_for(season)
    if not ascension:
        return False
    base = str(slot or "").split("_")[0]
    slots = {str(s).split("_")[0] for s in ascension.get("eligible_slots", [])}
    return base in slots


def ascension_result(season: Dict[str, Any], track: Optional[str], crafted: bool = False) -> Optional[int]:
    """Absolute ascended ilvl for a track (hero/myth), or None if not eligible.

    A max-quality crafted base ascends to a lower ilvl than a track item
    (``crafted_results``); fall back to the track ``results`` when the season
    defines no crafted value.
    """
    ascension = ascension_for(season)
    if not ascension or not track:
        return None
    track_key = str(track).lower()
    if crafted:
        crafted_result = (ascension.get("crafted_results") or {}).get(track_key)
        if crafted_result is not None:
            return crafted_result
    return (ascension.get("results") or {}).get(track_key)


def is_elevated(season: Dict[str, Any], level: Optional[int]) -> bool:
    """True for above-track items that cannot be upgraded further (e.g. 344)."""
    if level is None:
        return False
    try:
        return int(level) in set(season.get("elevated_ilvls") or [])
    except (TypeError, ValueError):
        return False


def season_payload() -> Dict[str, Any]:
    """Everything the web UI needs in one response."""
    data = load_upgrade_seasons()
    return {
        "schema_version": data.get("schema_version"),
        "active_season": data.get("active_season"),
        "seasons": data.get("seasons", []),
    }
