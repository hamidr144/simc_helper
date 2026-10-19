import os
import sys
from unittest.mock import MagicMock, patch

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from cli.sim_helper import (
    cull_k,
    filter_best,
    get_actor_summaries,
    get_all_combos,
    get_all_dps,
    get_character_name,
    get_default_filter,
    get_memory_based_batch_size,
    get_stage_plan,
    prepare_stage,
    run_simc,
    select_survivors,
    stage_args,
)


def test_get_default_filter():
    assert get_default_filter(1, 100) == "25%"
    assert get_default_filter(1, 500) == "15%"
    assert get_default_filter(1, 2000) == "10%"
    assert get_default_filter(2, 20) == "50%"
    assert get_default_filter(2, 100) == "20%"
    assert get_default_filter(2, 500) == "10%"

def test_get_character_name(tmp_path):
    f = tmp_path / "t.simc"
    f.write_text('paladin="Hamidriel"\n')
    assert get_character_name(str(f)) == "Hamidriel"

def test_get_character_name_missing(tmp_path):
    f = tmp_path / "m.simc"
    f.write_text("head=id=1")
    assert get_character_name(str(f)) is None

def test_get_all_combos(tmp_path):
    f = tmp_path / "t.simc"
    f.write_text('paladin="H"\ncopy="C1,H"\ncopy="C2,H"\n')
    assert len(get_all_combos(str(f), current_name="H")) == 2

def test_get_memory_based_batch_size():
    assert get_memory_based_batch_size() <= 200

def test_run_simc_progress_parsing(tmp_path):
    mock_proc = MagicMock()
    mock_proc.poll.side_effect = [None, 0]
    mock_proc.wait.return_value = 0
    mock_proc.returncode = 0
    master_fd = 10
    # select: first call has data, then no-ready so the loop drains and exits
    # once poll() reports the process finished.
    select_ready = ([master_fd], [], [])
    select_idle = ([], [], [])
    with patch("cli.sim_helper.os.path.isfile", return_value=True), \
         patch("cli.sim_helper.os.access", return_value=True), \
         patch("cli.sim_helper.pty.openpty", return_value=(master_fd, 11)), \
         patch("cli.sim_helper.subprocess.Popen", return_value=mock_proc), \
         patch("cli.sim_helper.os.close"), \
         patch("cli.sim_helper.select.select", side_effect=[select_ready, select_idle, select_idle]), \
         patch("cli.sim_helper.os.read", side_effect=[b"Combo_50 50/100 [==>] 100/1000\r", b""]), \
         patch("cli.sim_helper.print") as mock_print:
        run_simc("simc", "in", "", str(tmp_path / "p.log"))
        found = False
        for call in mock_print.mock_calls:
            if call.args and "50%" in str(call.args[0]):
                found = True; break
        assert found

def test_get_all_combos_error():
    assert get_all_combos("non-existent.simc") == []

def test_filter_best(tmp_path):
    f = tmp_path / "t.log"
    f.write_text("DPS Ranking:\n 100 100% H\n 90 90% C1\n 80 80% C2\n")
    assert len(filter_best(str(f), "50%", current_name="H")) == 1

def test_filter_best_absolute(tmp_path):
    f = tmp_path / "abs.log"
    f.write_text("DPS Ranking:\n 100 100% H\n 90 90% C1\n 80 80% C2\n")
    assert filter_best(str(f), "1", current_name="H") == ["C1"]

def test_get_all_dps_empty(tmp_path):
    f = tmp_path / "e.log"
    f.write_text("noise")
    assert get_all_dps(str(f)) == []

def test_prepare_stage_with_header(tmp_path):
    f_in = tmp_path / "in.simc"
    f_in.write_text("iterations=1000\nactive=1\npaladin=T\ncopy=C1,T\n")
    f_out = tmp_path / "out.simc"
    prepare_stage(str(f_in), ["C1"], str(f_out), "iterations=100")
    assert "# iterations=1000" in f_out.read_text()

def test_get_memory_based_batch_size_fallbacks():
    # also mask /proc/meminfo: the fallback contract is "no RAM source at
    # all"; Linux (CI ubuntu) has /proc even when psutil is patched away,
    # macOS happens not to — macos-only pass was masking RAM-detected values.
    with patch("cli.sim_helper.psutil", None), patch("builtins.open", side_effect=FileNotFoundError):
        assert get_memory_based_batch_size() == 200

