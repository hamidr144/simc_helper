import os
import sys
from unittest.mock import MagicMock, patch

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from cli.sim_helper import (
    filter_best,
    get_all_combos,
    get_all_dps,
    get_character_name,
    get_default_filter,
    get_memory_based_batch_size,
    prepare_stage,
    run_simc,
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
    with patch("cli.sim_helper.pty.openpty", return_value=(master_fd, 11)), \
         patch("cli.sim_helper.subprocess.Popen", return_value=mock_proc), \
         patch("cli.sim_helper.os.close"), \
         patch("cli.sim_helper.select.select", return_value=([master_fd], [], [])), \
         patch("cli.sim_helper.os.read", side_effect=[b"Test 50/100 [==>] 100/1000\r", b""]), \
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
    with patch("cli.sim_helper.psutil", None):
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
         patch("cli.sim_helper.filter_best", return_value=["C1"]), \
         patch("cli.sim_helper.get_all_dps", return_value=[("C1", 100)]), \
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
