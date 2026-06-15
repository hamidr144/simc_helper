import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_generate_input_main(tmp_path):
    from cli.generate_input import main
    addon_content = 'paladin="Test"\nhead=id=1\n### Gear from Bags\n# waist=id=2\n'
    addon_file = tmp_path / "addon.txt"
    addon_file.write_text(addon_content)
    with patch("sys.argv", ["generate_input.py"]), \
         patch("builtins.input", side_effect=[str(addon_file), "Test.simc", "n"]), \
         patch("cli.generate_input.load_config", return_value={}), \
         patch("builtins.open", MagicMock()):
        try: main()
        except SystemExit: pass

def test_sim_helper_batched_flow(tmp_path):
    from cli.sim_helper import main
    input_file = tmp_path / "test.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    combos = [f"Combo_{i}" for i in range(500)]
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=0"]), \
         patch("cli.sim_helper.os.path.exists", return_value=True), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=combos), \
         patch("cli.sim_helper.run_simc", return_value=0) as mock_run, \
         patch("cli.sim_helper.filter_best", return_value=["C1"]), \
         patch("cli.sim_helper.get_all_dps", return_value=[("C1", 100)]), \
         patch("cli.sim_helper.get_memory_based_batch_size", return_value=200):
        with patch("cli.sim_helper.prepare_stage"):
            main()
        assert mock_run.call_count >= 5

def test_sim_helper_main_no_combos(tmp_path):
    from cli.sim_helper import main
    input_file = tmp_path / "test.simc"
    input_file.write_text('paladin="Test"\n')
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=0"]), \
         patch("cli.sim_helper.os.path.exists", return_value=True), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=[]), \
         patch("cli.sim_helper.subprocess.Popen"), \
         patch("cli.sim_helper.pty.openpty", return_value=(10,11)), \
         patch("cli.sim_helper.os.close"), \
         patch("builtins.print") as mock_print:
        with pytest.raises(SystemExit) as e: main()
        assert e.value.code == 1

def test_sim_helper_main_no_character(tmp_path):
    from cli.sim_helper import main
    input_file = tmp_path / "test.simc"
    input_file.write_text('copy="C1,T"\n')
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}", "start_server=0"]), \
         patch("cli.sim_helper.os.path.exists", return_value=True), \
         patch("cli.sim_helper.get_character_name", return_value=None), \
         patch("cli.sim_helper.subprocess.Popen"), \
         patch("cli.sim_helper.pty.openpty", return_value=(10,11)), \
         patch("cli.sim_helper.os.close"), \
         patch("builtins.print") as mock_print:
        with pytest.raises(SystemExit) as e: main()
        assert e.value.code == 1

def test_sim_helper_main_help():
    from cli.sim_helper import main
    with patch("sys.argv", ["sim_helper.py"]), \
         patch("builtins.print") as mock_print:
        with pytest.raises(SystemExit) as e: main()
        assert e.value.code == 1
        # Check for start of usage string
        found = False
        for call in mock_print.mock_calls:
            if call.args and "Usage:" in str(call.args[0]):
                found = True; break
        assert found
