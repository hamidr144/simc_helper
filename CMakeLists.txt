cmake_minimum_required(VERSION 3.10)
project(SimcraftHelperSuite NONE)

option(BUILD_WITH_TESTS "Run the test suite before building the executables" OFF)
option(PYINSTALLER_CLEAN "Run PyInstaller with --clean" OFF)
set(TARGET_PLATFORM "linux" CACHE STRING "Target platform to build for (linux, windows, macos)")

if(PYINSTALLER_CLEAN)
    set(PYINSTALLER_CLEAN_VALUE ON)
else()
    set(PYINSTALLER_CLEAN_VALUE OFF)
endif()

set(PYINSTALLER_SCRIPT ${CMAKE_SOURCE_DIR}/scripts/build_pyinstaller.sh)

if(TARGET_PLATFORM STREQUAL "linux")
    set(BUILDER_IMAGE simc-builder-linux)
    set(DOCKER_PLATFORM_ARGS --platform linux/amd64)
    set(BUILDER_DOCKERFILE Dockerfile.linux)

    function(add_linux_artifact_target target_name artifact_name comment_text)
        add_custom_target(${target_name}
            COMMAND docker build ${DOCKER_PLATFORM_ARGS} -t ${BUILDER_IMAGE} -f ${BUILDER_DOCKERFILE} .
            COMMAND docker run ${DOCKER_PLATFORM_ARGS} --rm
                -e SIMC_BUILD_ARTIFACTS=${artifact_name}
                -e SIMC_PYINSTALLER_CLEAN=${PYINSTALLER_CLEAN_VALUE}
                -e SIMC_PYINSTALLER_WORKPATH=/app/build_output/pyinstaller-work
                -v ${CMAKE_SOURCE_DIR}:/app
                -v ${CMAKE_BINARY_DIR}:/app/build_output
                ${BUILDER_IMAGE}
            COMMAND test -f ${CMAKE_BINARY_DIR}/${artifact_name}
            WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
            COMMENT ${comment_text}
        )
    endfunction()

    add_linux_artifact_target(simc_master simc-master "Building Linux x86_64 simc-master via Docker...")
    add_linux_artifact_target(simc_worker simc-worker "Building Linux x86_64 simc-worker via Docker...")
    add_linux_artifact_target(deploy_tool deploy "Building Linux x86_64 deploy tool via Docker...")
    add_linux_artifact_target(debug_cli debug_cli "Building Linux x86_64 debug_cli via Docker...")
    add_linux_artifact_target(package_all all "Building all Linux x86_64 executables via Docker...")
elseif(TARGET_PLATFORM STREQUAL "windows")
    set(BUILDER_IMAGE simc-builder-windows)
    set(BUILDER_DOCKERFILE Dockerfile.windows)

    function(add_windows_artifact_target target_name artifact_name comment_text)
        add_custom_target(${target_name}
            COMMAND docker build -t ${BUILDER_IMAGE} -f ${BUILDER_DOCKERFILE} .
            COMMAND docker run --rm
                -e SIMC_BUILD_ARTIFACTS=${artifact_name}
                -e SIMC_PYINSTALLER_CLEAN=${PYINSTALLER_CLEAN_VALUE}
                -e SIMC_PYINSTALLER_WORKPATH=z:/app/build_output/pyinstaller-work
                -v ${CMAKE_SOURCE_DIR}:/app
                -v ${CMAKE_BINARY_DIR}:/app/build_output
                ${BUILDER_IMAGE}
            WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
            COMMENT ${comment_text}
        )
    endfunction()

    add_windows_artifact_target(simc_master simc-master "Building Windows simc-master via Docker/Wine...")
    add_windows_artifact_target(simc_worker simc-worker "Building Windows simc-worker via Docker/Wine...")
    add_windows_artifact_target(deploy_tool deploy "Building Windows deploy tool via Docker/Wine...")
    add_windows_artifact_target(debug_cli debug_cli "Building Windows debug_cli via Docker/Wine...")
    add_windows_artifact_target(package_all all "Building all Windows executables via Docker/Wine...")
elseif(TARGET_PLATFORM STREQUAL "macos")
    function(add_macos_artifact_target target_name artifact_name comment_text)
        add_custom_target(${target_name}
            COMMAND python3 -m pip install --break-system-packages -r requirements.txt
            COMMAND python3 -m pip install --break-system-packages pyinstaller
            COMMAND ${CMAKE_COMMAND} -E env
                SIMC_BUILD_ARTIFACTS=${artifact_name}
                SIMC_PYINSTALLER_CLEAN=${PYINSTALLER_CLEAN_VALUE}
                SIMC_PYINSTALLER_CMD=python3\ -m\ PyInstaller
                SIMC_PYINSTALLER_WORKPATH=${CMAKE_BINARY_DIR}/pyinstaller-work
                SIMC_PYINSTALLER_DISTPATH=${CMAKE_BINARY_DIR}
                bash ${PYINSTALLER_SCRIPT}
            WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
            COMMENT ${comment_text}
        )
    endfunction()

    add_macos_artifact_target(simc_master simc-master "Building macOS simc-master natively...")
    add_macos_artifact_target(simc_worker simc-worker "Building macOS simc-worker natively...")
    add_macos_artifact_target(deploy_tool deploy "Building macOS deploy tool natively...")
    add_macos_artifact_target(debug_cli debug_cli "Building macOS debug_cli natively...")
    add_macos_artifact_target(package_all all "Building all macOS executables natively...")
else()
    message(FATAL_ERROR "Unsupported TARGET_PLATFORM: ${TARGET_PLATFORM}")
endif()

if(BUILD_WITH_TESTS)
    add_custom_target(run_tests
        COMMAND bash scripts/run_tests.sh
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        COMMENT "Running test suite..."
    )
    add_dependencies(package_all run_tests)
else()
    add_custom_target(run_tests
        COMMAND bash scripts/run_tests.sh
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        COMMENT "Running test suite..."
    )
endif()

add_custom_target(verified_package_all DEPENDS run_tests package_all)
add_custom_target(build_executables DEPENDS package_all)
add_custom_target(simc_all ALL DEPENDS package_all)
