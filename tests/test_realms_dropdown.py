"""Hermetic tests for the static realm list (src/web/static/realms.json) and
the realm dropdown wired in app.js.

Contract under test (motion t_3b46a74b, verified by parent t_b9e549d1):
* top level: {generated_at, source, source_crawled_at, counts, realms{eu,us}};
* every realm record carries exactly the 7 fields
  {region, id, slug, name, type, timezone, population};
* slugs follow guide §3.1 (wow-armory-api-guide.md): lowercase, apostrophes
  stripped, non-alnum runs -> '-', accents preserved — the SAME regex the
  generator enforces (imported from scripts/refresh_realms.py, single source);
* EU/US grouping: per-region unique ids/slugs, sorted by name.casefold,
  counts block matches the arrays, realms present in both regions (kelthuzad)
  are NOT deduped;
* generated_at is a tz-aware ISO-8601 stamp that is not in the future
  (reviewer ruling: hard-fail on structure, never on age);
* the dropdown (populateRealmSelect/loadRealms in app.js) populates EU/US
  optgroups from the bundled fixture via a real-DOM-code harness, and
  degrades gracefully (select stays hidden+disabled) on fetch/shape failure.

No network, no clock dependence beyond "now" — fully hermetic.
"""

import importlib.util
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
REALMS_PATH = REPO_ROOT / "src" / "web" / "static" / "realms.json"
APP_JS_PATH = REPO_ROOT / "src" / "web" / "static" / "app.js"
APP_HTML_PATH = REPO_ROOT / "src" / "web" / "static" / "app.html"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "realms_dropdown.json"
HARNESS_PATH = Path(__file__).resolve().parent / "fixtures" / "realms_dropdown_harness.mjs"

# Import the generator module to reuse its single-source slug rule (guide §3.1)
# instead of duplicating the regex here.
_spec = importlib.util.spec_from_file_location(
    "refresh_realms", REPO_ROOT / "scripts" / "refresh_realms.py"
)
refresh_realms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh_realms)

SLUG_RE = refresh_realms.SLUG_RE
REQUIRED_FIELDS = refresh_realms.REQUIRED_FIELDS

REGIONS = ("eu", "us")
TYPES = {"NORMAL", "RP"}
POPULATIONS = {"NORMAL", "LOW", "MEDIUM", "HIGH", "FULL", "RECOMMENDED"}
# US realms include Australia/* zones (Oceania servers) — verified live 2026-10.
TIMEZONE_PREFIXES = {
    "eu": ("Europe/",),
    "us": ("America/", "Australia/"),
}

