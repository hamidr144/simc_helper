"""Heuristic per-class stat weights for the gear-list "Stat priority" sort.

The weights in ``data/stat_priorities.json`` are a coarse, DPS-leaning
ordering — they exist so the candidate list can be scanned quickly, not to
replace a sim. The UI must label the sort as a heuristic (the data file
carries ``"heuristic": true`` so the frontend can assert on it).

Scoring is a plain weighted sum over the stat lines parsed from a Wowhead
tooltip (``parse_wowhead_tooltip``). Labels not in the weight table count as
zero; combined labels like ``Strength or Intellect`` fall back to the maximum
of their parts, which is the optimistic reading for the wearer.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

DATA_FILE = Path(__file__).resolve().parent / "data" / "stat_priorities.json"


@lru_cache(maxsize=1)
def load_stat_priorities(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or DATA_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalise(label: Any) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip().lower()


def weights_for_class(char_class: Optional[str]) -> Dict[str, float]:
    """Lower-cased stat label -> weight for *char_class*, merged over defaults."""
    data = load_stat_priorities()
    weights = {
        _normalise(label): float(weight)
        for label, weight in (data.get("default_weights") or {}).items()
    }
    entry = (data.get("classes") or {}).get(str(char_class or "").strip().lower()) or {}
    for label, weight in (entry.get("weights") or {}).items():
        weights[_normalise(label)] = float(weight)
    return weights


def score_stats(
    stats: Optional[Iterable[Mapping[str, Any]]], weights: Mapping[str, float]
) -> float:
    """Weighted sum of tooltip stats; unknown labels count as zero."""
    total = 0.0
    for stat in stats or []:
        label = _normalise(stat.get("label"))
        if not label:
            continue
        weight = weights.get(label)
        if weight is None and " or " in label:
            weight = max(
                (weights.get(part.strip(), 0.0) for part in label.split(" or ")),
                default=0.0,
            )
        try:
            value = float(stat.get("value") or 0)
        except (TypeError, ValueError):
            value = 0.0
        total += value * float(weight or 0.0)
    return round(total, 1)
