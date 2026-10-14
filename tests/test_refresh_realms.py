"""Hermetic tests for the realm-list GENERATOR (scripts/refresh_realms.py).

Companion to tests/test_realms_dropdown.py, which only validates the
committed realms.json artifact. This file covers the generator's own
fetch/parse/validate/write logic and, above all, its FAILURE paths — the
arbitration rule from motion t_3b46a74b is that a broken scrape must fail
loudly (exit 1) and NEVER emit partial JSON or clobber the previous
realms.json.

Contract under test:
* parse_records(): strict key-order blob parsing, JS-escape + HTML-entity
  unescaping, ids as ints; zero matches (e.g. key-order drift) is FATAL;
* cross_check_anchors(): blob records and /realms/retail/(eu|us)/{slug}
  href anchors must describe the same set — any mismatch is FATAL;
* validate(): identical duplicate records dedupe silently, conflicting
  duplicates / bad slugs / missing fields are FATAL, kr/tw records are
  skipped with a note, per-region counts must sit inside the
  REALM_COUNT_FLOOR..REALM_COUNT_CEIL sanity band;
* fetch(): network errors and short/empty bodies are FATAL;
* write_atomic(): temp-file + rename — a failed run (any validation
  problem, short input, fetch failure) leaves the previous realms.json
  byte-for-byte untouched and leaves no .realms-*.tmp litter behind.

No network, no sleeps, no clock dependence — fully hermetic.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Same importlib pattern as tests/test_realms_dropdown.py line 43-47: the
# script is not an importable package module, so load it by path.
_spec = importlib.util.spec_from_file_location(
    "refresh_realms_gen", REPO_ROOT / "scripts" / "refresh_realms.py"
)
refresh_realms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh_realms)

FLOOR = refresh_realms.REALM_COUNT_FLOOR
CEIL = refresh_realms.REALM_COUNT_CEIL

# ---------------------------------------------------------------------------
# Fixture builders — synthesise everythingwow-style SSR pages in memory
# ---------------------------------------------------------------------------


def make_record(region, rid, slug, name, **overrides):
    """One realm record dict in the blob's fixed key order."""
    rec = {
        "region": region,
        "id": rid,
        "slug": slug,
        "name": name,
        "type": "NORMAL",
        "timezone": "Europe/Paris" if region == "eu" else "America/New_York",
        "status": "UP",
        "population": "NORMAL",
        "game_type": "NORMAL",
    }
    rec.update(overrides)
    return rec


