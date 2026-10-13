"""WoW Armory (worldsoul) character loading — Step 7.

Loads a character + equipped gear from the new "worldsoul" Armory's own
public XHR endpoint (no auth, no Blizzard API keys — the official Game
Data/Profile APIs are dead as of 2026; see
``~/Hermes-work/wow-armory-api-guide.md`` for the full research):

    GET https://worldofwarcraft.blizzard.com/{locale}/worldsoul/{region}/
        armory/character/{realmSlug}/{name}/model.json

Key facts pinned by that research (verified live 2026-10-13):

- Item / bonus / enchant ids are in the same id space as Wowhead and SimC —
  no resolution needed; parse ids only, ignore display strings.
- ``character.gear`` is an OBJECT keyed by camelCase slot names with a
  variable slot set — iterate keys, never assume a fixed count.
- ``shirt``/``tabard`` carry ilvl-1 cosmetics and must be skipped or the
  SimC engine chokes.
- Unknown character / wrong region returns HTTP **500** (not 404) with an
  HTML error page that can even carry an ``application/json`` content type.
  Success is discriminated by JSON parse + presence of ``.character.gear``,
  never by status code or content type alone.  Retry once on 5xx, then
  report "character not found".
- Client timeout >= 10 s, custom User-Agent, server-side fetch only.
- Our own server-side cache TTL: 10 minutes, keyed by region/realm/name
  (the upstream itself sends ``cache-control: max-age=60``).

The parsed result is returned in the same shape ``/api/parse-addon``
returns (``base_profile`` / ``equipped_gear`` / ``items_by_slot`` /
``item_names`` / ``char_name`` / ``char_class`` / ``item_upgrades`` /
``warnings``) so the frontend can treat both sources identically.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

import httpx

logger = logging.getLogger("master")

ARMORY_BASE_URL = "https://worldofwarcraft.blizzard.com"
ARMORY_LOCALE = "en-gb"  # ids are locale-independent; only strings localize
ARMORY_REGIONS = ("eu", "us", "kr", "tw")
ARMORY_USER_AGENT = "simc-helper/1.0 (+personal gear comparison tool; contact: self-hosted)"
ARMORY_TIMEOUT_SECONDS = 12.0  # guide: observed 0.4-4.2 s, use >= 10 s
ARMORY_CACHE_TTL_SECONDS = 600  # 10 minutes (spec supersedes the ~5 min note)
ARMORY_CACHE_MAX_ENTRIES = 128

# Armory camelCase gear key -> SimC slot name (guide §4.2).
ARMORY_SLOT_MAP = {
    "head": "head",
    "neck": "neck",
    "shoulder": "shoulder",
    "back": "back",
    "chest": "chest",
    "wrist": "wrist",
    "hand": "hands",
    "waist": "waist",
    "leg": "legs",
    "foot": "feet",
    "leftFinger": "finger1",
    "rightFinger": "finger2",
    "leftTrinket": "trinket1",
    "rightTrinket": "trinket2",
    "weapon": "main_hand",
    "offhand": "off_hand",
}

# Cosmetic slots (ilvl 1 shirt/tabard) — SimC cannot consume them.
ARMORY_COSMETIC_SLOTS = frozenset({"shirt", "tabard"})

# ---------------------------------------------------------------------------
# Errors — mapped to HTTP codes by the /api/armory-load endpoint
# ---------------------------------------------------------------------------


class ArmoryError(Exception):
    """Base class for Armory loading failures with a user-readable message."""


class ArmoryInputError(ArmoryError):
    """The user's input (URL / name / realm / region) is invalid."""


class ArmoryNotFoundError(ArmoryError):
    """Character not found (unknown name, wrong region, wrong realm)."""


class ArmoryRateLimitedError(ArmoryError):
    """The Armory answered 429 — back off."""


class ArmoryUnavailableError(ArmoryError):
    """The Armory could not be reached (connection error or timeout)."""


class ArmoryParseError(ArmoryError):
    """The Armory answered but with unexpected data."""


# ---------------------------------------------------------------------------
# Input parsing: URL / Name-Realm / Name, Realm -> (region, realmSlug, name)
# ---------------------------------------------------------------------------

_WORLD_SOUL_URL_RE = re.compile(
    r"^(?:https?://)?worldofwarcraft\.blizzard\.com/"
    r"(?P<locale>[A-Za-z]{2}-[A-Za-z]{2})/worldsoul/(?P<region>eu|us|kr|tw)/"
    r"armory/character/(?P<realm>[^/]+)/(?P<name>[^/?#]+)",
    re.IGNORECASE,
)

