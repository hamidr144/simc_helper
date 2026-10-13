# Armory fixtures (t_234f51f3 research, captured 2026-10-13)

Real responses from the new "worldsoul" Armory `model.json` endpoint —
public character data, no auth required. Tests must use these instead of
hitting Blizzard live.

| File | Source |
|---|---|
| `armory_model_hamidriel_eu.json` | `GET https://worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/character/draenor/Hamidriel/model.json` (90 BE Ret Paladin, Horde, 15 gear slots, ilvls 321-334, enchants + bonus lists) |
| `armory_model_onryo_us.json` | `GET https://worldofwarcraft.blizzard.com/en-us/worldsoul/us/armory/character/illidan/onry%C3%B4/model.json` (90 Human Holy Paladin, US region, unicode name, 18 slots incl. `offhand`/`shirt`/`tabard`, PvP gear) |
| `armory_model_hamidriel_achievements_tab.json` | `GET .../Hamidriel/achievements/model.json` — shows the per-tab `model.json` pattern |
| `error_500_unknown_character.txt` | `GET .../draenor/NotACharacter12345` — unknown characters return **HTTP 500** (not 404) with this HTML error page |

Trimming applied (structure otherwise byte-faithful): removed
`character.specs` (150 KB per-spec dumps), `character.pve`,
`character.mythicKeystoneDungeons` (top-level list kept to 2 entries),
duplicated `media.content._links`; compact JSON.

Regenerate with curl + the trim logic in kanban task t_234f51f3 if the
schema ever changes.
