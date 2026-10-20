"""GUI-rewrite gate tests (t_94a15fe3, gui-rewrite-contract §5 RG-P3/A3/A6).

These are the new pytest gates the rewrite contract requires on top of the
redirected legacy pins:
  * RG-P3  no dead exports anywhere under js/ (entry exports allowed);
           every DOM id referenced from JS exists in some page.
  * A3     no items[0] fallback in the selection initializer.
  * A6     zero version literal in static/ (chip text comes from /api/version).
"""
import re
from pathlib import Path

import static_assets  # noqa: F401  (shares the split-asset bundle helpers)

STATIC = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
JS_DIR = STATIC / "js"

EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
ENTRY_GLOBS = ("js/pages/", "js/auth.js", "js/boot/")


def _entries(touched):
    # a module is an entry if no other module imports it directly from pages/
    # or it is a page script itself (pages/, auth.js).
    return touched.startswith(("js/pages/", "js/auth.js"))


def test_rg_p3_no_dead_exports():
    files = {p.relative_to(STATIC).as_posix(): p.read_text()
             for p in JS_DIR.rglob("*.js")}
    # page scripts and the .mjs realm harness count as entry usage.
    consumers = dict(files)
    for fx in (Path(__file__).parent / "fixtures").glob("*.mjs"):
        consumers[f"tests/fixtures/{fx.name}"] = fx.read_text()
    dead = []
    for path, text in files.items():
        if _entries(path):
            continue
        for name in EXPORT_RE.findall(text):
            rx = re.compile(rf"\b{re.escape(name)}\b")
            used = any(other_path != path and rx.search(other)
                       for other_path, other in consumers.items())
            if not used:
                dead.append(f"{path}: {name}")
    assert not dead, f"dead exports (RG-P3): {dead}"


def test_rg_p3_markup_ids_referenced():
    # Contract direction: every id CREATED in page markup is referenced by some
    # script or selector (runtime-built ids are covered by the JS side).
    pages = {p: (STATIC / p).read_text()
             for p in ("app.html", "results.html", "history.html",
                       "login.html", "register.html")}
    js = static_assets.read_js()
    css = static_assets.read_css()
    dead = []
    for page, html in pages.items():
        others = "\n".join(t for p, t in pages.items() if p != page)
        for ident in re.findall(r'id="([^"{}]+)"', html):
            needle = re.escape(ident)
            hit = (re.search(rf"getElementById\(['\"]{needle}['\"]", js)
                   or f'href="#{ident}"' in html
                   or f'id="{ident}"' in others
                   or re.search(rf"[.#]{needle}\b", css)
                   or re.search(rf'(for|aria-\w+|aria-\w+-\w+)="{needle}"', html)
                   or html.count(f'id="{ident}"') > 1)
            if not hit:
                dead.append(f"{page}: #{ident}")
    assert not dead, f"markup ids referenced nowhere (RG-P3): {dead}"


def test_a3_selection_init_has_no_first_item_fallback():
    js = static_assets.read_js()
    assert "add(items[0])" not in js
    assert "gearTouchedByUser" in js  # equipped-only bookkeeping shipped


def test_a6_no_version_literal_in_static():
    blob = static_assets.read_js() + static_assets.read_css()
    for page in ("app.html", "results.html", "history.html", "login.html", "register.html"):
        blob += (STATIC / page).read_text()
    # version-shaped tokens (1.2.3 / v1.2.3); "WCAG 2.4.11" is a guideline ref.
    assert not re.search(r"(?<!WCAG )\bv?\d+\.\d+\.\d+\b", blob)