# Legacy battle.net profile URL, e.g.
# https://eu.battle.net/wow/en/character/draenor/Hamidriel/advanced
_LEGACY_URL_RE = re.compile(
    r"^(?:https?://)?(?P<region>eu|us|kr|tw)\.battle\.net/wow/"
    r"(?:[A-Za-z]{2}(?:-[A-Za-z]{2})?/)?character/(?P<realm>[^/]+)/(?P<name>[^/?#]+)",
    re.IGNORECASE,
)


def slugify_realm(realm: str) -> str:
    """Turn free-text realm text into an Armory realm slug.

    Rules verified live (guide §3.1/§6): lowercase, apostrophes (both
    ``'`` and ``’``) REMOVED (``Kel'Thuzad`` -> ``kelthuzad``), runs of any
    other non-alphanumeric characters (spaces included) collapse to ``-``
    (``Area 52`` -> ``area-52``).
    """
    text = str(realm or "").strip().lower()
    text = text.replace("'", "").replace("\u2019", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_armory_url(url: str) -> Tuple[str, str, str]:
    """Parse a full Armory profile URL into ``(region, realmSlug, name)``.

    Accepts the current worldsoul form (locale segment required upstream,
    optional ``/model.json`` suffix and query string tolerated) and the
    legacy ``{region}.battle.net/wow/.../character/{realm}/{name}`` form.
    Percent-encoded names are decoded (``onry%C3%B4`` -> ``Onryô``).
    """
    text = str(url or "").strip()
    for pattern in (_WORLD_SOUL_URL_RE, _LEGACY_URL_RE):
        match = pattern.match(text)
        if match:
            return (
                match.group("region").lower(),
                slugify_realm(unquote(match.group("realm"))),
                unquote(match.group("name")),
            )
    raise ArmoryInputError(
        "That does not look like an Armory URL. Paste a link like "
        "worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/character/realm/Name"
    )


def parse_name_realm(text: str) -> Tuple[str, str]:
    """Split ``Name-Realm`` or ``Name, Realm`` free text into ``(name, realm)``.

    WoW character names never contain dashes or commas, while realm slugs
    can contain dashes (``area-52``), so the FIRST separator wins:
    ``Hamidriel-Draenor`` -> (Hamidriel, Draenor),
    ``Name-Area-52`` -> (Name, Area-52).
    """
    value = str(text or "").strip()
    separator = "," if "," in value else "-" if "-" in value else None
    if separator is None:
        raise ArmoryInputError(
            "Enter your character with its realm, e.g. Name-Realm or Name, Realm"
        )
    name, _, realm = value.partition(separator)
    name, realm = name.strip(), realm.strip()
    if not name or not realm:
        raise ArmoryInputError(
            "Enter your character with its realm, e.g. Name-Realm or Name, Realm"
        )
    return name, realm


def parse_armory_input(
    url: Optional[str] = None,
    name: Optional[str] = None,
    realm: Optional[str] = None,
    region: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Resolve user input into ``(region, realmSlug, name)``.

    A full Armory URL wins over name/realm fields (its region wins too).
    Region defaults to ``eu``.  Raises :class:`ArmoryInputError` with a
    message the UI can show verbatim.
    """
    text = str(url or "").strip()
    if text:
        if re.match(r"^https?://", text, re.IGNORECASE) or "battle.net/" in text or "blizzard.com/" in text:
            return parse_armory_url(text)
        # A bare "worldsoul/..." path fragment without scheme: still parse it.
        try:
            return parse_armory_url(text)
        except ArmoryInputError:
            # Not a URL after all — fall through to Name-Realm handling.
            name, realm = parse_name_realm(text)
            region = region or "eu"
            return _finish(region, realm, name)

    name = str(name or "").strip()
    realm = str(realm or "").strip()
    if name and not realm:
        # The single-input UI may hand us the whole "Name-Realm" string.
        name, realm = parse_name_realm(name)
    if not name or not realm:
        raise ArmoryInputError(
            "Enter your character with its realm, e.g. Name-Realm or Name, Realm"
        )
    return _finish(region or "eu", realm, name)


def _finish(region: str, realm: str, name: str) -> Tuple[str, str, str]:
    region = str(region or "eu").strip().lower()
    if region not in ARMORY_REGIONS:
        raise ArmoryInputError(
            f"Unknown Armory region '{region}'. Use one of: {', '.join(ARMORY_REGIONS)}"
        )
    realm_slug = slugify_realm(realm)
    if not realm_slug:
        raise ArmoryInputError("Enter your character with its realm, e.g. Name-Realm or Name, Realm")
    name = str(name).strip()
    if not name:
        raise ArmoryInputError("Enter your character name")
    return region, realm_slug, name


def build_model_url(region: str, realm_slug: str, name: str) -> str:
    """Full model.json URL; non-ASCII names are percent-encoded (Onryô -> onry%C3%B4).

    Note the ``/model.json`` suffix — WITHOUT it the URL is the SPA page
    (HTML, HTTP 200), which the success discriminator correctly rejects.
    """
    return (
        f"{ARMORY_BASE_URL}/{ARMORY_LOCALE}/worldsoul/{region}/armory/"
        f"character/{realm_slug}/{quote(name)}/model.json"
    )


# ---------------------------------------------------------------------------
# Fetching (server-side only) + TTL cache
# ---------------------------------------------------------------------------

# (region, realmSlug, lowercased name) -> (timestamp, payload)
armory_model_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}


async def _http_get(url: str) -> httpx.Response:
    """One upstream GET. Split out so tests can fake the transport."""
    async with httpx.AsyncClient(
        timeout=ARMORY_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": ARMORY_USER_AGENT},
    ) as client:
        return await client.get(url)


def _is_valid_model(payload: Any) -> bool:
    """Success discriminator: parsed JSON object carrying ``character.gear``."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("character"), dict)
        and isinstance(payload["character"].get("gear"), dict)
    )


async def fetch_armory_model(region: str, realm_slug: str, name: str) -> Dict[str, Any]:
    """Fetch one character's model.json with TTL cache, one 5xx retry and
    the guide's not-found discrimination (unknown characters return HTTP
    500 + HTML that may even claim to be JSON — never trust status/content
    type alone).
    """
    key = (region, slugify_realm(realm_slug), name.lower())
    realm_slug = slugify_realm(realm_slug)
    now = time.time()
    cached = armory_model_cache.get(key)
    if cached and now - cached[0] < ARMORY_CACHE_TTL_SECONDS:
        return cached[1]

    url = build_model_url(region, realm_slug, name)
    attempts = 2  # initial + one retry (5xx and transport errors are retried)
    last_status: Optional[int] = None

    for attempt in range(attempts):
        try:
            response = await _http_get(url)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            if attempt + 1 < attempts:
                logger.warning("Armory fetch error for %s/%s (%s), retrying: %s", region, realm_slug, name, exc)
                continue
            raise ArmoryUnavailableError(
                "The Armory could not be reached (timeout or connection error). Try again."
            ) from exc

        if response.status_code == 429:
            raise ArmoryRateLimitedError("The Armory is rate limiting us. Wait a minute and try again.")

        if response.status_code >= 500:
            # Unknown characters AND real server errors both land here; the
            # guide's recipe is one retry, then report "character not found".
            last_status = response.status_code
            if attempt + 1 < attempts:
                continue
            raise ArmoryNotFoundError(
                f"No character '{name}' found on realm {realm_slug} ({region.upper()}). "
                "Check the name, realm and region."
            )

        if response.status_code != 200:
            raise ArmoryNotFoundError(
                f"No character '{name}' found on realm {realm_slug} ({region.upper()}). "
                "Check the name, realm and region."
            )

        # 200: the ONLY success proof is JSON with .character.gear.
        try:
            payload = json.loads(response.text)
        except ValueError as exc:
            raise ArmoryNotFoundError(
                f"No character '{name}' found on realm {realm_slug} ({region.upper()}). "
                "Check the name, realm and region."
            ) from exc
        if not _is_valid_model(payload):
            raise ArmoryNotFoundError(
                f"No usable gear data for '{name}' on realm {realm_slug} ({region.upper()})."
            )
        if len(armory_model_cache) >= ARMORY_CACHE_MAX_ENTRIES:
            oldest = min(armory_model_cache, key=lambda cache_key: armory_model_cache[cache_key][0])
            del armory_model_cache[oldest]
        armory_model_cache[key] = (now, payload)
        return payload

    raise ArmoryNotFoundError(  # unreachable belt (loop always raises/returns)
        f"No character '{name}' found on realm {realm_slug} "
        f"({region.upper()}; upstream HTTP {last_status})."
    )


# ---------------------------------------------------------------------------
# Parsing model.json -> parse-addon-shaped result
# ---------------------------------------------------------------------------


def armory_item_string(item: Dict[str, Any]) -> str:
    """Build one SimC item details string (guide §5):

    ``id=<id>,bonus_id=<bonus_list joined '/'>,enchant_id=<first enchant>,ilevel=<level.value>``

    ``bonus_id=`` omitted for an empty bonus list, ``enchant_id=`` omitted
    for empty/absent enchantments.  Ids only — display strings are
    locale-dependent and ignored.
    """
    item_id = item.get("id")
    if not isinstance(item_id, int) or item_id <= 0:
        return ""
    parts = [f"id={item_id}"]

    bonus_ids = [
        str(int(bonus))
        for bonus in (item.get("bonus_list") or [])
        if isinstance(bonus, (int, float)) or str(bonus).isdigit()
    ]
    if bonus_ids:
        parts.append("bonus_id=" + "/".join(bonus_ids))

    enchantments = item.get("enchantments") or []
    if enchantments:
        first = enchantments[0] if isinstance(enchantments[0], dict) else None
        enchant_id = (first or {}).get("enchantment_id")
        if enchant_id is not None and str(enchant_id).isdigit():
            parts.append(f"enchant_id={int(enchant_id)}")

    level = (item.get("level") or {}).get("value") if isinstance(item.get("level"), dict) else None
    if isinstance(level, (int, float)):
        parts.append(f"ilevel={int(level)}")

    return ",".join(parts)


def _normalized_slot(slot: str) -> str:
    """Mirror the addon parser: finger1/finger2 -> finger, trinket1/2 -> trinket."""
    if slot.startswith("finger"):
        return "finger"
    if slot.startswith("trinket"):
        return "trinket"
    return slot


def parse_armory_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a model.json payload into the ``/api/parse-addon`` response shape.

    Unicode-safe throughout (guild names can be Cyrillic, names can be
    Onryô): everything stays Python str/JSON — no encoding round-trips.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("character"), dict):
        raise ArmoryParseError("The Armory returned unexpected data for this character.")
    character = payload["character"]

    if character.get("isRemix"):
        raise ArmoryInputError(
            f"'{character.get('name')}' is a Remix event character; its Armory gear "
            "cannot be simulated. Load a normal character instead."
        )

    warnings: List[str] = []
    if character.get("isOutdated"):
        warnings.append("The Armory marks this character as outdated — the gear shown may be stale.")

    char_name = str(character.get("name") or "Unknown")
    char_class = str((character.get("class") or {}).get("slug") or "unknown").lower()
    char_spec = str((character.get("spec") or {}).get("slug") or "").lower()
    race_slug = str((character.get("race") or {}).get("slug") or "").lower()
    char_race = race_slug.replace("-", "_") if race_slug else ""
    char_level = character.get("level")
    char_ilvl = character.get("averageItemLevel")

    gear = character.get("gear") or {}
    equipped_gear: Dict[str, str] = {}
    items_by_slot: Dict[str, List[str]] = {}
    item_names: Dict[str, str] = {}

    for slot_key, item in gear.items():
        if slot_key in ARMORY_COSMETIC_SLOTS:
            continue  # ilvl-1 shirt/tabard — SimC chokes on them
        slot = ARMORY_SLOT_MAP.get(slot_key)
        if not slot or not isinstance(item, dict):
            continue  # unknown slot key: skip, never assume the set
        details = armory_item_string(item)
        if not details:
            continue
        equipped_gear[slot] = details
        norm_slot = _normalized_slot(slot)
        if details not in items_by_slot.setdefault(norm_slot, []):
            items_by_slot[norm_slot].append(details)
            item_name = str(item.get("name") or f"Item {item.get('id')}")
            level = (item.get("level") or {}).get("value") if isinstance(item.get("level"), dict) else None
            item_names[details] = f"{item_name} ({int(level)})" if isinstance(level, (int, float)) else item_name

    if not equipped_gear:
        raise ArmoryParseError(f"The Armory reported no usable gear for '{char_name}'.")

    base_lines = [f'{char_class}="{char_name}"']
    if isinstance(char_level, int):
        base_lines.append(f"level={char_level}")
    if char_race:
        base_lines.append(f"race={char_race}")
    if char_spec:
        base_lines.append(f"spec={char_spec}")

    return {
        "base_profile": "\n".join(base_lines),
        "equipped_gear": equipped_gear,
        "items_by_slot": items_by_slot,
        "item_names": item_names,
        "char_name": char_name,
        "char_class": char_class,
        "char_spec": char_spec,
        "char_ilvl": char_ilvl,
        "item_upgrades": {},
        "warnings": warnings,
    }