def test_main_with_server(tmp_path):
    from cli.sim_helper import main
    input_file = tmp_path / "test.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,Test"\n')
    
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=1"]), \
         patch("cli.sim_helper.os.path.exists", return_value=True), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=["C1"]), \
         patch("cli.sim_helper.run_simc", return_value=0), \
         patch("cli.sim_helper.get_actor_summaries", return_value=[("C1", 100.0, None, False)]), \
         patch("cli.sim_helper.prepare_stage"), \
         patch("cli.sim_helper.subprocess.Popen") as mock_popen, \
         patch("cli.sim_helper.socket.socket") as mock_socket, \
         patch("cli.sim_helper.webbrowser.open") as mock_browser, \
         patch("cli.sim_helper.time.sleep"), \
         patch("builtins.input", return_value=""):
        
        mock_socket.return_value.getsockname.return_value = ["127.0.0.1"]
        main()
        assert mock_popen.called
        assert mock_browser.called

def test_run_simc_complex_output(tmp_path):
    mock_proc = MagicMock()
    mock_proc.poll.side_effect = [None, None, 0]
    mock_proc.wait.return_value = 0
    mock_proc.returncode = 0
    with patch("cli.sim_helper.pty.openpty", return_value=(10, 11)), \
         patch("cli.sim_helper.subprocess.Popen", return_value=mock_proc), \
         patch("cli.sim_helper.os.close"), \
         patch("cli.sim_helper.os.read", side_effect=[b"A 1/1 [>] 1/1\r", b"B 1/1 [>] 1/1\r", b""]), \
         patch("cli.sim_helper.print"):
        run_simc("s", "i", "", str(tmp_path / "c.log"))

def test_get_character_name_quoted(tmp_path):
    f = tmp_path / "q.simc"
    f.write_text("paladin='Hamidriel'\n")
    assert get_character_name(str(f)) == "Hamidriel"


def test_main_zero_combos_runs_baseline_report(tmp_path, capsys):
    """t_4485565b: an input with no copy= blocks must produce a baseline
    current-gear HTML report instead of exiting 1 with 'No combos found'."""
    from cli.sim_helper import main
    input_file = tmp_path / "baseline.simc"
    input_file.write_text('paladin="Test"\n')

    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=[]), \
         patch("cli.sim_helper.run_simc", return_value=0) as mock_run, \
         patch("cli.sim_helper.filter_best") as mock_filter, \
         patch("cli.sim_helper.prepare_stage") as mock_prepare:
        main()  # must NOT raise SystemExit

    out = capsys.readouterr().out
    assert "BASELINE" in out
    assert "No combos found" not in out
    assert "Simcraft Helper complete!" in out

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[1] == str(input_file)  # base profile simulated directly
    # final-stage precision plan (TG2-C), not a bare full-precision run
    assert args[2] == "iterations=20000 target_error=0.05% single_actor_batch=1"
    assert str(kwargs.get("html_report", "")).endswith(".html")
    mock_filter.assert_not_called()
    mock_prepare.assert_not_called()


def test_main_zero_combos_baseline_failure_exits(tmp_path, capsys):
    """A failing baseline simulation still surfaces a non-zero exit."""
    import pytest
    from cli.sim_helper import main
    input_file = tmp_path / "baseline.simc"
    input_file.write_text('paladin="Test"\n')

    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=[]), \
         patch("cli.sim_helper.run_simc", return_value=1):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1
    assert "baseline simulation" in capsys.readouterr().out


# =========================================================================
# TG2-C staged precision parity + error-band culling (t_590f5317,
# design t_0fbfd0bd §5). Engine facts certified step-0 on simc `midnight`
# report_text.cpp: DPS line is 'DPS=<mean> DPS-Error=<abs>/<rel>% ...' and
# DPS-Error is the 95% CI half-width (1.96*sigma_mean) of the sample mean.
# =========================================================================