# Researcher spot-checks (motion t_3b46a74b) that must survive every refresh.
SPOT_CHECKS = {
    "eu": {"pozzo-delleternità": "Pozzo dell'Eternità", "kelthuzad": "Kel'Thuzad"},
    "us": {"blades-edge": "Blade's Edge", "kelthuzad": "Kel'Thuzad"},
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def realms() -> dict:
    return _load(REALMS_PATH)


def assert_schema(doc: dict, *, label: str) -> None:
    """Full structural contract shared by the real file and the fixture."""
    assert set(doc) == {"generated_at", "source", "source_crawled_at", "counts", "realms"}, label
    assert doc["source"] == "https://everythingwow.com/realms", label
    assert set(doc["counts"]) == set(REGIONS), label
    assert set(doc["realms"]) == set(REGIONS), f"{label}: dropdown is EU/US only"

    for region in REGIONS:
        records = doc["realms"][region]
        assert isinstance(records, list) and records, f"{label}: {region} empty"
        assert doc["counts"][region] == len(records), (
            f"{label}: counts[{region!r}]={doc['counts'][region]} != {len(records)} records"
        )
        ids, slugs = set(), set()
        for rec in records:
            assert set(rec) == set(REQUIRED_FIELDS), f"{label}: {region} field set {sorted(rec)}"
            assert rec["region"] == region, f"{label}: region field/group mismatch {rec}"
            assert isinstance(rec["id"], int) and not isinstance(rec["id"], bool) and rec["id"] > 0, rec
            assert isinstance(rec["name"], str) and rec["name"].strip(), rec
            assert isinstance(rec["slug"], str) and SLUG_RE.match(rec["slug"]), (
                f"{label}: slug {rec['slug']!r} violates guide §3.1"
            )
            assert rec["type"] in TYPES, f"{label}: bad type {rec['type']!r}"
            assert rec["population"] in POPULATIONS, f"{label}: bad population {rec['population']!r}"
            assert isinstance(rec["timezone"], str) and "/" in rec["timezone"], rec
            assert rec["timezone"].startswith(TIMEZONE_PREFIXES[region]), (
                f"{label}: {region} realm {rec['slug']} has unexpected zone {rec['timezone']!r}"
            )
            assert rec["id"] not in ids, f"{label}: duplicate id {rec['id']} in {region}"
            assert rec["slug"] not in slugs, f"{label}: duplicate slug {rec['slug']} in {region}"
            ids.add(rec["id"])
            slugs.add(rec["slug"])


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------

def test_static_realms_endpoint_serves_valid_json():
    from web.main import app

    client = TestClient(app)
    response = client.get("/static/realms.json")
    assert response.status_code == 200
    doc = response.json()  # must parse straight from the HTTP body
    assert_schema(doc, label="served /static/realms.json")


# --------------------------------------------------------------------------
# Schema: required fields, EU/US grouping, slug rules (guide §3.1)
# --------------------------------------------------------------------------

def test_realms_file_exists_and_is_utf8_json():
    raw = REALMS_PATH.read_bytes()
    doc = json.loads(raw.decode("utf-8"))  # raises if not valid UTF-8 JSON
    assert len(doc["realms"]["eu"]) >= 150 and len(doc["realms"]["us"]) >= 150


def test_schema_of_committed_realms_json(realms):
    assert_schema(realms, label="src/web/static/realms.json")


def test_records_sorted_by_casefolded_name(realms):
    for region in REGIONS:
        names = [r["name"].casefold() for r in realms["realms"][region]]
        assert names == sorted(names), f"{region} not sorted by name.casefold"


def test_slug_rules_positive_and_negative(realms):
    # Positive: every committed slug matches the generator's §3.1 regex...
    for region in REGIONS:
        for rec in realms["realms"][region]:
            assert SLUG_RE.match(rec["slug"]), rec["slug"]
    # ...and the regex itself rejects §3.1 violations (uppercase, spaces,
    # apostrophes, leading/trailing/double hyphens, empty).
    for bad in ["Kel'Thuzad", "Area 52", "azjol-nerub-", "-x", "a--b", "", "Pozzo-delleternità"]:
        assert not SLUG_RE.match(bad), f"regex wrongly accepts {bad!r}"
    for good in ["kelthuzad", "area-52", "pozzo-delleternità", "aggra-português", "a"]:
        assert SLUG_RE.match(good), f"regex wrongly rejects {good!r}"


def test_cross_region_realms_not_deduped(realms):
    # Kel'Thuzad exists in BOTH regions with different ids; Aegwynn too.
    eu = {r["slug"]: r for r in realms["realms"]["eu"]}
    us = {r["slug"]: r for r in realms["realms"]["us"]}
    for slug in ("kelthuzad", "aegwynn"):
        assert slug in eu and slug in us, f"{slug} must exist in both regions"
        assert eu[slug]["id"] != us[slug]["id"], f"{slug} ids must differ per region"


def test_researcher_spot_checks(realms):
    for region, expected in SPOT_CHECKS.items():
        by_slug = {r["slug"]: r for r in realms["realms"][region]}
        for slug, name in expected.items():
            assert slug in by_slug, f"missing {region}/{slug}"
            assert by_slug[slug]["name"] == name


# --------------------------------------------------------------------------
# generated_at freshness
# --------------------------------------------------------------------------

def _parse_stamp(value: str) -> datetime:
    # datetime.fromisoformat handles "+00:00" offsets on all supported versions.
    stamp = datetime.fromisoformat(value)
    assert stamp.tzinfo is not None, f"{value!r} is not timezone-aware"
    return stamp


def test_generated_at_is_fresh_tz_aware_and_not_future(realms):
    generated = _parse_stamp(realms["generated_at"])
    now = datetime.now(timezone.utc)
    # Reviewer ruling on t_3b46a74b: hard-fail on structure, never on age —
    # so we only assert validity + not-in-the-future (60 s clock-skew margin),
    # plus that the source crawl stamp predates generation.
    assert generated <= now + timedelta(seconds=60), (
        f"generated_at {realms['generated_at']} is in the future"
    )
    crawled = _parse_stamp(realms["source_crawled_at"])
    assert crawled <= generated, "source_crawled_at is after generated_at"


# --------------------------------------------------------------------------
# Bundled fixture
# --------------------------------------------------------------------------

def test_bundled_fixture_matches_real_schema_contract():
    assert_schema(_load(FIXTURE_PATH), label="tests/fixtures/realms_dropdown.json")


def test_app_js_and_html_are_wired():
    js = APP_JS_PATH.read_text(encoding="utf-8")
    assert "realms.json" in js and "loadRealms" in js
    assert re.search(r"^\s*loadRealms\(\);", js, re.MULTILINE), "loadRealms() never called"
    html = APP_HTML_PATH.read_text(encoding="utf-8")
    assert 'id="armory-realm"' in html
    assert '<option value="" selected>Select realm' in html


# --------------------------------------------------------------------------
# Dropdown population against the bundled fixture (real app.js code in node)
# --------------------------------------------------------------------------

def _node_binary() -> str:
    node = shutil.which("node")
    if node:
        return node
    bundled = sorted(
        Path.home().glob(".hermes/tools/node-*/bin/node"),
        key=lambda p: p.parts[-4] if len(p.parts) > 3 else str(p),
    )
    if bundled:
        return str(bundled[-1])
    pytest.skip("node not available; dropdown harness needs it")


def _run_harness(realms_json: Path, *flags: str) -> dict:
    result = subprocess.run(
        [_node_binary(), str(HARNESS_PATH), str(realms_json), *flags],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"harness failed: {result.stderr[-2000:]}"
    return json.loads(result.stdout)


def test_dropdown_populates_from_bundled_fixture():
    out = _run_harness(FIXTURE_PATH)
    assert out["disabled"] is False and out["hidden"] is False, "select must activate on success"
    labels = [g["label"] for g in out["groups"]]
    assert labels == ["EU", "US"], f"expected EU/US optgroups, got {labels}"
    eu, us = out["groups"]
    assert [o["value"] for o in eu["options"]] == [
        "eu/aegwynn", "eu/aggra-portugu\u00eas", "eu/kelthuzad", "eu/pozzo-delleternit\u00e0",
    ]
    assert [o["value"] for o in us["options"]] == [
        "us/aegwynn", "us/area-52", "us/blades-edge", "us/kelthuzad",
    ]
    assert [o["text"] for o in eu["options"]] == [
        "Aegwynn", "Aggra (Portugu\u00eas)", "Kel'Thuzad", "Pozzo dell'Eternit\u00e0",
    ]
    # No dedupe by name: Kel'Thuzad appears once per region group.
    kel = [o for g in out["groups"] for o in g["options"] if o["text"] == "Kel'Thuzad"]
    assert len(kel) == 2 and {o["value"] for o in kel} == {"eu/kelthuzad", "us/kelthuzad"}
    # Tooltip carries region + record details.
    assert eu["options"][2]["title"].startswith("EU \u00b7 "), eu["options"][2]["title"]
    # realmIndex keys are region-qualified and complete.
    assert sorted(out["indexKeys"]) == sorted(
        [o["value"] for g in out["groups"] for o in g["options"]]
    )
    assert out["indexSample"]["eu/kelthuzad"] == {"region": "eu", "slug": "kelthuzad", "name": "Kel'Thuzad"}
    assert out["indexSample"]["us/kelthuzad"] == {"region": "us", "slug": "kelthuzad", "name": "Kel'Thuzad"}


def test_dropdown_populates_from_real_realms_json():
    doc = _load(REALMS_PATH)
    out = _run_harness(REALMS_PATH)
    total = len(doc["realms"]["eu"]) + len(doc["realms"]["us"])
    options = [o for g in out["groups"] for o in g["options"]]
    assert len(options) == total == len(out["indexKeys"])
    assert [g["label"] for g in out["groups"]] == ["EU", "US"]
    values = {o["value"] for o in options}
    assert {"eu/kelthuzad", "us/kelthuzad", "us/blades-edge", "eu/pozzo-delleternit\u00e0"} <= values


def test_dropdown_degrades_gracefully_when_fetch_fails():
    out = _run_harness(FIXTURE_PATH, "--fail-fetch")
    assert out == {"degraded": True, "disabled": True, "hidden": True, "childCount": 0}


def test_dropdown_degrades_gracefully_on_bad_shape():
    out = _run_harness(FIXTURE_PATH, "--bad-shape")
    assert out == {"degraded": True, "disabled": True, "hidden": True, "childCount": 0}
