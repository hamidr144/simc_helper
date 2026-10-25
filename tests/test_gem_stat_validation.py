"""t_d671cd7c directive 3: gem `stat` classification config validation.

The season config's gem records gained an optional ``stat`` field (the gear
page splits gems into one column per secondary stat). Normalization happens
at the single season-config load edge (generate_input.load_config): aliases
fold to canonical values, anything unknown is dropped so the frontend falls
back to its 'Other' column.
"""
import json

from src.cli.generate_input import GEM_STATS, load_config, normalize_gem_stats


def _config(gems):
    return {"enchantments": {}, "gems": gems, "max_concurrent_jobs": 1}


def test_canonical_values_survive():
    config = _config({"standard": [
        {"id": 1, "name": "a", "stat": "mastery"},
        {"id": 2, "name": "b", "stat": "crit"},
        {"id": 3, "name": "c", "stat": "versatility"},
        {"id": 4, "name": "d", "stat": "haste"},
    ]})
    normalize_gem_stats(config)
    assert [g["stat"] for g in config["gems"]["standard"]] == [
        "mastery", "crit", "versatility", "haste"]


def test_aliases_and_casing_fold_to_canonical():
    config = _config({"standard": [
        {"id": 1, "name": "a", "stat": "Critical Strike"},
        {"id": 2, "name": "b", "stat": "CRITICAL_STRIKE"},
        {"id": 3, "name": "c", "stat": "Crit-Strike"},
        {"id": 4, "name": "d", "stat": " Haste "},
    ]})
    normalize_gem_stats(config)
    assert [g["stat"] for g in config["gems"]["standard"]] == ["crit", "crit", "crit", "haste"]


def test_unknown_or_missing_stat_is_dropped_not_invented():
    config = _config({"standard": [
        {"id": 1, "name": "a", "stat": "spellpower"},
        {"id": 2, "name": "b", "stat": None},
        {"id": 3, "name": "c"},
    ], "meta": [{"id": 4, "name": "m", "stat": "Chaos"}]})
    normalize_gem_stats(config)
    assert all("stat" not in gem for gem in config["gems"]["standard"])
    assert "stat" not in config["gems"]["meta"][0]


def test_non_dict_records_tolerated():
    config = _config({"standard": [7, None, {"id": 1, "stat": "crit"}]})
    normalize_gem_stats(config)
    assert config["gems"]["standard"][2]["stat"] == "crit"


def test_load_config_normalizes_at_the_load_edge(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"enchantments": {}, "gems": {
        "standard": [{"id": 1, "name": "a", "stat": "Mastery"}]}}), encoding="utf-8")
    config = load_config(str(path))
    assert config["gems"]["standard"][0]["stat"] == "mastery"


def test_example_ships_canonical_stats():
    from pathlib import Path
    example = json.loads(
        (Path(__file__).resolve().parents[1] / "examples" / "config.example.json")
        .read_text(encoding="utf-8"))
    for gem in example["gems"]["standard"]:
        if "stat" in gem:
            assert gem["stat"] in GEM_STATS, gem


def test_missing_gem_section_is_safe():
    assert normalize_gem_stats({}) == {}
    assert normalize_gem_stats({"gems": None})["gems"] is None
