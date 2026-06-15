from pathlib import Path


def test_urllib3_is_pinned_below_v2_for_system_python_libressl():
    requirements = Path("requirements.txt").read_text().splitlines()
    normalized = [line.strip().lower().replace(" ", "") for line in requirements]

    assert "urllib3<2" in normalized


def test_test_runner_installs_project_requirements():
    script = Path("scripts/run_tests.sh").read_text()

    assert "python3 -m pip install -r requirements.txt" in script
