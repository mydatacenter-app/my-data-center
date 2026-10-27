"""Picks the newest llama.cpp release whose Windows and Mac engine packages exist AND actually
contain llama-server plus the RPC server, by downloading and listing each package.
Writes the tag to $GITHUB_OUTPUT as engine_tag."""
import io
import json
import os
import tarfile
import urllib.request
import zipfile

NEEDED = ["bin-win-vulkan-x64.zip", "bin-macos-arm64.tar.gz", "bin-macos-x64.tar.gz"]
SERVER = ("llama-server",)
RPC = ("ggml-rpc-server", "rpc-server")
H = {"User-Agent": "MyDataCenter-build"}
API = dict(H, Accept="application/vnd.github+json")
if os.environ.get("GITHUB_TOKEN"):
    API["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]


def names_in(url):
    data = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=300).read()
    if url.endswith(".zip"):
        return [n.rsplit("/", 1)[-1] for n in zipfile.ZipFile(io.BytesIO(data)).namelist()]
    return [n.rsplit("/", 1)[-1] for n in tarfile.open(fileobj=io.BytesIO(data)).getnames()]


def has(files, stems):
    return any(f in (s, s + ".exe") for f in files for s in stems)


releases = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30", headers=API), timeout=60))
checked = 0
for rel in releases:
    if rel.get("draft"):  # llama.cpp marks every release as a pre-release, so those are fine
        continue
    tag = rel["tag_name"]
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    wanted = [f"llama-{tag}-{n}" for n in NEEDED]
    if not all(w in assets for w in wanted):
        continue
    checked += 1
    ok = True
    for w in wanted:
        files = names_in(assets[w])
        if not (has(files, SERVER) and has(files, RPC)):
            print(f"::warning::{w} is missing llama-server or the RPC server")
            ok = False
            break
    if ok:
        print("engine", tag)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"engine_tag={tag}\n")
        break
    if checked >= 5:
        raise SystemExit("::error::Recent llama.cpp releases are missing the RPC server")
else:
    raise SystemExit("::error::No llama.cpp release has all the needed files")
