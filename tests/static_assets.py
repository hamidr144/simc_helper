"""Successors to the pre-MGE2 monolith assets for token-pinning tests
(t_94a15fe3, gui-rewrite-contract §3.1): app.js/style.css/results.js/
history.js/auth.js/api-fetch.js are split into css/*.css + js/**. Bundling
the split files keeps substring pins honest across the module graph; real
HTTP serving is asserted against the entry files themselves."""
import pathlib
from types import SimpleNamespace

STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "web" / "static"

def _cat(*patterns):
    parts = []
    for pat in patterns:
        parts += [p.read_text(encoding="utf-8") for p in sorted(STATIC.glob(pat))]
    return "\n".join(parts)

def read_css():
    return _cat("css/*.css")

def read_js():
    return _cat("js/core/*.js", "js/setup/*.js", "js/results/*.js", "js/pages/*.js", "js/*.js")

def resp(text):
    """Stands in for the old client.get('/static/app.js') shape in pins."""
    return SimpleNamespace(text=text, status_code=200)
