@echo off
setlocal

set VENV_DIR=.venv

echo === auto-translator setup ===

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    exit /b 1
)

if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate.bat
echo Installing dependencies...
pip install --upgrade pip -q
pip install pyyaml requests

echo.
echo === Setup complete ===
echo.
echo Activate venv:  .venv\Scripts\activate
echo Run tool:       python translate.py --config config.yaml
echo.
echo === AI mode (recommended) ===
echo Edit config.yaml: set translation_type: 'ai' and fill in ai_config
echo.
echo === Local mode (offline) ===
echo pip install argostranslate
echo python -m argostranslate.package --install-package translate-en_zh
