"""t_7514a3c0 (iter-6 rank-5): rename the visible 'Augurnium' enhancements
group to the system name users know — 'Embellishments'.

Contract: the third trio summary shows 'Embellishments' and the JS display
map drives every visible label (summary count label, fieldset legend, entry
fallback name), while the data-enh-group value, the selectedAugurnium state
key, the appConfig.augurnium config key and the frozen payload mapping stay
byte-identical. Saved drafts keep reopening unchanged because nothing that
serializes changed.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "web" / "static"
APP_HTML = (STATIC / "app.html").read_text(encoding="utf-8")
ENH_JS = (STATIC / "js" / "setup" / "enhancements.js").read_text(encoding="utf-8")
PASTE_JS = (STATIC / "js" / "setup" / "paste.js").read_text(encoding="utf-8")
PAYLOAD_JS = (STATIC / "js" / "setup" / "payload.js").read_text(encoding="utf-8")
STATE_JS = (STATIC / "js" / "core" / "state.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_trio_shows_gems_enchantments_embellishments():
    for label in ("Gems", "Enchantments", "Embellishments"):
        assert f"<summary>{label}</summary>" in APP_HTML, f"{label} summary label missing"


def test_data_group_state_and_config_keys_stay_augurnium():
    # Internal identities are byte-identical: only visible labels moved.
    assert 'data-enh-group="Augurnium" open' in APP_HTML
    assert "selectedAugurnium" in STATE_JS
    assert "state.appConfig.augurnium" in ENH_JS
    # payload.js is frozen and never referenced the group (client-state chips).
    assert "ugurnium" not in PAYLOAD_JS


def test_display_title_map_drives_visible_labels():
    assert "Augurnium: 'Embellishments'" in ENH_JS
    assert "ENH_DISPLAY_TITLES[section.dataset.enhGroup]" in ENH_JS
    assert "addFieldset(bodies.Augurnium, ENH_DISPLAY_TITLES.Augurnium)" in ENH_JS
    assert "<summary>Augurnium</summary>" not in APP_HTML


def test_setup_graph_cache_token_swept():
    assert "js/pages/setup.js?v=red3-14" in APP_HTML
    assert "import { renderWorkflow } from '../pages/setup.js?v=red3-14';" in PASTE_JS


HARNESS_PRELUDE = r'''
import { renderEnhancements } from "./src/web/static/js/setup/enhancements.js";
class El {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.style = { setProperty() {} }; this.classList = { add() {}, toggle() {}, contains() { return false; } };
    this._text = ""; this.hidden = false; this.value = "";
  }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
  set innerHTML(v) { this.children = []; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener() {}
  setAttribute() {}
  closest() { return null; }
  querySelector() { return new El(); }
  querySelectorAll() { return []; }
}
const sections = ["Gems", "Enchantments", "Augurnium"].map(group => {
  const section = new El("details");
  section.dataset.enhGroup = group;
  section.summary = new El("summary");
  section.querySelector = sel => (sel === "summary" ? section.summary : new El());
  return section;
});
const bodies = new Map(sections.map(s => [
  `#enhancement-options [data-enh-group="${s.dataset.enhGroup}"] .enh-body`, new El(),
]));
const trio = new El("div");
trio.querySelectorAll = sel => (sel === ".enh-section" ? sections : []);
const search = new El("input");
globalThis.window = {};
globalThis.document = {
  createElement: tag => new El(tag),
  getElementById: id => (id === "enhancement-options" ? trio : id === "enh-search" ? search : new El()),
  querySelector: sel => bodies.get(sel) || new El(),
  querySelectorAll: () => [],
};
'''


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_rendered_summary_labels_say_embellishments_key_stays_augurnium():
    body = r'''
renderEnhancements();
const labels = sections.map(s => s.summary.textContent);
if (labels.join("|") !== "Gems (0)|Enchantments (0)|Embellishments (0)") {
  throw Error("rendered trio labels: " + labels.join("|"));
}
if (sections[2].dataset.enhGroup !== "Augurnium") {
  throw Error("data-enh-group value must stay Augurnium");
}
'''
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", HARNESS_PRELUDE + body],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
