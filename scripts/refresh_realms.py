#!/usr/bin/env python3
"""Refresh the static realm list used by the character-setup dropdown.

Fetches https://everythingwow.com/realms (no credentials needed — the Blizzard
Game Data API is dead as of 2026, see wow-armory-api-guide.md §8) and extracts
the server-rendered TanStack Router data blob, which embeds every retail realm
as a structured record in a fixed key order:

    $R[59]={region:"eu",id:577,slug:"aegwynn",name:"Aegwynn",type:"NORMAL",
            timezone:"Europe/Paris",status:"UP",population:"LOW",game_type:"NORMAL"}

Emits ``src/web/static/realms.json`` — ``{generated_at, source,
source_crawled_at, counts, realms: {eu: [...], us: [...]}}`` — where each realm
record carries exactly the fields agreed in motion t_3b46a74b:
``{region, id, slug, name, type, timezone, population}``. Slugs are taken
verbatim from the source (they are the authoritative Armory slugs and conform
to guide §3.1: lowercase, apostrophes stripped, accents preserved).

Safety rules agreed in motion t_3b46a74b — a broken scrape must never ship a
truncated dropdown:

* stdlib-only (urllib), but still sends a browser User-Agent — the site has
  been observed serving 0 bytes to bare curl (defensive; not always required);
* an empty/short fetch, zero parsed records, or per-region deduped counts
  outside REALM_COUNT_FLOOR..REALM_COUNT_CEIL are FATAL (exit 1);
* the parsed blob records are cross-checked against the page's
  ``/realms/retail/(eu|us)/{slug}`` href anchors — a mismatch means schema
  drift and is FATAL;
* every record must carry all REQUIRED_FIELDS and a §3.1-shaped slug;
* output is written to a temp file and atomically renamed over the target,
  so a failed run leaves the previous realms.json untouched.

Regeneration cadence: around expansion launches (new realms appear); the
source itself is crawled daily. See the runbook in docs/ for details.

Usage:
    .venv/bin/python scripts/refresh_realms.py [-o PATH] [--url URL]
    .venv/bin/python scripts/refresh_realms.py --input saved_page.html   # offline/hermetic
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://everythingwow.com/realms"
# The site has served 0 bytes to non-browser agents (verified 2026-10-13);
# keep a browser UA even though plain curl works from some networks.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "web" / "static" / "realms.json"

REGIONS = ("eu", "us")
# Sanity band for per-region deduped counts (reviewer ruling on t_3b46a74b:
# hard-fail on structure, never on age; no hard-pinned totals). Live values:
# EU 267 / US 246 (2026-10-13).
REALM_COUNT_FLOOR = 150
REALM_COUNT_CEIL = 400
MIN_PAGE_BYTES = 10_000
REQUIRED_FIELDS = ("region", "id", "slug", "name", "type", "timezone", "population")
# Guide §3.1: lowercase, apostrophes removed, non-alnum runs -> '-'. Accented
# letters are alnum and stay (e.g. pozzo-delleternità). [^\W_A-Z] = lowercase
# alphanumerics including accented letters.
SLUG_RE = re.compile(r"^[^\W_A-Z]+(-[^\W_A-Z]+)*$")

# One realm record from the SSR blob. The anchor on region+id+slug distinguishes
# realm records from the region summary records ({region:"eu",realms:267,...})
# and from the giant loader object $R[45], whose embedded JSON strings with
# escaped quotes defeat generic $R[N]={...} matching (it swallows the whole
# rows array, or worse, yields one fake record assembled from loader fields).
# A strict key order is intentional: if the serializer reorders or renames
# keys the parse yields zero records and we fail loudly rather than shipping a
# partial list. JS string escapes (\", \', \\) are unescaped after matching;
# the (?:[^"\\]|\\.)* classes keep \X pairs inside captured values so a name
# like "Zul\'jin" cannot terminate its string early.
RECORD_RE = re.compile(
    r'\{region:"(?P<region>eu|us|kr|tw)",id:(?P<id>\d+),'
    r'slug:"(?P<slug>(?:[^"\\]|\\.)*)",name:"(?P<name>(?:[^"\\]|\\.)*)",'
    r'type:"(?P<type>[A-Z_]*)",timezone:"(?P<timezone>(?:[^"\\]|\\.)*)",'
    r'status:"(?P<status>[A-Z_]*)",population:"(?P<population>[A-Z_]*)",'
    r'game_type:"(?P<game_type>[A-Z_]*)"\}'
)
# Stable secondary anchor: the visible table's href links (devops ruling on
# t_3b46a74b — deduping these yields the same realm set as the blob).
ANCHOR_RE = re.compile(r'href="/realms/retail/(eu|us)/([^"?]+)"')
CRAWL_STAMP_RE = re.compile(r'newest:"([^"]+)"')

_JS_SIMPLE_ESCAPES: dict[str, str] = {"\\": "\\", '"': '"', "/": "/", "'": "'", "n": "\n", "r": "\r", "t": "\t"}


def unescape_js(value: str) -> str:
    """Unescape a JS double-quoted string body, then HTML entities."""

    def repl(m: re.Match) -> str:
        seq = m.group(1)
        if seq.startswith("u"):
            return chr(int(seq[1:], 16))
        return _JS_SIMPLE_ESCAPES.get(seq, seq)

    value = re.sub(r"\\(u[0-9a-fA-F]{4}|.)", repl, value)
    return html_lib.unescape(value)


def fetch(url: str = SOURCE_URL, timeout: int = 60) -> str:
    """Return the realms page HTML, or exit(1) with a clear message."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # urllib follows same-scheme redirects (www -> apex) by default.
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - any network error is fatal here
        sys.exit(f"refresh_realms: FATAL: fetch failed: {exc}")
    if len(body) < MIN_PAGE_BYTES:
        sys.exit(
            f"refresh_realms: FATAL: suspiciously short response "
            f"({len(body)} bytes) from {url} — refusing to parse."
        )
    return body


