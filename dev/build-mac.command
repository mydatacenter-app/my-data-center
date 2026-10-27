#!/bin/bash
# Builds "My Data Center.app" (run on a Mac). Output: dist/My Data Center.app
cd "$(dirname "$0")/.."
python3 -m venv .buildenv
.buildenv/bin/python -m pip install -q --upgrade pip
.buildenv/bin/python -m pip install -q -r requirements.txt pyinstaller
.buildenv/bin/pyinstaller --noconfirm --clean --windowed --name "My Data Center" \
  --icon assets/icon.icns --add-data "ui.html:." \
  --osx-bundle-identifier com.mydatacenter.app mydatacenter.py
# allow incoming connections without the app being signed
codesign --force --deep --sign - "dist/My Data Center.app" 2>/dev/null
echo ""
echo "Done: dist/My Data Center.app  (drag it into Applications)"
read -p "Press Enter to close..."