CONSOLE_LOG = """Simulating... ( iterations=1000, threads=14, target_error=0.000 )

DPS Ranking:
  100500 100.0%  Raid
  100499 100.0%  Test
   99200  98.7%  C1
   98000  97.5%  Combo 3
   97000  96.5%  Ghost
       0   0.0%  Dead

HPS Ranking:
      0 100.0%%  Raid

Player: Test
  Blood Elf paladin (Retribution, 90)
  DPS=100498.75 DPS-Error=200.99/0.20% DPS-Range=1000.5/0.99%
Player: C1
  Blood Elf paladin (Retribution, 90)
  DPS=99200.5 DPS-Error=396.8/0.40% DPS-Range=1500.0/1.51%
Player: Combo 3
  Blood Elf paladin (Retribution, 90)
  DPS=98000.25 DPS-Error=980.0/1.00% DPS-Range=3000.0/3.06%
Player: Dead
  Blood Elf paladin (Retribution, 90)
  HPS=5.0 HPS-Error=1.0/20.00% HPS-Range=40.0/800.00%
"""


def test_get_actor_summaries_parses_player_summaries(tmp_path):
    f = tmp_path / "c.log"
    f.write_text(CONSOLE_LOG)
    got = get_actor_summaries(str(f), current_name="Test")
    # Ranking order; Raid + current excluded; Dead quarantined (dps<=0);
    # Ghost has no Player summary block -> ok=False, mean from ranking.
    assert got == [
        ("C1", 99200.5, 0.40, True),
        ("Combo 3", 98000.25, 1.00, True),
        ("Ghost", 97000.0, None, False),
    ]
    assert get_actor_summaries(str(f))[0] == ("Test", 100498.75, 0.20, True)
    assert get_actor_summaries(str(tmp_path / "missing.log")) == []
    # Legacy wrapper: integer means, name order preserved.
    assert get_all_dps(str(f), current_name="Test") == [("C1", 99200), ("Combo 3", 98000), ("Ghost", 97000)]


def test_get_stage_plan_default_and_env(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_STAGE_PLAN", raising=False)
    assert get_stage_plan() == [(200, 1.0), (5000, 0.2), (20000, 0.05)]
    assert stage_args(get_stage_plan(), 0) == "iterations=200 target_error=1% single_actor_batch=1"
    assert stage_args(get_stage_plan(), 1) == "iterations=5000 target_error=0.2% single_actor_batch=1"
    assert stage_args(get_stage_plan(), 2) == "iterations=20000 target_error=0.05% single_actor_batch=1"
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "20:1;40:0.2;60:0.05")
    assert get_stage_plan() == [(20, 1.0), (40, 0.2), (60, 0.05)]
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "0:0;999999:9;5:0.001")
    assert get_stage_plan() == [(1, 0.01), (100000, 5.0), (5, 0.01)]


def test_get_stage_plan_malformed_warns_and_defaults(monkeypatch, capsys):
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "garbage")
    assert get_stage_plan() == [(200, 1.0), (5000, 0.2), (20000, 0.05)]
    assert "Warning" in capsys.readouterr().out
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "100:1;200:0.2")  # wrong arity
    assert get_stage_plan() == [(200, 1.0), (5000, 0.2), (20000, 0.05)]