def parse_records(page_html: str) -> list[dict]:
    """Extract realm records from the SSR blob. Exits(1) if none are found."""
    records: list[dict] = []
    for m in RECORD_RE.finditer(page_html):
        rec = {k: (int(v) if k == "id" else unescape_js(v)) for k, v in m.groupdict().items()}
        records.append(rec)
    if not records:
        sys.exit(
            "refresh_realms: FATAL: no realm records matched — the blob layout "
            "has likely changed (key order/renames); inspect the parser before shipping."
        )
    return records


def crawl_stamp(page_html: str) -> str | None:
    """The source site's own newest-crawl stamp, if present."""
    stamps = CRAWL_STAMP_RE.findall(page_html)
    return max(stamps) if stamps else None


def cross_check_anchors(records: list[dict], page_html: str) -> None:
    """Blob records and href anchors must describe the same EU/US realm set."""
    blob_set = {(r["region"], r["slug"]) for r in records if r["region"] in REGIONS}
    anchor_set = {(region, unescape_js(slug)) for region, slug in ANCHOR_RE.findall(page_html)}
    if blob_set == anchor_set:
        return
    only_blob = sorted(blob_set - anchor_set)[:5]
    only_anchor = sorted(anchor_set - blob_set)[:5]
    sys.exit(
        "refresh_realms: FATAL: blob/anchor mismatch — schema drift suspected.\n"
        f"  blob-only:   {only_blob}\n"
        f"  anchor-only: {only_anchor}"
    )


def validate(records: list[dict]) -> dict[str, list[dict]]:
    """Dedupe, check every record, and group by region. Exits(1) on any breach."""
    grouped: dict[str, dict[str, dict]] = {region: {} for region in REGIONS}
    problems: list[str] = []
    skipped_regions: set[str] = set()

    for rec in records:
        missing = [f for f in REQUIRED_FIELDS if rec.get(f) in (None, "")]
        if missing:
            problems.append(f"{rec.get('name') or rec.get('slug') or rec}: missing {missing}")
            continue
        region = rec["region"]
        if region not in grouped:
            skipped_regions.add(region)  # kr/tw/... — dropdown is EU/US only
            continue
        slug = rec["slug"]
        if not SLUG_RE.match(slug):
            problems.append(f"{rec['name']}: slug {slug!r} violates guide §3.1 rules")
            continue
        if slug in grouped[region]:
            prev = grouped[region][slug]
            if prev != {k: rec[k] for k in prev}:
                problems.append(f"duplicate {region}/{slug} with conflicting data")
            continue
        grouped[region][slug] = {f: rec[f] for f in REQUIRED_FIELDS}

    for region, realms in grouped.items():
        if not REALM_COUNT_FLOOR <= len(realms) <= REALM_COUNT_CEIL:
            problems.append(
                f"{region} realm count {len(realms)} outside sanity band "
                f"{REALM_COUNT_FLOOR}..{REALM_COUNT_CEIL} — refusing to write"
            )
    if problems:
        for p in problems:
            print(f"refresh_realms: ERROR: {p}", file=sys.stderr)
        sys.exit(f"refresh_realms: FATAL: {len(problems)} validation problem(s); realms.json untouched.")
    if skipped_regions:
        print(f"refresh_realms: note: skipped non-EU/US regions: {sorted(skipped_regions)}", file=sys.stderr)
    # Deterministic order so regeneration diffs stay reviewable (reviewer criterion).
    return {
        region: sorted(by_slug.values(), key=lambda r: (r["name"].casefold(), r["id"]))
        for region, by_slug in grouped.items()
    }


def build_document(grouped: dict[str, list[dict]], source: str, stamp: str | None) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "source_crawled_at": stamp,
        "counts": {region: len(realms) for region, realms in grouped.items()},
        "realms": {region: grouped[region] for region in REGIONS},
    }


def write_atomic(doc: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=out_path.parent, prefix=".realms-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, out_path)  # atomic; old file survives any earlier failure
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the static realms.json from the everythingwow.com/realms SSR blob."
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"output JSON path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--url", default=SOURCE_URL, help="source page URL (default: %(default)s)")
    parser.add_argument("--input", type=Path, default=None,
                        help="read page HTML from a file instead of fetching (for tests/offline runs)")
    args = parser.parse_args(argv)

    if args.input:
        page_html = args.input.read_text(encoding="utf-8", errors="replace")
        if len(page_html) < MIN_PAGE_BYTES:
            sys.exit(f"refresh_realms: FATAL: input file too small ({len(page_html)} bytes).")
        source = f"file:{args.input}"
    else:
        page_html = fetch(args.url)
        source = args.url

    records = parse_records(page_html)
    cross_check_anchors(records, page_html)
    grouped = validate(records)
    doc = build_document(grouped, source, crawl_stamp(page_html))
    write_atomic(doc, args.output)

    counts = ", ".join(f"{region} {n}" for region, n in doc["counts"].items())
    total = sum(doc["counts"].values())
    print(f"refresh_realms: wrote {args.output} — {total} realms ({counts}); "
          f"source crawl: {doc['source_crawled_at'] or 'unknown'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