def _serialize(rec):
    """Render one record the way the source site's serializer does:
    apostrophes JS-escaped, fixed key order."""

    def esc(value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    name = rec.get("_raw_name") or esc(rec["name"])
    return (
        '{{region:"{region}",id:{id},slug:"{slug}",name:"{name}",'
        'type:"{type}",timezone:"{timezone}",status:"{status}",'
        'population:"{population}",game_type:"{game_type}"}}'
    ).format(**{**rec, "name": name})


def render_page(records, *, anchors=True, drop_anchors=(), stamp="2026-10-13T12:00:00Z",
                min_bytes=0):
    """Full page: href anchors + $R blob + crawl stamp, padded to min_bytes.

    anchors=False omits ALL anchors; drop_anchors is a set of
    (region, slug) pairs whose anchors are individually removed.
    """
    parts = []
    if anchors:
        for r in records:
            if r["region"] in ("eu", "us") and (r["region"], r["slug"]) not in drop_anchors:
                parts.append(f'<a href="/realms/retail/{r["region"]}/{r["slug"]}">{r["name"]}</a>')
    blob = "".join(f"$R[{50 + i}]=" + _serialize(r) + ";" for i, r in enumerate(records))
    stamp_part = f'newest:"{stamp}"' if stamp else ""
    page = f"<html><body>{''.join(parts)}<script>{stamp_part}{blob}</script></body></html>"
    if len(page) < min_bytes:
        page += "<!-- " + "x" * (min_bytes - len(page) - 8) + " -->"
    return page


def make_region_records(region, count, id_base=1000):
    """count valid records for one region with §3.1-shaped slugs."""
    return [
        make_record(region, id_base + i, f"test-realm-{region}-{i:03d}",
                    f"Test Realm {region.upper()} {i:03d}")
        for i in range(count)
    ]


def make_valid_page(*, eu=160, us=160, **kw):
    """A realistic full page (both regions inside the sanity band)."""
    records = make_region_records("eu", eu) + make_region_records("us", us)
    return render_page(records, min_bytes=refresh_realms.MIN_PAGE_BYTES, **kw)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _assert_untouched(path: Path, sentinel: str) -> None:
    assert path.read_text(encoding="utf-8") == sentinel, (
        "previous realms.json must survive a failed run byte-for-byte"
    )


def _assert_no_temp_litter(directory: Path) -> None:
    litter = sorted(p.name for p in directory.glob(".realms-*.tmp"))
    assert litter == [], f"temp-file litter left behind: {litter}"


# ---------------------------------------------------------------------------
# 1. parse_records() — normal parse, unescaping, drift detection
# ---------------------------------------------------------------------------


def test_parse_records_normal_parse_with_escapes_and_entities():
    records = [
        make_record("eu", 577, "aegwynn", "Aegwynn"),
        # apostrophe arrives JS-escaped as \' in the source blob
        make_record("eu", 1589, "kelthuzad", "Kel'Thuzad"),
        # name arrives with HTML entities (&#39; and &agrave;)
        make_record("eu", 1130, "pozzo-delleternità",
                    "Pozzo dell&#39;Eternit&agrave;"),
        make_record("us", 1116, "area-52", "Area 52"),
        make_record("kr", 9999, "kr-test", "KR Test"),  # parsed, skipped later
    ]
    parsed = refresh_realms.parse_records(render_page(records))
    assert len(parsed) == 5
    by_slug = {(r["region"], r["slug"]): r for r in parsed}
    assert by_slug[("eu", "kelthuzad")]["name"] == "Kel'Thuzad", "JS \\' escape"
    assert by_slug[("eu", "pozzo-delleternità")]["name"] == "Pozzo dell'Eternità", (
        "HTML entities must be unescaped"
    )
    assert by_slug[("us", "area-52")]["name"] == "Area 52"
    assert by_slug[("eu", "aegwynn")]["id"] == 577
    assert isinstance(by_slug[("eu", "aegwynn")]["id"], int)
    # every blob field survives, including the ones validate() drops later
    assert set(parsed[0]) == {
        "region", "id", "slug", "name", "type", "timezone", "status",
        "population", "game_type",
    }


def test_parse_records_unicode_escape():
    rec = make_record("eu", 1, "dalaran", "Dalaran")
    rec["_raw_name"] = "Dalar\\u00e4n"  # serializer-style \\uXXXX escape
    parsed = refresh_realms.parse_records(render_page([rec]))
    assert parsed[0]["name"] == "Dalarän"


def test_parse_records_zero_matches_is_fatal():
    with pytest.raises(SystemExit) as exc:
        refresh_realms.parse_records("<html><body>no blob here</body></html>")
    assert "no realm records matched" in str(exc.value)


def test_parse_records_key_order_drift_is_fatal():
    """Strict key order is intentional: a reordered serializer yields zero
    records and a loud failure, never a silently partial parse."""
    drifted = '{region:"eu",id:577,name:"Aegwynn",slug:"aegwynn",type:"NORMAL",' \
              'timezone:"Europe/Paris",status:"UP",population:"LOW",game_type:"NORMAL"}'
    with pytest.raises(SystemExit) as exc:
        refresh_realms.parse_records(f"<script>$R[59]={drifted};</script>")
    assert "no realm records matched" in str(exc.value)


# ---------------------------------------------------------------------------
# 3. cross_check_anchors() — missing anchors / set mismatch is fatal
# ---------------------------------------------------------------------------


def test_cross_check_anchors_matching_passes():
    records = [make_record("eu", 1, "aegwynn", "Aegwynn"),
               make_record("us", 2, "area-52", "Area 52")]
    assert refresh_realms.cross_check_anchors(records, render_page(records)) is None


def test_cross_check_anchors_missing_anchors_is_fatal():
    records = [make_record("eu", 1, "aegwynn", "Aegwynn"),
               make_record("us", 2, "area-52", "Area 52")]
    page = render_page(records, anchors=False)
    with pytest.raises(SystemExit) as exc:
        refresh_realms.cross_check_anchors(records, page)
    assert "blob/anchor mismatch" in str(exc.value)


def test_cross_check_anchors_partial_anchors_is_fatal():
    records = [make_record("eu", 1, "aegwynn", "Aegwynn"),
               make_record("us", 2, "area-52", "Area 52")]
    page = render_page(records, drop_anchors={("us", "area-52")})
    with pytest.raises(SystemExit) as exc:
        refresh_realms.cross_check_anchors(records, page)
    msg = str(exc.value)
    assert "blob/anchor mismatch" in msg and "area-52" in msg


# ---------------------------------------------------------------------------
# validate() — dedupe, region split, field/slug rules
# ---------------------------------------------------------------------------


@pytest.fixture()
def wide_band(monkeypatch):
    """Let small structural fixtures through the count band; band itself is
    covered separately against the real constants."""
    monkeypatch.setattr(refresh_realms, "REALM_COUNT_FLOOR", 0)
    monkeypatch.setattr(refresh_realms, "REALM_COUNT_CEIL", 10_000)


def test_validate_dedupes_identical_records(wide_band):
    rec = make_record("eu", 1, "aegwynn", "Aegwynn")
    grouped = refresh_realms.validate([rec, dict(rec)])
    assert len(grouped["eu"]) == 1 and grouped["us"] == []


def test_validate_conflicting_duplicate_is_fatal(wide_band, capsys):
    a = make_record("eu", 1, "aegwynn", "Aegwynn")
    b = make_record("eu", 1, "aegwynn", "Aegwynn The Second")
    with pytest.raises(SystemExit):
        refresh_realms.validate([a, b])
    assert "conflicting data" in capsys.readouterr().err


def test_validate_region_split_and_non_eu_us_skipped(wide_band, capsys):
    grouped = refresh_realms.validate([
        make_record("eu", 1, "aegwynn", "Aegwynn"),
        make_record("us", 2, "aegwynn", "Aegwynn"),  # same slug, other region: kept
        make_record("kr", 3, "kr-test", "KR Test"),
    ])
    assert set(grouped) == {"eu", "us"}
    assert [r["slug"] for r in grouped["eu"]] == ["aegwynn"]
    assert [r["slug"] for r in grouped["us"]] == ["aegwynn"]
    assert "skipped non-EU/US regions: ['kr']" in capsys.readouterr().err


def test_validate_bad_slug_is_fatal(wide_band, capsys):
    with pytest.raises(SystemExit):
        refresh_realms.validate([make_record("eu", 1, "Area 52", "Area 52")])
    assert "guide §3.1" in capsys.readouterr().err


def test_validate_missing_field_is_fatal(wide_band, capsys):
    with pytest.raises(SystemExit):
        refresh_realms.validate([make_record("eu", 1, "aegwynn", "Aegwynn", population="")])
    assert "missing ['population']" in capsys.readouterr().err


def test_validate_output_is_sorted_and_field_trimmed(wide_band):
    grouped = refresh_realms.validate([
        make_record("eu", 2, "bruno", "Bruno"),
        make_record("eu", 1, "anna", "anna"),  # casefold sort: anna < Bruno
    ])
    assert [r["slug"] for r in grouped["eu"]] == ["anna", "bruno"]
    assert set(grouped["eu"][0]) == set(refresh_realms.REQUIRED_FIELDS)


# ---------------------------------------------------------------------------
# 4. validate() — per-region sanity band (real 150..400 constants)
# ---------------------------------------------------------------------------


def test_validate_below_floor_is_fatal(capsys):
    records = make_region_records("eu", FLOOR - 1) + make_region_records("us", FLOOR)
    with pytest.raises(SystemExit):
        refresh_realms.validate(records)
    assert f"eu realm count {FLOOR - 1} outside sanity band {FLOOR}..{CEIL}" in capsys.readouterr().err


def test_validate_above_ceiling_is_fatal(capsys):
    records = make_region_records("eu", FLOOR) + make_region_records("us", CEIL + 1)
    with pytest.raises(SystemExit):
        refresh_realms.validate(records)
    assert f"us realm count {CEIL + 1} outside sanity band" in capsys.readouterr().err


def test_validate_band_boundaries_pass():
    records = make_region_records("eu", FLOOR) + make_region_records("us", CEIL)
    grouped = refresh_realms.validate(records)
    assert len(grouped["eu"]) == FLOOR and len(grouped["us"]) == CEIL


def test_validate_empty_region_is_fatal(capsys):
    with pytest.raises(SystemExit):
        refresh_realms.validate(make_region_records("eu", FLOOR))
    assert "us realm count 0 outside sanity band" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 2. fetch() — empty/short response and network errors are fatal
# ---------------------------------------------------------------------------


def test_fetch_empty_response_is_fatal(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(b""))
    with pytest.raises(SystemExit) as exc:
        refresh_realms.fetch("https://everythingwow.test/realms")
    assert "suspiciously short response" in str(exc.value)


def test_fetch_short_response_is_fatal(monkeypatch):
    body = b"x" * (refresh_realms.MIN_PAGE_BYTES - 1)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(body))
    with pytest.raises(SystemExit) as exc:
        refresh_realms.fetch("https://everythingwow.test/realms")
    assert "suspiciously short response" in str(exc.value)


