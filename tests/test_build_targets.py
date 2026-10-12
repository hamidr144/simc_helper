from pathlib import Path


def test_cmake_exposes_fast_package_targets_and_clean_option():
    cmake = Path("CMakeLists.txt").read_text()

    assert 'option(PYINSTALLER_CLEAN "Run PyInstaller with --clean" OFF)' in cmake
    assert "add_linux_artifact_target(simc_master simc-master" in cmake
    assert "add_linux_artifact_target(simc_worker simc-worker" in cmake
    assert "add_linux_artifact_target(deploy_tool deploy" in cmake
    assert "add_linux_artifact_target(debug_cli debug_cli" in cmake
    assert "add_linux_artifact_target(package_all all" in cmake
    assert "add_custom_target(verified_package_all DEPENDS run_tests package_all)" in cmake
    assert "add_custom_target(simc_all ALL DEPENDS package_all)" in cmake


def test_cmake_linux_targets_build_only_requested_artifacts():
    cmake = Path("CMakeLists.txt").read_text()

    assert "-e SIMC_BUILD_ARTIFACTS=${artifact_name}" in cmake
    assert "add_linux_artifact_target(simc_master simc-master" in cmake
    assert "add_linux_artifact_target(simc_worker simc-worker" in cmake
    assert "add_linux_artifact_target(deploy_tool deploy" in cmake
    assert "add_linux_artifact_target(debug_cli debug_cli" in cmake
    assert "add_linux_artifact_target(package_all all" in cmake
    assert "SIMC_PYINSTALLER_CLEAN=${PYINSTALLER_CLEAN_VALUE}" in cmake
    assert "SIMC_PYINSTALLER_WORKPATH=/app/build_output/pyinstaller-work" in cmake


def test_docker_builds_are_driven_by_shared_script_not_hardcoded_clean_commands():
    linux_dockerfile = Path("Dockerfile.linux").read_text()
    windows_dockerfile = Path("Dockerfile.windows").read_text()
    dockerfile = Path("Dockerfile").read_text()
    build_script = Path("scripts/build_pyinstaller.sh").read_text()

    assert "scripts/build_pyinstaller.sh" in linux_dockerfile
    assert "scripts/build_pyinstaller.sh" in windows_dockerfile
    # The local Dockerfile is a plain source runtime for Compose; packaged
    # standalone artifacts are built only via CMake/Dockerfile.linux/windows.
    assert "Packaged standalone artifacts are built separately via CMake" in dockerfile
    assert "pyinstaller" not in dockerfile.lower()
    assert "pyinstaller --clean" not in linux_dockerfile
    assert "pyinstaller --clean" not in windows_dockerfile
    assert "SIMC_BUILD_ARTIFACTS" in build_script
    assert "SIMC_PYINSTALLER_CLEAN" in build_script
    assert "simc-master)" in build_script
    assert "simc-worker)" in build_script
    assert "requested=(simc-worker simc-master deploy debug_cli)" in build_script


def test_docker_context_excludes_local_build_outputs():
    dockerignore = Path(".dockerignore").read_text()

    assert "build/" in dockerignore
    assert "build_macos/" in dockerignore
    assert "dist/" in dockerignore
    assert "*.spec" in dockerignore


def test_dockerfile_is_single_stage_nonroot_runtime():
    """The local Dockerfile is a deliberate single-stage source runtime.

    Multi-stage packaging lives in Dockerfile.linux/.windows (CMake-driven);
    the local image must stay lean and run as a non-root user.
    """
    dockerfile = Path("Dockerfile").read_text()

    assert dockerfile.count("FROM ") == 1
    assert "useradd" in dockerfile
    assert "USER appuser" in dockerfile


def test_dockerfile_env_handling():
    """Runtime knobs live in the Dockerfile; secrets come from the environment.

    The local Dockerfile is a plain source runtime, so it must NOT bake in
    secret defaults (ADMIN_TOKEN/CLUSTER_SECRET) — those are supplied by
    docker-compose/.env at run time.
    """
    dockerfile = Path("Dockerfile").read_text()
    compose = Path("docker-compose.yml").read_text()

    for var in ["HOST", "PORT", "SIMC_HELPER_DEV_MODE"]:
        assert var in dockerfile

    for var in ["ADMIN_TOKEN", "CLUSTER_SECRET", "SIMC_PATH"]:
        assert var in compose

    # Secrets must never have hardcoded defaults baked into the image.
    assert "ADMIN_TOKEN=" not in dockerfile
    assert "CLUSTER_SECRET=" not in dockerfile


def test_dockerfile_healthcheck():
    """The Dockerfile should include a HEALTHCHECK directive."""
    dockerfile = Path("Dockerfile").read_text()

    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile


def test_dockerfile_exposes_port():
    """The Dockerfile should EXPOSE the configured port."""
    dockerfile = Path("Dockerfile").read_text()

    assert "EXPOSE" in dockerfile


def test_docker_compose_exists():
    """The docker-compose.yml should exist and contain expected services."""
    compose = Path("docker-compose.yml").read_text()

    assert "simc-master" in compose
    assert "simc-worker" in compose
    assert "simc-helper:latest" in compose


def test_docker_compose_healthcheck():
    """The docker-compose.yml should include healthcheck configuration."""
    compose = Path("docker-compose.yml").read_text()

    assert "healthcheck" in compose.lower()
    assert "/health" in compose


def test_docker_compose_redis_optional():
    """The docker-compose.yml should have an optional Redis service (commented out)."""
    compose = Path("docker-compose.yml").read_text()

    # Redis should be present but commented out with a profiles config
    assert "redis" in compose.lower()
    assert "# redis:" in compose  # commented out
    assert "profiles:" in compose  # enable via --profile
