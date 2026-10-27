#!/bin/bash
cd "$(dirname "$0")/.."
VENV="$HOME/MyDataCenter/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; assert sys.version_info >= (3, 9)" >/dev/null 2>&1; then
    echo ""
    echo "  Python 3 is needed. A macOS prompt will appear to install it."
    echo "  When it finishes, double-click this file again."
    echo ""
    xcode-select --install 2>/dev/null
    read -p "Press Enter to close..."
    exit 1
  fi
  echo ""
  echo "  First-time setup: installing My Data Center (about a minute)..."
  echo ""
  mkdir -p "$HOME/MyDataCenter"
  python3 -m venv "$VENV" && "$VENV/bin/python" -m pip install --upgrade pip -q \
    && "$VENV/bin/python" -m pip install -q -r requirements.txt || {
      echo "  Setup failed. Check your internet connection and try again."
      rm -rf "$VENV"; read -p "Press Enter to close..."; exit 1; }
fi

echo "  My Data Center is open. You can close this Terminal window."
nohup "$VENV/bin/python" mydatacenter.py >/dev/null 2>&1 &
disown
exit 0
