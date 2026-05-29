#!/usr/bin/env bash
# Convenience wrapper: activates venv and runs translate.py
# Usage: ./run.sh --config config.yaml [--force]

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "ERROR: venv not found. Run ./setup.sh first."
    exit 1
fi

source "$VENV_DIR/bin/activate"
python translate.py "$@"
