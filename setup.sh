#!/usr/bin/env bash
set -e

VENV_DIR=".venv"
PYTHON="${PYTHON:-python3}"

echo "=== auto-translator setup ==="

# Check Python
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: Python 3 not found. Install from https://python.org"
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_VER" -lt 9 ]; then
    echo "ERROR: Python 3.9+ required"
    exit 1
fi

# Create venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate and install
source "$VENV_DIR/bin/activate"
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install pyyaml requests

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate venv:  source .venv/bin/activate"
echo "Run tool:       python translate.py --config config.yaml"
echo ""
echo "=== AI mode (recommended) ==="
echo "Edit config.yaml: set translation_type: 'ai' and fill in ai_config"
echo ""
echo "=== Local mode (offline) ==="
echo "pip install argostranslate"
echo "python -m argostranslate.package --install-package translate-en_zh"
echo "python -m argostranslate.package --install-package translate-en_es"
