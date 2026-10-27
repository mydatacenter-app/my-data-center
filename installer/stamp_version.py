"""Writes the app version (APP_VERSION) and pinned engine version (ENGINE_TAG) into mydatacenter.py."""
import os
import re
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "mydatacenter.py"
s = p.read_text(encoding="utf-8")
v, tag = os.environ["APP_VERSION"], os.environ["ENGINE_TAG"]
s = re.sub(r'^VERSION = .*$', f'VERSION = "{v}"', s, flags=re.M)
s = re.sub(r'^ENGINE_TAG = .*$', f'ENGINE_TAG = "{tag}"', s, flags=re.M)
p.write_text(s, encoding="utf-8")
print("version", v, "engine", tag)
