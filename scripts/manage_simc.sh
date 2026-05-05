#!/bin/bash
set -e

SIMC_DIR="$HOME/.simc"

echo "Checking SimulationCraft repository..."

if [ ! -d "$SIMC_DIR" ]; then
    echo "SimulationCraft repository not found. Cloning..."
    git clone https://github.com/simulationcraft/simc.git "$SIMC_DIR"
else
    echo "SimulationCraft repository found. Pulling latest changes..."
    cd "$SIMC_DIR"
    git pull
    cd - > /dev/null
fi

echo "Building SimulationCraft Engine..."
make -C "$SIMC_DIR/engine" optimized -j$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

echo "Build complete."
