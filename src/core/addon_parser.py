import re
from typing import Any, Dict, List, Optional, Tuple

SLOTS = [
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger1", "finger2", "trinket1", "trinket2",
    "main_hand", "off_hand",
]
CLASSES = {
    "deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk",
    "paladin", "priest", "rogue", "shaman", "warlock", "warrior",
}

# Addon ``# upgrade_levels=`` comment grammar, verified against the real
# simc-addon source (github.com/simulationcraft/simc-addon, core.lua master,
# getUpgradeComment/formatCosts, fetched 2026-10-13).  The addon emits the
# comment right after the item-name comment and before the item line, only
# in ``/simc debug`` output while an upgrade vendor is open:
#
#   upgrade_levels=<levelStr>[/<levelStr>...]
#   <levelStr> = upgradeLevel:itemLevelIncrement:currencyCosts:itemCosts
#   <currencyCosts> = "" | "c#<currencyId>#<count>#<discounted01>"[,...]
#   <itemCosts>     = "" | "i#<itemId>#<count>#<discounted01>"[,...]
#
# Increments are relative to the item's *current* ilvl, and the addon
# excludes the item's own current upgrade level from the list.
_UPGRADE_COMMENT_RE = re.compile(r"^#\s*upgrade_levels=(.*)$")
_UPGRADE_COST_RE = re.compile(r"^([ci])#(\d+)#(\d+)#([01])$")

# ---------------------------------------------------------------------------
# WoW: Forever export detection
#
# WoW: Forever (launch 2026-11-04) is a separate game with its own level-60
# gear economy and its own SimulationCraft engine branch
# (github.com/simulationcraft/simc, branch "forever" — see also the
# data-update-foreverBeta-* branches).  Our engine is the retail (Midnight)
# nightly and cannot simulate Forever characters, so reject those exports
# with a clear error instead of producing garbage sims.
#
# The official addon gained experimental Forever support (simc-addon release
# #124, commit 703bc5c).  core.lua (master, fetched 2026-10-13) detects the
# client via Forever-only APIs (IS_FOREVER, ~line 78) and gates whole export
# sections through EXPORTS: FOREVER_EXPORTS = {character_stats, skills, buffs}
# vs MODERN_EXPORTS = {spec, trait_systems, catalyst_currencies, ...}.  The
# Forever-only sections are emitted as comment lines and NEVER appear in a
# retail export (core.lua GetSimcProfile, ~lines 1477-1500; forever/stats.lua):
#
#   # skills=<skillID>:<rank>:<modifier>:<maxRank>[/...]      (GetSkillLevels)
#   # buffs=<spellID>:<stacks>[/<spellID>:<stacks>...]        (GetActiveBuffs)
#   # character_stats=<name>:<value>/...                      (+ _base/_bonus/_gear)
#   # attack_power= / spell_power= / spell_stats= / regen= / crit= / hit= /
#   # haste= / combat_modifiers= / combat_ratings= / defense= / resistances= /
#   # weapon_damage= / pet_*=                                 (GetCharacterStats)
#
# The IS_FOREVER branch additionally emits per-spec-group talent blocks under
# "# Primary Talents" / "# Secondary Talents" comment headers (core.lua
# 1207-1230, groupLabels at 1221-1229); no retail code path ever writes those
# headers.
#
# Additionally, Forever exports always write bare ``spec=unknown`` and never
# the ``# loot_spec=`` comment (EXPORTS.spec is retail-only; core.lua ~1201),
# and the Forever client's interface TOC is 16001 while retail Midnight TOCs
# are 1201xx (Simulationcraft.toc: "Interface: 120100, 120105, 16001").
#
# Hard rejection uses only the explicit Forever-only comment markers above
# (with value grammars required for the generically-named keys so a stray
# retail comment can never trip them).  The spec/TOC signals are soft: they
# only produce warnings, never a 400.  As a belt for hand-edited or mixed
# exports, any retail-only marker (``# loot_spec=``, ``omnium_talents=``,
# ``# bonus_roll_items=``/``# bonus_roll_currencies=`` — all gated behind
# MODERN_EXPORTS, core.lua 83-101) overrides detection: such an export is
# treated as retail no matter which Forever keys it also carries.
# ---------------------------------------------------------------------------

FOREVER_EXPORT_MESSAGE = (
    "This looks like a WoW: Forever export. This tool only simulates "
    "Midnight (retail) characters."
)

