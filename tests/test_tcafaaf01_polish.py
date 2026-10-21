from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins
"""Regression pins for t_cafaaf01 (post-merge polish, reviewer NB1-NB7 from
t_89761608). String-pinning style follows test_t2aede9cd_gqa_bugs.py.

NB1 hero extras replace-not-stack | NB2 --danger token | NB3 btn-danger tokens
NB4 search re-closes its own sections | NB5 chip wording | NB6 D1 quarantine
NB7 sticky offset token | plus the cache-bust sweep (followed by the
TG2-A sweep to 20261017-enh-chips, TG2-B sweep to 20261018-mean-err-1, the
TG2-F sweep to 20261018-chip-worn-1, the t_4d8563f2 merge sweep to
older sweeps; t_94a15fe3 swept the pages to the current token).

"""
from pathlib import Path
import re

CSS = read_css()
APP_JS = read_js()
RESULTS_JS = read_js()
PAGES = ["app.html", "history.html", "login.html", "register.html", "results.html"]


def _rule(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"rule not found: {selector}"
    return m.group(1)


def test_nb1_hero_extras_replace_not_stack():
    # RED-3: the hero extras moved to the results side rail; renderHeroExtras
    # still re-runs per fetchResults retry and must clear before appending
    # (kv.replaceChildren() before any kv.append) or retries stack duplicates.
    assert "kv.replaceChildren()" in RESULTS_JS
    assert RESULTS_JS.index("kv.replaceChildren()") < RESULTS_JS.index("kv.append(row)")
    assert "hero.append(line)" not in RESULTS_JS  # old stacking host is gone


def test_nb2_danger_token_matches_doc():
    # RED-3 palette (v11 zip): the danger token is --dn; light palette value.
    assert "--dn:#b3382c;" in CSS
    assert "#f87181" not in CSS


def test_nb3_btn_danger_uses_danger_token():
    # NB3 is about btn-danger token hygiene; other rose consumers (status-err
    # chip, history failed badge) are out of scope.
    for selector in ("button.btn-danger", "button.btn-danger:not(:disabled):hover"):
        body = _rule(CSS, selector)
        assert "var(--dn" in body, f"{selector} must use the --dn token"
        assert not re.search(r"#fda4af|#fecdd3|rgba\(251, 113, 133", body)


def test_nb4_search_recloses_only_sections_it_opened():
    assert "if (!section.open) searchOpened.add(section);" in APP_JS
    assert "} else if (!needle && searchOpened.has(section)) {" in APP_JS
    assert "searchOpened.delete(section)" in APP_JS
    assert "section.open = false" in APP_JS


def test_nb5_worker_chip_empty_state_wording():
    assert "'No idle workers'" in APP_JS
    assert "'No workers'" not in APP_JS


def test_nb6_no_gear_difference_rows_are_quarantined():
    # Doc D1: dps>0 rows with no gear difference are quarantined, never ranked.
    assert "const noDiff = rankedAll.filter(result => !changesFromBaseline(result, baseline).length);" in RESULTS_JS
    assert "const rankedRows = rankedAll.filter(result => changesFromBaseline(result, baseline).length);" in RESULTS_JS  # MGE-2 A2 (t_94a15fe3)
    assert "'no gear difference'" in RESULTS_JS
    # The ranked rows can no longer render the marker; dead fallbacks removed.
    assert "No gear difference was parsed from the report." not in RESULTS_JS


def test_nb7_sticky_column_offset_is_a_token():
    # RED-3: the v11 ranked table drops the sticky first column; stickiness
    # survives in the sticky side rail / jump nav and must stay offset-free:
    # no raw 40px offset may return, and no hardcoded pixel offsets on sticky.
    assert "left: var(--results-num-col)" not in CSS
    assert "left: 40px" not in CSS
    assert "position:sticky" in CSS


def test_cache_bust_token_everywhere():
    # t_5e099a0a: sweep extended to all pages; pins track the current token
    # (t_8bf63ec6 TG2-B sweep to 20261018-mean-err-1, t_61442157 TG2-F sweep
    # to 20261018-chip-worn-1, t_4d8563f2 merge sweep to 20261018-merge-1, t_9fdd2c1b
    # TG3-D compact-rows sweep to 20261018-tg3d-1, TG3-D2 sweep to 20261018-d2-1,
    # TG3-G results-polish sweep to 20261018-tg3g-1, t_79a87102 F2 batch sweep
    # older sweeps; t_94a15fe3 swept all pages to the single MGE-2 token).
    for page in PAGES:
        html = Path(f"src/web/static/{page}").read_text()
        # RB1 (t_754e1374) bumped only app.html to rb1-1; other pages stay guir-3.
        token = "red3-1"
        assert token in html, page
        assert "20261017-enh-chips" not in html, page