def test_fetch_network_error_is_fatal(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("connection reset")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        refresh_realms.fetch("https://everythingwow.test/realms")
    assert "fetch failed" in str(exc.value)


def test_fetch_returns_body_when_long_enough(monkeypatch):
    body = b"y" * refresh_realms.MIN_PAGE_BYTES
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(body))
    assert refresh_realms.fetch("https://everythingwow.test/realms") == body.decode()


# ---------------------------------------------------------------------------
# 5. End-to-end via main(): fail-loud never touches the previous realms.json
# ---------------------------------------------------------------------------


@pytest.fixture()
def prev_realms(tmp_path):
    """A previous realms.json that every failed run must leave untouched."""
    out = tmp_path / "realms.json"
    sentinel = '{"realms": {"eu": [], "us": []}, "note": "previous good file"}\n'
    out.write_text(sentinel, encoding="utf-8")
    return out, sentinel


def _write_input(tmp_path, page: str) -> Path:
    src = tmp_path / "page.html"
    src.write_text(page, encoding="utf-8")
    return src


def test_main_success_writes_valid_document(tmp_path):
    out = tmp_path / "nested" / "realms.json"  # parent dir must be created
    src = _write_input(tmp_path, make_valid_page(eu=160, us=160))
    assert refresh_realms.main(["--input", str(src), "-o", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["counts"] == {"eu": 160, "us": 160}
    assert set(doc["realms"]) == {"eu", "us"}
    assert doc["source_crawled_at"] == "2026-10-13T12:00:00Z"
    assert doc["source"] == f"file:{src}"
    assert doc["realms"]["eu"][0]["slug"] == "test-realm-eu-000"
    names = [r["name"].casefold() for r in doc["realms"]["us"]]
    assert names == sorted(names)
    assert set(doc["realms"]["eu"][0]) == set(refresh_realms.REQUIRED_FIELDS)
    _assert_no_temp_litter(out.parent)


def test_main_missing_anchor_never_writes_partial_json(tmp_path, prev_realms):
    """Item 3: blob parses but an anchor is missing -> schema-drift FATAL,
    previous file untouched."""
    out, sentinel = prev_realms
    records = make_region_records("eu", 160) + make_region_records("us", 160)
    page = render_page(records, drop_anchors={("us", "test-realm-us-007")},
                       min_bytes=refresh_realms.MIN_PAGE_BYTES)
    src = _write_input(tmp_path, page)
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--input", str(src), "-o", str(out)])
    assert "blob/anchor mismatch" in str(exc.value)
    _assert_untouched(out, sentinel)
    _assert_no_temp_litter(tmp_path)


def test_main_no_records_never_writes(tmp_path, prev_realms):
    out, sentinel = prev_realms
    src = _write_input(tmp_path, "<html><body>blob gone</body>"
                       + "z" * refresh_realms.MIN_PAGE_BYTES + "</html>")
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--input", str(src), "-o", str(out)])
    assert "no realm records matched" in str(exc.value)
    _assert_untouched(out, sentinel)
    _assert_no_temp_litter(tmp_path)


def test_main_count_below_floor_never_writes(tmp_path, prev_realms, capsys):
    """Item 4 end-to-end: valid structure but 100 realms/region -> FATAL."""
    out, sentinel = prev_realms
    records = make_region_records("eu", 100) + make_region_records("us", 100)
    page = render_page(records, min_bytes=refresh_realms.MIN_PAGE_BYTES)
    src = _write_input(tmp_path, page)
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--input", str(src), "-o", str(out)])
    err = capsys.readouterr().err
    assert "outside sanity band 150..400" in err
    assert "realms.json untouched" in str(exc.value)
    _assert_untouched(out, sentinel)
    _assert_no_temp_litter(tmp_path)


def test_main_input_too_small_never_writes(tmp_path, prev_realms):
    out, sentinel = prev_realms
    src = _write_input(tmp_path, "tiny page")
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--input", str(src), "-o", str(out)])
    assert "input file too small" in str(exc.value)
    _assert_untouched(out, sentinel)
    _assert_no_temp_litter(tmp_path)


def test_main_fetch_failure_never_creates_output(tmp_path, monkeypatch):
    """Item 2 end-to-end: fetch dies -> output path never even appears."""
    out = tmp_path / "realms.json"

    def boom(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--url", "https://everythingwow.test/realms", "-o", str(out)])
    assert "fetch failed" in str(exc.value)
    assert not out.exists()
    _assert_no_temp_litter(tmp_path)


def test_main_fetch_empty_body_never_creates_output(tmp_path, monkeypatch):
    out = tmp_path / "realms.json"
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResponse(b""))
    with pytest.raises(SystemExit) as exc:
        refresh_realms.main(["--url", "https://everythingwow.test/realms", "-o", str(out)])
    assert "suspiciously short response" in str(exc.value)
    assert not out.exists()
    _assert_no_temp_litter(tmp_path)


# ---------------------------------------------------------------------------
# write_atomic() — temp-file + rename semantics
# ---------------------------------------------------------------------------


def test_write_atomic_creates_parents_and_leaves_no_temp(tmp_path):
    out = tmp_path / "deep" / "dir" / "realms.json"
    refresh_realms.write_atomic({"realms": {"eu": [], "us": []}}, out)
    assert json.loads(out.read_text(encoding="utf-8")) == {"realms": {"eu": [], "us": []}}
    _assert_no_temp_litter(out.parent)


def test_write_atomic_serialization_failure_keeps_previous_file(tmp_path):
    out = tmp_path / "realms.json"
    out.write_text("previous\n", encoding="utf-8")
    with pytest.raises(TypeError):
        refresh_realms.write_atomic({"bad": {1, 2, 3}}, out)  # set is not JSON
    assert out.read_text(encoding="utf-8") == "previous\n"
    _assert_no_temp_litter(tmp_path)