def test_cull_k(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    assert cull_k() == 1.0
    monkeypatch.setenv("SIMC_HELPER_CULL_K", "0.5")
    assert cull_k() == 0.5
    monkeypatch.setenv("SIMC_HELPER_CULL_K", "bogus")
    assert cull_k() == 1.0


def test_select_survivors_error_band(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    # top 100+-1 -> bound 99: B (99.0+1.0) overlaps, C (80+1) is 18 full bands out.
    s = [("A", 100.0, 1.0, True), ("B", 99.0, 1.0, True), ("C", 80.0, 1.0, True)]
    assert select_survivors(s, 2) == ["A", "B"]
    monkeypatch.setenv("SIMC_HELPER_CULL_K", "0.5")  # bound 99.5: B (99.5) just misses
    assert select_survivors(s, 2) == ["A"]
    monkeypatch.setenv("SIMC_HELPER_CULL_K", "40")   # everything falls in band
    assert select_survivors(s, 2) == ["A", "B", "C"]
    assert select_survivors([], 2) == []


def test_select_survivors_missing_errors_use_count_rule(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    s = [("A", 100.0, None, False), ("B", 99.0, None, False), ("C", 98.0, None, False)]
    assert select_survivors(s, 2) == ["A", "B"]
    assert select_survivors(s, 3, override="2") == ["A", "B"]
    assert select_survivors(s, 3, override="34%") == ["A", "B"]
    # Band active: a missing-error entry only survives inside the count rule.
    mixed = [("A", 100.0, 1.0, True), ("B", 99.9, None, False), ("X", 99.8, None, False)]
    assert select_survivors(mixed, 2) == ["A", "B"]
    assert select_survivors(mixed, 1) == ["A"]
    # User override only feeds the count basis; the keep-set is the band
    # (Z's band at 97.51) plus missing-error entries inside the count 1.
    assert select_survivors(s[:2] + [("Z", 98.0, 0.5, True)], 3, override="1") == ["A", "Z"]


def test_select_survivors_cost_cap_prints_and_keeps_top_means(monkeypatch, capsys):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    s = [(f"C{i}", 100.0 - i * 0.01, 1.0, True) for i in range(40)]
    out = select_survivors(s, 5)  # cap = max(25, 3*5) = 25
    assert out == [f"C{i}" for i in range(25)]  # top means, rank order kept
    assert "Culled 15 statistically-tied candidates to fit the work budget" in capsys.readouterr().out


def test_main_stage_commands_carry_precision(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "20:1;40:0.2;60:0.05")
    from cli.sim_helper import main
    input_file = tmp_path / "t.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=0"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=["C1"]), \
         patch("cli.sim_helper.run_simc", return_value=0) as run, \
         patch("cli.sim_helper.prepare_stage") as prep, \
         patch("cli.sim_helper.get_actor_summaries", return_value=[("C1", 100.0, 0.5, True)]):
        main()
    out = capsys.readouterr().out
    assert [c.args[2] for c in run.call_args_list] == [
        "iterations=20 target_error=1% single_actor_batch=1",
        "iterations=40 target_error=0.2% single_actor_batch=1",
        "iterations=60 target_error=0.05% single_actor_batch=1",
    ]
    # prepare_stage gets the same args as files; the CLI stays authoritative.
    assert [c.args[3] for c in prep.call_args_list] == [
        "iterations=40 target_error=0.2% single_actor_batch=1",
        "iterations=60 target_error=0.05% single_actor_batch=1",
    ]
    # STAGE 1 header surfaces target_error, completion line unchanged.
    assert "STAGE 1: Fast Filtering (iterations=20 target_error=1% single_actor_batch=1)" in out
    assert "Simcraft Helper complete!" in out


def test_main_batched_stage1_culls_globally_within_band(tmp_path, monkeypatch, capsys):
    from cli.sim_helper import main
    input_file = tmp_path / "t.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    combos = [f"C{i}" for i in range(401)]
    # Batch 1: A1 at top; batch 2: B1 within A1's band; batch 3: far off C9.
    per_batch = [
        [("A1", 100.0, 0.5, True)],
        [("B1", 99.0, 1.0, True)],
        [("C9", 10.0, 0.5, True)],
        [("A1", 100.0, 0.2, True), ("B1", 99.0, 0.2, True)],  # stage 2 summaries
        [("A1", 100.0, 0.05, True), ("B1", 99.0, 0.05, True)],  # stage 3 never re-filters
    ]
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=0"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=combos), \
         patch("cli.sim_helper.get_memory_based_batch_size", return_value=200), \
         patch("cli.sim_helper.run_simc", return_value=0), \
         patch("cli.sim_helper.prepare_stage"), \
         patch("cli.sim_helper.get_actor_summaries", side_effect=per_batch):
        main()
    out = capsys.readouterr().out
    assert "Kept 2 profiles within the error band for Stage 2." in out
    assert "Simcraft Helper complete!" in out


def test_main_stage2_override_is_count_cap_not_selector(tmp_path, monkeypatch, capsys):
    from cli.sim_helper import main
    input_file = tmp_path / "t.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    s2 = [("A1", 100.0, 0.5, True), ("B1", 99.0, 0.5, True)]  # banded -> override "1" must NOT pick 1
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}",
                            "start_server=0", "stage2_percent_best=1"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=["C1", "C2"]), \
         patch("cli.sim_helper.run_simc", return_value=0), \
         patch("cli.sim_helper.prepare_stage"), \
         patch("cli.sim_helper.get_actor_summaries", return_value=s2):
        main()
    out = capsys.readouterr().out
    assert "using 1" in out  # stage-2 header echoes the override verbatim
    assert "Simcraft Helper complete!" in out
    # A1 and B1 both advance: band rule, not the literal count 1.
    assert "STAGE 2: Refinement" in out