_FOREVER_HARD_RES = [
    # Forever-only "# skills=" block; grammar from forever/stats.lua GetSkillLevels.
    re.compile(r"^#\s*skills=\d+:\d+:\d+:\d+(?:/\d+:\d+:\d+:\d+)*\s*$"),
    # Forever-only "# buffs=" block; grammar from forever/stats.lua GetActiveBuffs.
    re.compile(r"^#\s*buffs=\d+:\d+(?:/\d+:\d+)*\s*$"),
    # Forever-only character stats block (forever/stats.lua AddPrimaryStats/AddGearStats).
    re.compile(r"^#\s*character_stats(?:_base|_bonus|_gear)?="),
    # Forever-only pet mirror of the same block (forever/stats.lua AddPet*).
    re.compile(r"^#\s*pet_(?:info|stats|stats_base|stats_bonus|attack_power|modifiers|defense|resistances|weapon_damage)="),
    # Forever-only per-spec-group talent headers, emitted only in the
    # IS_FOREVER branch (core.lua 1207-1230; groupLabels = { 'Primary',
    # 'Secondary' } at 1221, header written at 1227).  Retail code paths
    # never write "# <label> Talents" comment lines.
    re.compile(r"^#\s*(?:Primary|Secondary) Talents\s*$"),
    # Remaining forever/stats.lua keys; the generic names require the addon's
    # "name:value" value shape so free-text retail comments never match.
    re.compile(
        r"^#\s*(?:attack_power|spell_power|spell_stats|regen|crit|hit|haste"
        r"|combat_modifiers|combat_ratings|defense|resistances|weapon_damage)"
        r"=[a-z_][a-z0-9_]*:"
    ),
]

# Retail-only markers (MODERN_EXPORTS-gated, core.lua 83-101: 'spec' writes
# the "# loot_spec=" comment at ~1203, 'trait_systems' writes omnium_talents,
# 'bonus_roll_items'/'bonus_roll_currencies' write the matching comments at
# 1462-1472).  The Forever client never emits any of them, so their presence
# means the export came from a retail client; if one shows up alongside
# Forever keys (hand-edited or mixed export) we treat it as retail and never
# hard-reject.
_RETAIL_OVERRIDE_RES = [
    re.compile(r"^#\s*loot_spec="),
    re.compile(r"^omnium_talents="),
    re.compile(r"^#\s*bonus_roll_(?:items|currencies)="),
]

# Forever client TOC is 16001 (Simulationcraft.toc compat list); retail
# Midnight TOCs are 1201xx (six digits).  Anything below this in the header
# is not a modern retail client.
_FOREVER_TOC_MAX = 100_000
_TOC_COMMENT_RE = re.compile(r"^#\s*WoW\s+\S+,\s*TOC\s+(\d+)\s*$")
_LOOT_SPEC_COMMENT_RE = re.compile(r"^#\s*loot_spec=")
_SPEC_OPTION_RE = re.compile(r"^spec=([A-Za-z_]+)\s*$")


def is_forever_export(lines: List[str]) -> bool:
    """True when the export carries explicit WoW: Forever markers.

    Only the Forever-only comment sections emitted by the official addon
    (gated behind EXPORTS.character_stats/skills/buffs and the IS_FOREVER
    talent block, Forever client only) trigger this; see the rationale block
    above.  Normal retail exports never contain these lines.

    Any retail-only marker (``# loot_spec=``, ``omnium_talents=``,
    ``# bonus_roll_*=``) overrides the Forever keys: mixed or hand-edited
    exports that still carry a retail marker are treated as retail and never
    hard-rejected.
    """
    lines_strip = [line.strip() for line in lines]
    # Full-scan override: a retail marker anywhere in the export wins, even
    # if Forever keys appear earlier in a hand-edited/mixed file.
    if any(
        pattern.match(line) for line in lines_strip for pattern in _RETAIL_OVERRIDE_RES
    ):
        return False
    return any(
        pattern.match(line) for line in lines_strip for pattern in _FOREVER_HARD_RES
    )


def forever_export_warnings(lines: List[str]) -> List[str]:
    """Soft WoW: Forever signals; warnings only, never a hard reject.

    A retail export can legitimately look weak on any single one of these
    (e.g. a character without a spec yet), so they only annotate an otherwise
    successful parse.
    """
    warnings: List[str] = []
    has_loot_spec_comment = False
    spec_unknown = False
    for line in lines:
        line_strip = line.strip()
        toc_match = _TOC_COMMENT_RE.match(line_strip)
        if toc_match:
            toc = int(toc_match.group(1))
            if toc <= _FOREVER_TOC_MAX:
                warnings.append(
                    f"Export header shows client TOC {toc}, which is not a "
                    "Midnight (retail) build — if this is a WoW: Forever "
                    "character, this tool cannot simulate it."
                )
            continue
        if _LOOT_SPEC_COMMENT_RE.match(line_strip):
            has_loot_spec_comment = True
            continue
        spec_match = _SPEC_OPTION_RE.match(line_strip)
        if spec_match and spec_match.group(1).lower() == "unknown":
            spec_unknown = True
    if spec_unknown and not has_loot_spec_comment:
        warnings.append(
            "Export has spec=unknown and no '# loot_spec=' comment, which "
            "matches a WoW: Forever export; retail exports always include a "
            "spec comment."
        )
    return warnings


