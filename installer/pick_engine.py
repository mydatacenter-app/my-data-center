"""Picks the newest llama.cpp release that has engine files for Windows and both kinds of Mac.
Run in CI; prints the tag and writes it to $GITHUB_OUTPUT as engine_tag."""
import json
import os
import urllib.request

NEEDED = ["bin-win-vulkan-x64.zip", "bin-win-cpu-x64.zip", "bin-macos-arm64.tar.gz", "bin-macos-x64.tar.gz"]
headers = {"Accept": "application/vnd.github+json", "User-Agent": "MyDataCenter-build"}
if os.environ.get("GITHUB_TOKEN"):
    headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
req = urllib.request.Request("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30", headers=headers)
releases = json.load(urllib.request.urlopen(req, timeout=60))
for rel in releases:
    if rel.get("draft"):  # llama.cpp marks every release as a pre-release, so those are fine
        continue
    names = [a["name"] for a in rel.get("assets", [])]
    tag = rel["tag_name"]
    if all(f"llama-{tag}-{n}" in names for n in NEEDED):
        print("engine", tag)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"engine_tag={tag}\n")
        break
else:
    raise SystemExit("No llama.cpp release has all the needed files")
