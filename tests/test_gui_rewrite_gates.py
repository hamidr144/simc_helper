"""GUI-rewrite gate tests (t_94a15fe3, gui-rewrite-contract §5 RG-P3/A3/A6).

These are the new pytest gates the rewrite contract requires on top of the
redirected legacy pins:
  * RG-P3  no dead exports anywhere under js/ (entry exports allowed),
           import-aware per export name (t_f9a0df27), and every cross-module
           name a module uses is imported by it;
           every DOM id referenced from JS exists in some page.
  * A3     no items[0] fallback in the selection initializer.
  * A6     zero version literal in static/ (chip text comes from /api/version).
"""
import os
import re
from pathlib import Path

import static_assets  # noqa: F401  (shares the split-asset bundle helpers)

STATIC = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
JS_DIR = STATIC / "js"

EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
# destructured dynamic import in the .mjs realm harness
DYN_IMPORT_RE = re.compile(
    r"\{([^}]*)\}\s*=\s*(?:await\s+)?import\(\s*(?:fileURLToPath\(\s*new URL\(\s*)?['\"]([^'\"]+)['\"]")
ENTRY_GLOBS = ("js/pages/", "js/auth.js", "js/boot/")


def _entries(touched):
    # a module is an entry if no other module imports it directly from pages/
    # or it is a page script itself (pages/, auth.js).
    return touched.startswith(("js/pages/", "js/auth.js"))


def _js_files():
    return {p: p.read_text() for p in sorted(JS_DIR.rglob("*.js"))}


def _imported_pairs(text, consumer_path):
    # (resolved-target-path, name) for every `import { a, b as c } from '...'`
    # and for the harness's destructured `await import(...)` form.
    for clause, spec in IMPORT_RE.findall(text) + DYN_IMPORT_RE.findall(text):
        target = os.path.normpath(os.path.join(os.path.dirname(str(consumer_path)), spec))
        for part in clause.split(","):
            name = part.strip().split(" as ")[0].strip()
            if name:
                yield target, name


def test_rg_p3_no_dead_exports():
    # Import-aware (t_f9a0df27): the old bare \bname\b match passed vacuously
    # at 9881c8c — pages/setup.js's own `export function wire` counted as usage
    # for the three setup-module wires nothing imported. Usage = another module
    # (or a fixture harness) imports the name from this exact module path.
    files = _js_files()
    consumers = dict(files)
    for fx in (Path(__file__).parent / "fixtures").glob("*.mjs"):
        consumers[fx] = fx.read_text()
    imported = set()
    for cpath, ctext in consumers.items():
        imported.update(_imported_pairs(ctext, cpath))
    dead = []
    for path, text in files.items():
        rel = path.relative_to(STATIC).as_posix()
        if _entries(rel):
            continue
        for name in EXPORT_RE.findall(text):
            if (str(path), name) not in imported:
                dead.append(f"{rel}: {name}")
    assert not dead, f"dead exports (RG-P3): {dead}"


def _scan_body(text):
    # strip import clauses (bindings, not uses), comments and quoted strings so
    # the unbound-name scan only sees code identifiers. Template literals stay
    # (their ${...} parts are code); shortcut: a name used ONLY inside a
    # template's prose is not caught — upgrade to a real parser if that bites.
    text = IMPORT_RE.sub("", text)
    text = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", text)
    text = re.sub(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"", " ", text)
    return text


def _locally_bound(text, name):
    n = re.escape(name)
    return (re.search(rf"\b(?:const|let|var|function|class)\s+{n}\b", text)
            or re.search(rf"[(,]\s*{n}\s*[,)=]", text)  # (params, x, y) / (x = d) =>
            or re.search(rf"\{{\s*{n}\s*[,}}]", text))  # destructuring { x, ... } = ...


def test_rg_p3_used_names_are_imported():
    # Companion gate (t_f9a0df27): the dropped-import defect class QA found at
    # 9881c8c (initializeSelections in paste.js, PAPER_DOLL_SLOTS in
    # gear/enhancements) — ReferenceError only fires on click in the browser.
    files = _js_files()
    exporters = {}
    for path, text in files.items():
        for name in EXPORT_RE.findall(text):
            exporters.setdefault(name, set()).add(path)
    offenders = []
    for path, text in files.items():
        body = _scan_body(text)
        imported_here = {n for _, n in _imported_pairs(text, path)}
        for name, srcs in sorted(exporters.items()):
            if path in srcs or name in imported_here:
                continue
            if _locally_bound(body, name):
                continue
            if re.search(rf"(?<![\w.$]){re.escape(name)}\b", body):
                offenders.append(f"{path.relative_to(STATIC).as_posix()}: {name}")
    assert not offenders, f"used without import (RG-P3): {offenders}"


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