def parse_upgrade_levels(value: str) -> Optional[Dict[str, Any]]:
    """Parse the value of an addon ``upgrade_levels=`` comment.

    Returns ``{"levels": [...]}`` with one entry per upgrade level
    (``upgrade_level``, ``ilvl_increment``, ``currency_costs``,
    ``item_costs``), or ``None`` when nothing valid can be salvaged.
    Malformed individual levels are skipped; parsing never raises.
    """
    levels: List[Dict[str, Any]] = []
    for segment in str(value or "").split("/"):
        if not segment:
            continue
        parts = segment.split(":")
        if len(parts) != 4:
            continue
        try:
            upgrade_level = int(parts[0])
            ilvl_increment = int(parts[1])
        except ValueError:
            continue
        currency_costs: List[Dict[str, Any]] = []
        item_costs: List[Dict[str, Any]] = []
        malformed = False
        for kind, raw, bucket in (
            ("c", parts[2], currency_costs),
            ("i", parts[3], item_costs),
        ):
            for cost_str in filter(None, raw.split(",")):
                match = _UPGRADE_COST_RE.match(cost_str)
                if not match or match.group(1) != kind:
                    malformed = True
                    break
                bucket.append({
                    "id": int(match.group(2)),
                    "count": int(match.group(3)),
                    "discounted": match.group(4) == "1",
                })
            if malformed:
                break
        if malformed:
            continue
        levels.append({
            "upgrade_level": upgrade_level,
            "ilvl_increment": ilvl_increment,
            "currency_costs": currency_costs,
            "item_costs": item_costs,
        })
    return {"levels": levels} if levels else None


def parse_addon_lines(lines: List[str]) -> Tuple[str, Dict[str, str], Dict[str, List[str]], Dict[str, str], str, str, Dict[str, Dict[str, Any]]]:
    base_profile = []
    items_by_slot: Dict[str, List[str]] = {}
    item_names: Dict[str, str] = {}
    equipped_gear: Dict[str, str] = {}
    item_upgrades: Dict[str, Dict[str, Any]] = {}
    char_name = "Unknown"
    char_class = "Unknown"
    current_name_comment = ""
    current_upgrade: Optional[Dict[str, Any]] = None
    in_bags = False
    in_copy = False
    valid_slots = set(SLOTS) | {"finger", "trinket"}

    def preserve_line(raw_line: str) -> str:
        return raw_line if raw_line.endswith("\n") else raw_line + "\n"

    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("copy="):
            # TG3-D2: an embedded copy= block is a candidate from a previous
            # generation, not baseline state. Keep it out of base_profile and
            # equipped_gear; its gear lines still feed items_by_slot below
            # (SimC binds directives after copy= to the clone, last-actor
            # semantics — carrying them over hijacks the baseline).
            in_copy = True
            continue
        if not line_strip:
            in_copy = False
            continue
        upgrade_match = _UPGRADE_COMMENT_RE.match(line_strip)
        if upgrade_match:
            # Attach to the item line that follows; never a name comment,
            # never part of the base profile.
            current_upgrade = parse_upgrade_levels(upgrade_match.group(1))
            continue
        if line_strip.startswith("# ") and not re.match(r"^#\s+\w+=", line_strip):
            current_name_comment = line_strip[2:]
            current_upgrade = None

        name_match = re.match(r"^(\w+)=[\"']?([^\"'\s,]+)[\"']?$", line_strip)
        if name_match:
            key, val = name_match.groups()
            if key.lower() in CLASSES:
                char_class, char_name = key, val
                base_profile.append(preserve_line(line))
                continue

        if line_strip == "### Gear from Bags":
            in_bags = True
            continue
        if line_strip == "### Additional Character Info":
            break

        if not in_bags:
            match = re.match(r"^(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                if slot in SLOTS:
                    if not in_copy:
                        equipped_gear[slot] = details
                    norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                    items_by_slot.setdefault(norm_slot, [])
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment
                    if current_upgrade:
                        item_upgrades.setdefault(details, current_upgrade)
                current_upgrade = None
            if not in_copy and not any(line_strip.startswith(s + "=") for s in SLOTS):
                base_profile.append(preserve_line(line))
        else:
            match = re.match(r"^#\s+(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                if norm_slot in valid_slots:
                    items_by_slot.setdefault(norm_slot, [])
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment
                    if current_upgrade:
                        item_upgrades.setdefault(details, current_upgrade)
                current_upgrade = None

    return "".join(base_profile), equipped_gear, items_by_slot, item_names, char_name, char_class, item_upgrades


def count_embedded_copies(lines: List[str]) -> int:
    """Number of embedded ``copy=`` blocks in raw upload text."""
    return sum(1 for line in lines if line.strip().startswith("copy="))


def strip_embedded_copies(text: str) -> Tuple[str, int]:
    """Drop ``copy=`` lines and their override lines from a profile body.

    TG3-D2: SimC binds directives after a ``copy=`` line to that clone
    (last-actor semantics), so embedded copies carried in a caller-supplied
    base profile would hijack the baseline gear block generate-simc appends.
    Returns ``(clean_text, count)``. Blocks end at the next blank line — the
    format the app itself emits; a copy block without trailing blank line
    swallows its directives only, which is still the safe bound.
    """
    lines = text.splitlines(keepends=True)
    count = count_embedded_copies(lines)
    if not count:
        return text, 0
    kept: List[str] = []
    in_copy = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("copy="):
            in_copy = True
            continue
        if in_copy:
            in_copy = bool(stripped)
            continue
        kept.append(line)
    return "".join(kept), count
