from src.cli.sim_helper import run_simc


def test_run_simc_reports_missing_engine_without_traceback(tmp_path, capsys):
    exit_code = run_simc(str(tmp_path / "missing-simc"), "input.simc", "", str(tmp_path / "output.log"))

    assert exit_code == 127
    assert "SimulationCraft engine is unavailable" in capsys.readouterr().out
