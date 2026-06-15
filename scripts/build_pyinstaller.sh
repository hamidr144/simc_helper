#!/usr/bin/env bash
set -euo pipefail

artifacts="${SIMC_BUILD_ARTIFACTS:-all}"
pyinstaller_cmd="${SIMC_PYINSTALLER_CMD:-pyinstaller}"
clean_flag="${SIMC_PYINSTALLER_CLEAN:-OFF}"
workpath="${SIMC_PYINSTALLER_WORKPATH:-/tmp/build}"
distpath="${SIMC_PYINSTALLER_DISTPATH:-./build_output}"
add_data_sep="${SIMC_ADD_DATA_SEP:-:}"

clean_args=()
case "${clean_flag}" in
    ON|on|TRUE|true|1|YES|yes)
        clean_args=(--clean)
        ;;
esac

run_pyinstaller() {
    # SIMC_PYINSTALLER_CMD intentionally supports command strings such as
    # "python3 -m PyInstaller" and "wine pyinstaller" for native/macOS and
    # Windows builds while keeping Docker/Linux builds at plain pyinstaller.
    ${pyinstaller_cmd} "${clean_args[@]+"${clean_args[@]}"}" -y --workpath "${workpath}" --distpath "${distpath}" "$@"
}

build_one() {
    case "$1" in
        simc-worker)
            run_pyinstaller \
                --onefile \
                --name simc-worker \
                --hidden-import utils.manage_simc \
                --hidden-import src.cli.sim_helper \
                src/worker.py
            ;;
        simc-master)
            run_pyinstaller \
                --onefile \
                --name simc-master \
                --add-data "src/web/static${add_data_sep}src/web/static" \
                --hidden-import src.cli.generate_input \
                --hidden-import src.cli.sim_helper \
                --hidden-import uvicorn.logging \
                --hidden-import uvicorn.loops \
                --hidden-import uvicorn.loops.auto \
                --hidden-import uvicorn.protocols \
                --hidden-import uvicorn.protocols.http \
                --hidden-import uvicorn.protocols.http.auto \
                --hidden-import uvicorn.protocols.websockets \
                --hidden-import uvicorn.protocols.websockets.auto \
                --hidden-import websockets \
                src/web/main.py
            ;;
        deploy)
            run_pyinstaller \
                --onefile \
                --name deploy \
                utils/deploy.py
            ;;
        debug_cli)
            run_pyinstaller \
                --onefile \
                --name debug_cli \
                utils/debug_cli.py
            ;;
        *)
            echo "Unknown artifact: $1" >&2
            exit 2
            ;;
    esac
}

IFS=',' read -r -a requested <<< "${artifacts}"
if [[ " ${requested[*]} " == *" all "* ]]; then
    requested=(simc-worker simc-master deploy debug_cli)
fi

for artifact in "${requested[@]}"; do
    build_one "${artifact}"
done
