"""Writes the build's version number (APP_VERSION) into mydatacenter.py."""
import os
import re
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "mydatacenter.py"
v = os.environ["APP_VERSION"]
p.write_text(re.sub(r'^VERSION = .*$', f'VERSION = "{v}"', p.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
print("version", v)
