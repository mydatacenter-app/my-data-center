#!/usr/bin/env python3
"""
My Data Center — desktop app
Pool the computers on your network into one AI cluster.

Every computer runs this app. They find each other on the local network.
"Sharing" lends a computer's RAM/GPU to the cluster (llama.cpp rpc-server).
The host loads a model split across every shared computer and chats with it.
"""
import argparse
import collections
import ctypes
import json
import os
import platform
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import certifi
except ImportError:
    certifi = None

try:
    import psutil
except ImportError:  # app still works, just without live CPU/RAM graphs
    psutil = None

VERSION = "0.2.0"
APP_ID = "mydatacenter"
DISCOVERY_PORT = 8801
RPC_PORT = 50052
RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=15"
UPDATE_REPO = "mydatacenter-app/my-data-center"
ENGINE_TAG = ""  # set at build time to a llama.cpp release that has files for Windows and Mac
UA = {"User-Agent": f"MyDataCenter/{VERSION}"}


def make_ssl_context():
    """Trust a bundled certificate list plus the computer's own. Fresh Windows installs often
    haven't downloaded the root certificates GitHub uses yet, which breaks downloads otherwise."""
    ctx = ssl.create_default_context()
    if certifi:
        try:
            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
    return ctx


urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=make_ssl_context())))

PRESETS = [
    {"name": "Llama 3.2 3B", "note": "Small and fast. Runs on one laptop.", "gb": 2.0,
     "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"},
    {"name": "Qwen 2.5 7B", "note": "Good all-rounder. 8 GB+ RAM.", "gb": 4.7,
     "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"},
    {"name": "Qwen 2.5 14B", "note": "Smarter. Pool 2 computers.", "gb": 9.0,
     "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf"},
    {"name": "Qwen 2.5 32B", "note": "Big brain. Pool 3+ computers.", "gb": 19.9,
     "url": "https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q4_K_M.gguf"},
]

MODES = {
    "eco": {"label": "Eco", "cpu": 0.25, "priority": "low",
            "desc": "Quiet and cool. Uses about a quarter of the CPU at low priority, so the computer stays usable."},
    "balanced": {"label": "Balanced", "cpu": 0.5, "priority": "normal",
                 "desc": "Half the CPU at normal priority. Good default for most computers."},
    "max": {"label": "Max", "cpu": 1.0, "priority": "high",
            "desc": "Every CPU core at high priority. Fastest, loudest. Best for a dedicated machine."},
}


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


# ----------------------------------------------------------------- settings --
ap = argparse.ArgumentParser(description="My Data Center")
ap.add_argument("--port", type=int, default=8800, help="dashboard port (default 8800)")
ap.add_argument("--home", default=str(Path.home() / "MyDataCenter"), help="data folder")
ap.add_argument("--browser", action="store_true", help="open in your web browser instead of an app window")
ap.add_argument("--headless", action="store_true", help="no window at all (for always-on helper computers)")
ARGS, _ = ap.parse_known_args()

DASH_PORT = ARGS.port
LLAMA_PORT = DASH_PORT + 2
HOME = Path(ARGS.home)
ENGINE_DIR = HOME / "engine"
MODEL_DIR = HOME / "models"
DL_DIR = HOME / "downloads"
CONFIG_PATH = HOME / "config.json"
CHATS_PATH = HOME / "chats.json"
for d in (HOME, ENGINE_DIR, MODEL_DIR, DL_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOCK = threading.RLock()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


CONFIG = load_json(CONFIG_PATH, {})
CONFIG.setdefault("id", uuid.uuid4().hex[:12])
CONFIG.setdefault("name", socket.gethostname().split(".")[0][:32] or "computer")
CONFIG.setdefault("share_on_start", False)
CONFIG.setdefault("manual_peers", [])
CONFIG.setdefault("mode", "balanced")
if CONFIG["mode"] not in MODES:
    CONFIG["mode"] = "balanced"


def save_config():
    with LOCK:
        CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2), encoding="utf-8")


save_config()

# ------------------------------------------------------------- system info --
OS_NAME = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(platform.system(), platform.system())
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def total_ram_gb():
    if psutil:
        return psutil.virtual_memory().total / 2**30
    try:
        s = platform.system()
        if s == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5).strip()) / 2**30
        if s == "Windows":
            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMSTAT()
            m.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 2**20
    except Exception:
        return 0.0


def gpu_name():
    try:
        s = platform.system()
        if s == "Darwin":
            if platform.machine() == "arm64":
                chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5, text=True).strip()
                return f"{chip} GPU"
            return "Intel Mac (CPU)"
        if shutil.which("nvidia-smi"):
            out = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                          timeout=5, text=True, creationflags=NO_WINDOW).strip().splitlines()
            if out:
                return out[0]
        if s == "Windows":
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)"],
                timeout=10, text=True, creationflags=NO_WINDOW).strip()
            return out or "Unknown GPU"
    except Exception:
        pass
    return "CPU only"


def cpu_cores():
    if psutil:
        return psutil.cpu_count(logical=False) or psutil.cpu_count() or 4
    return os.cpu_count() or 4


RAM_GB = round(total_ram_gb(), 1)
GPU = gpu_name()
CORES = cpu_cores()
HAS_NVIDIA = bool(shutil.which("nvidia-smi"))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------- live stats --
STATS = {"cpu": 0.0, "ram_used": 0.0, "gpu": None, "vram_used": None, "vram_total": None}
HIST = collections.deque(maxlen=120)        # one sample per second
TPS_HIST = collections.deque(maxlen=60)     # one sample per chat reply


def sample_gpu():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            timeout=3, text=True, creationflags=NO_WINDOW).strip().splitlines()[0]
        u, used, tot = (float(x) for x in out.split(","))
        return u, used / 1024, tot / 1024
    except Exception:
        return None, None, None


def sampler_loop():
    if psutil:
        psutil.cpu_percent(None)
    n = 0
    while True:
        time.sleep(1)
        cpu = psutil.cpu_percent(None) if psutil else 0.0
        ram = psutil.virtual_memory().used / 2**30 if psutil else 0.0
        gpu = vram = vtot = None
        if HAS_NVIDIA and n % 2 == 0:
            gpu, vram, vtot = sample_gpu()
        with LOCK:
            STATS.update(cpu=round(cpu, 1), ram_used=round(ram, 2))
            if gpu is not None:
                STATS.update(gpu=gpu, vram_used=round(vram, 2), vram_total=round(vtot, 1))
            HIST.append({"t": round(time.time()), "cpu": STATS["cpu"], "ram": STATS["ram_used"], "gpu": STATS["gpu"]})
        n += 1


# ------------------------------------------------------------------ engine --
ENGINE = {"state": "missing", "progress": 0.0, "error": "", "version": "", "bin": ""}
ENGINE_META = ENGINE_DIR / "engine.json"
EXE = ".exe" if os.name == "nt" else ""


RPC_NAMES = ("ggml-rpc-server", "rpc-server")  # llama.cpp renamed it; accept both


def rpc_exe(bin_dir):
    for n in RPC_NAMES:
        p = Path(bin_dir) / f"{n}{EXE}"
        if p.exists():
            return p
    return None


def refresh_engine():
    with LOCK:
        if ENGINE["state"] == "installing":
            return
        meta = load_json(ENGINE_META, None)
        if meta:
            b = Path(meta.get("bin", ""))
            if (b / f"llama-server{EXE}").exists() and rpc_exe(b):
                ENGINE.update(state="ready", version=meta["version"], bin=str(b), error="")
                return
        if ENGINE["state"] != "error":
            ENGINE.update(state="missing", version="", bin="")


def wanted_suffixes():
    """Release file endings for this computer, best first."""
    s, m = platform.system(), platform.machine().lower()
    arm = m in ("arm64", "aarch64")
    if s == "Darwin":
        return ["bin-macos-arm64.tar.gz", "bin-macos-arm64.zip"] if arm else ["bin-macos-x64.tar.gz", "bin-macos-x64.zip"]
    if s == "Windows":
        # Vulkan build runs on NVIDIA, AMD and Intel GPUs with no extra installs; CPU build as fallback
        a = "arm64" if arm else "x64"
        return [f"bin-win-vulkan-{a}.zip", f"bin-win-cpu-{a}.zip"]
    a = "arm64" if arm else "x64"
    return [f"bin-ubuntu-vulkan-{a}.tar.gz", f"bin-ubuntu-{a}.tar.gz"]


def pick_asset(assets):
    for suffix in wanted_suffixes():
        for a in assets:
            n = a["name"]
            if n.endswith(suffix) and not n.startswith("cudart"):
                return a
    return None


def url_exists(url):
    try:  # ask for just the first byte; HEAD requests get refused by GitHub's download servers
        with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"}), timeout=20) as r:
            r.read(1)
            return True
    except Exception:
        return False


def find_engine_download():
    """Returns (tag, file name, url). Uses the engine version this app was built with, so every
    computer running the same app version gets the exact same engine."""
    if ENGINE_TAG:
        for suffix in wanted_suffixes():
            name = f"llama-{ENGINE_TAG}-{suffix}"
            url = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_TAG}/{name}"
            if url_exists(url):
                return ENGINE_TAG, name, url
    # development builds: newest recent release that has a file for this computer
    req = urllib.request.Request(RELEASES_API, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        releases = json.load(r)
    for rel in releases:
        asset = pick_asset(rel.get("assets", []))
        if asset and not rel.get("draft"):
            return rel["tag_name"], asset["name"], asset["browser_download_url"]
    raise RuntimeError(f"No llama.cpp build found for {OS_NAME} {platform.machine()}. Check your internet connection and try again.")


def download(url, dest, on_progress):
    req = urllib.request.Request(url, headers=UA)
    tmp = Path(str(dest) + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            on_progress(done, total)
    tmp.replace(dest)


def safe_extract(archive, dest):
    dest = dest.resolve()
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not (dest / n).resolve().is_relative_to(dest):
                    raise RuntimeError(f"unsafe path in archive: {n}")
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            try:
                t.extractall(dest, filter="data")
            except TypeError:
                for m in t.getmembers():
                    if not (dest / m.name).resolve().is_relative_to(dest):
                        raise RuntimeError(f"unsafe path in archive: {m.name}")
                t.extractall(dest)


def install_engine():
    with LOCK:
        if ENGINE["state"] == "installing":
            return
        ENGINE.update(state="installing", progress=0.0, error="")
    try:
        tag, name, url = find_engine_download()
        archive = DL_DIR / name

        def prog(done, total):
            with LOCK:
                ENGINE["progress"] = done / total if total else 0.0

        download(url, archive, prog)
        was_sharing = RPC.running()
        RPC.stop()
        LLAMA.stop()
        target = ENGINE_DIR / tag
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        safe_extract(archive, target)
        archive.unlink(missing_ok=True)
        server = next(target.rglob(f"llama-server{EXE}"), None)
        if not server:
            raise RuntimeError("llama-server not found in the download")
        bin_dir = server.parent
        if not rpc_exe(bin_dir):
            raise RuntimeError("rpc-server not found in the download")
        if os.name != "nt":
            for p in bin_dir.iterdir():
                if p.is_file():
                    p.chmod(p.stat().st_mode | 0o755)
            if platform.system() == "Darwin":
                subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)], capture_output=True)
        for old in ENGINE_DIR.iterdir():
            if old.is_dir() and old != target:
                shutil.rmtree(old, ignore_errors=True)
        ENGINE_META.write_text(json.dumps({"version": tag, "bin": str(bin_dir)}))
        with LOCK:
            ENGINE["state"] = "missing"
        refresh_engine()
        if was_sharing:
            set_sharing(True)
    except Exception as e:
        with LOCK:
            ENGINE.update(state="error", error=str(e))


# --------------------------------------------------------------- processes --
def mode_threads():
    return max(1, round(CORES * MODES[CONFIG["mode"]]["cpu"]))


def apply_priority(proc):
    if not psutil or not proc.running():
        return
    pr = MODES[CONFIG["mode"]]["priority"]
    try:
        p = psutil.Process(proc.p.pid)
        if os.name == "nt":
            p.nice({"low": psutil.BELOW_NORMAL_PRIORITY_CLASS, "normal": psutil.NORMAL_PRIORITY_CLASS,
                    "high": psutil.ABOVE_NORMAL_PRIORITY_CLASS}[pr])
        else:
            # raising priority above normal needs admin rights on Mac/Linux, so "high" = normal there
            p.nice(10 if pr == "low" else max(p.nice(), 0))
    except Exception:
        pass


class Proc:
    def __init__(self, name):
        self.name = name
        self.p = None
        self.log = collections.deque(maxlen=400)
        self.meta = {}

    def start(self, args, meta=None):
        self.stop()
        self.meta = meta or {}
        self.log.append(f"$ {' '.join(args)}")
        self.p = subprocess.Popen(
            args, cwd=str(Path(args[0]).parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
        threading.Thread(target=self._pump, args=(self.p,), daemon=True).start()
        apply_priority(self)

    def _pump(self, p):
        for line in p.stdout:
            self.log.append(line.rstrip())
        self.log.append(f"[{self.name} stopped, exit code {p.wait()}]")

    def running(self):
        return self.p is not None and self.p.poll() is None

    def stop(self):
        if self.running():
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.meta = {}


RPC = Proc("rpc-server")
LLAMA = Proc("llama-server")


def set_sharing(on):
    refresh_engine()
    if on:
        if ENGINE["state"] != "ready":
            raise RuntimeError("Install the engine first (Settings → AI engine)")
        exe = str(rpc_exe(ENGINE["bin"]))
        RPC.start([exe, "-H", "0.0.0.0", "-p", str(RPC_PORT), "-c", "-t", str(mode_threads())],
                  {"mode": CONFIG["mode"]})
    else:
        RPC.stop()
    CONFIG["share_on_start"] = bool(on)
    save_config()


def set_mode(mode):
    if mode not in MODES:
        raise RuntimeError("Unknown mode")
    CONFIG["mode"] = mode
    save_config()
    if RPC.running():
        set_sharing(True)  # restart with new thread count (takes a second)
    apply_priority(LLAMA)
    return {"restart_needed": LLAMA.running() and LLAMA.meta.get("mode") != mode}


def llama_health():
    if not LLAMA.running():
        return "stopped"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=0.4) as r:
            return "ready" if r.status == 200 else "loading"
    except Exception:
        return "loading"


def start_cluster(model, peer_ids, ctx):
    refresh_engine()
    if ENGINE["state"] != "ready":
        raise RuntimeError("Install the engine first (Settings → AI engine)")
    path = MODEL_DIR / Path(model).name
    if not model or not path.exists():
        raise RuntimeError("Pick a model. Download one on the Models page.")
    rpcs, names = [], [CONFIG["name"]]
    with LOCK:
        for pid in peer_ids:
            p = PEERS.get(pid)
            if not p or not peer_online(p):
                raise RuntimeError("A selected computer went offline")
            if not p.get("sharing"):
                raise RuntimeError(f"{p['name']} is not sharing. Turn on sharing on that computer.")
            if p.get("engine_version") != ENGINE["version"]:
                raise RuntimeError(f"{p['name']} has engine {p.get('engine_version') or 'none'}, this computer has "
                                   f"{ENGINE['version']}. Install the same My Data Center version on both so they match.")
            rpcs.append(f"{p['ip']}:{p.get('rpc_port', RPC_PORT)}")
            names.append(p["name"])
    exe = str(Path(ENGINE["bin"]) / f"llama-server{EXE}")
    args = [exe, "-m", str(path), "--host", "127.0.0.1", "--port", str(LLAMA_PORT),
            "-ngl", "999", "-c", str(int(ctx)), "-t", str(mode_threads())]
    if rpcs:
        args += ["--rpc", ",".join(rpcs)]
    LLAMA.start(args, {"model": path.name, "nodes": names, "peer_ids": list(peer_ids), "ctx": int(ctx),
                       "mode": CONFIG["mode"], "started": time.time()})


# ----------------------------------------------------------------- updates --
# Updates download quietly in the background. When one is ready the app shows
# "Restart to update". Closing the app instead installs it on the next launch.
FROZEN = bool(getattr(sys, "frozen", False))
UPDATE = {"state": "idle", "latest": "", "progress": 0.0, "error": "", "checked": 0}
PENDING_PATH = HOME / "pending_update.json"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def update_file_name():
    if platform.system() == "Windows":
        return "MyDataCenter-Setup.exe"
    if platform.system() == "Darwin":
        return "MyDataCenter-Mac-AppleSilicon.dmg" if platform.machine() == "arm64" else "MyDataCenter-Mac-Intel.dmg"
    return None


def read_pending():
    """The update already downloaded and waiting to install, if any."""
    p = load_json(PENDING_PATH, None)
    if not p:
        return None
    f = Path(p.get("file", ""))
    if vtuple(p.get("version", "0")) > vtuple(VERSION) and f.exists() and f.stat().st_size == p.get("size"):
        return p
    try:  # stale or already installed: clean up
        PENDING_PATH.unlink(missing_ok=True)
        if f.exists() and f.parent == DL_DIR:
            f.unlink()
    except OSError:
        pass
    return None


def check_update():
    with LOCK:
        if UPDATE["state"] in ("downloading", "installing"):
            return
    pending = read_pending()
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                     headers={**UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
        latest = rel["tag_name"].lstrip("v")
        asset = next((a for a in rel.get("assets", []) if a["name"] == update_file_name()), None)
        newer = vtuple(latest) > vtuple(VERSION) and asset is not None
        with LOCK:
            UPDATE.update(latest=latest, checked=time.time(), error="")
        if not newer:
            with LOCK:
                UPDATE["state"] = "current"
            return
        if pending and pending["version"] == latest:
            with LOCK:
                UPDATE["state"] = "ready"
            return
        if not FROZEN:  # running from source: just tell them
            with LOCK:
                UPDATE["state"] = "available"
            return
        threading.Thread(target=download_update, args=(latest, asset), daemon=True).start()
    except Exception as e:
        with LOCK:
            if pending:
                UPDATE.update(state="ready", latest=pending["version"], checked=time.time())
            else:
                UPDATE.update(state="idle", error=f"Couldn't check for updates: {e}", checked=time.time())


def download_update(version, asset):
    with LOCK:
        if UPDATE["state"] in ("downloading", "installing"):
            return
        UPDATE.update(state="downloading", progress=0.0, error="", latest=version)
    try:
        dest = DL_DIR / f"update-{version}-{asset['name']}"

        def prog(done, total):
            with LOCK:
                UPDATE["progress"] = done / total if total else 0.0

        download(asset["browser_download_url"], dest, prog)
        if dest.stat().st_size != asset["size"]:
            dest.unlink(missing_ok=True)
            raise RuntimeError("Update download was incomplete. It will retry later.")
        for old in DL_DIR.glob("update-*"):
            if old != dest:
                old.unlink(missing_ok=True)
        PENDING_PATH.write_text(json.dumps({"version": version, "file": str(dest), "size": asset["size"]}))
        with LOCK:
            UPDATE.update(state="ready", progress=1.0)
    except Exception as e:
        with LOCK:
            UPDATE.update(state="idle", error=f"Update download failed: {e}")


def update_loop():
    time.sleep(5)
    while True:
        check_update()
        time.sleep(3 * 3600)


def install_pending(pending):
    """Hand off to the installer and exit. The app reopens on the new version."""
    with LOCK:
        UPDATE["state"] = "installing"
    f = Path(pending["file"])
    if platform.system() == "Windows":
        # wait for this app to fully close, then run the installer silently (it reopens the app)
        cmd = f'ping -n 3 127.0.0.1 >nul & "{f}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS'
        subprocess.Popen(["cmd", "/c", cmd], close_fds=True,
                         creationflags=NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
    elif platform.system() == "Darwin":
        install_mac_update(f)
        app = Path(sys.executable).resolve().parents[2]
        subprocess.Popen(["/bin/sh", "-c", f"sleep 2; open {shlex.quote(str(app))}"], start_new_session=True)
    else:
        raise RuntimeError("Automatic updates aren't supported on this system")
    PENDING_PATH.unlink(missing_ok=True)


def restart_to_update():
    pending = read_pending()
    if not pending:
        raise RuntimeError("No update is ready yet")
    if not FROZEN:
        raise RuntimeError("Updates only install in the packaged app")
    install_pending(pending)

    def go():
        time.sleep(0.6)
        LLAMA.stop()
        RPC.stop()
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()


def install_mac_update(dmg):
    app = Path(sys.executable).resolve().parents[2]  # .../My Data Center.app
    if app.suffix != ".app":
        raise RuntimeError("Couldn't find the app to update")
    mnt = tempfile.mkdtemp(prefix="mdc-update-")
    subprocess.run(["hdiutil", "attach", str(dmg), "-nobrowse", "-quiet", "-mountpoint", mnt], check=True)
    try:
        src = next(Path(mnt).glob("*.app"))
        new = app.with_name(app.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
        subprocess.run(["ditto", str(src), str(new)], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", mnt, "-quiet"])
    old = app.with_name(app.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    app.rename(old)
    new.rename(app)
    shutil.rmtree(old, ignore_errors=True)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(app)], capture_output=True)


def install_on_launch():
    """If an update was downloaded last time, install it now instead of opening the old version.
    Returns True when the app should exit and let the new version open."""
    if not FROZEN:
        return False
    pending = read_pending()
    if not pending:
        return False
    try:
        install_pending(pending)
        return True
    except Exception as e:
        print("Update failed, opening current version:", e)
        PENDING_PATH.unlink(missing_ok=True)
        return False


# ------------------------------------------------------------------ models --
DOWNLOADS = {}


def list_models():
    return [{"file": p.name, "gb": round(p.stat().st_size / 2**30, 2)} for p in sorted(MODEL_DIR.glob("*.gguf"))]


def download_model(url):
    name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    if not name.endswith(".gguf"):
        raise RuntimeError("Link must point to a .gguf file")
    with LOCK:
        if DOWNLOADS.get(name, {}).get("state") == "downloading":
            return
        DOWNLOADS[name] = {"state": "downloading", "progress": 0.0, "error": "", "done_gb": 0}

    def run():
        start = time.time()

        def prog(done, total):
            with LOCK:
                DOWNLOADS[name].update(progress=done / total if total else 0.0, done_gb=round(done / 2**30, 2),
                                       total_gb=round(total / 2**30, 2),
                                       mbps=round(done / 2**20 / max(time.time() - start, 0.1), 1))
        try:
            download(url, MODEL_DIR / name, prog)
            with LOCK:
                DOWNLOADS.pop(name, None)
        except Exception as e:
            with LOCK:
                DOWNLOADS[name] = {"state": "error", "progress": 0.0, "error": str(e)}

    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------- chats --
def load_chats():
    return load_json(CHATS_PATH, [])


def save_chat(chat):
    with LOCK:
        chats = [c for c in load_chats() if c.get("id") != chat.get("id")]
        chat["updated"] = time.time()
        chats.insert(0, chat)
        CHATS_PATH.write_text(json.dumps(chats[:200]), encoding="utf-8")


def delete_chat(cid):
    with LOCK:
        CHATS_PATH.write_text(json.dumps([c for c in load_chats() if c.get("id") != cid]), encoding="utf-8")


# --------------------------------------------------------------- discovery --
PEERS = {}
PEER_HIST = collections.defaultdict(lambda: collections.deque(maxlen=60))


def node_info():
    refresh_engine()
    with LOCK:
        st = dict(STATS)
    return {
        "app": APP_ID, "version": VERSION, "id": CONFIG["id"], "name": CONFIG["name"],
        "os": OS_NAME, "ram_gb": RAM_GB, "gpu_name": GPU, "cores": CORES, "ip": local_ip(),
        "dash_port": DASH_PORT, "rpc_port": RPC_PORT, "mode": CONFIG["mode"],
        "sharing": RPC.running(), "engine_version": ENGINE["version"],
        "hosting": LLAMA.meta.get("model") if LLAMA.running() else None,
        "cpu": st["cpu"], "ram_used": st["ram_used"], "gpu": st["gpu"],
        "vram_used": st["vram_used"], "vram_total": st["vram_total"],
    }


def peer_online(p):
    return time.time() - p.get("last_seen", 0) < 15


def remember_peer(info, ip):
    if info.get("app") != APP_ID or info.get("id") == CONFIG["id"]:
        return
    info["ip"] = ip
    info["last_seen"] = time.time()
    with LOCK:
        PEERS[info["id"]] = info
        PEER_HIST[info["id"]].append(info.get("cpu") or 0)


def announce_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        try:
            msg = json.dumps(node_info()).encode()
            ip = local_ip()
            targets = {"255.255.255.255"}
            if ip.count(".") == 3 and not ip.startswith("127."):
                targets.add(ip.rsplit(".", 1)[0] + ".255")
            for t in targets:
                try:
                    s.sendto(msg, (t, DISCOVERY_PORT))
                except OSError:
                    pass
        except Exception:
            pass
        time.sleep(2)


def listen_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind(("", DISCOVERY_PORT))
    while True:
        try:
            data, addr = s.recvfrom(65535)
            remember_peer(json.loads(data), addr[0])
        except Exception:
            continue


def manual_peer_loop():
    while True:
        for entry in list(CONFIG.get("manual_peers", [])):
            ip, _, port = entry.partition(":")
            try:
                with urllib.request.urlopen(f"http://{ip}:{port or 8800}/api/info", timeout=2) as r:
                    remember_peer(json.load(r), ip)
            except Exception:
                pass
        time.sleep(3)


# --------------------------------------------------------------------- web --
def full_state():
    me = node_info()
    with LOCK:
        peers = [dict(p, online=peer_online(p), hist=list(PEER_HIST[p["id"]])) for p in PEERS.values()]
        downloads = json.loads(json.dumps(DOWNLOADS))
        engine = dict(ENGINE)
        hist = list(HIST)
        tps = list(TPS_HIST)
    peers.sort(key=lambda p: (not p["online"], p["name"].lower()))
    return {
        "me": me, "peers": peers, "engine": engine, "models": list_models(),
        "downloads": downloads, "presets": PRESETS, "hist": hist, "tps": tps,
        "modes": MODES, "mode": CONFIG["mode"], "threads": mode_threads(), "has_psutil": bool(psutil),
        "cluster": {"status": llama_health(), **{k: v for k, v in LLAMA.meta.items()}},
        "manual_peers": CONFIG.get("manual_peers", []), "home": str(HOME), "app_version": VERSION, "update": dict(UPDATE), "frozen": FROZEN,
        "logs": {"rpc": list(RPC.log)[-80:], "llama": list(LLAMA.log)[-80:]},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def local_only(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_json({"error": "Controls only work from the app on this computer"}, 403)
            return False
        return True

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = resource("ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/info":
            self.send_json(node_info())
        elif self.path == "/api/state":
            self.send_json(full_state())
        elif self.path == "/api/chats":
            if self.local_only():
                self.send_json(load_chats())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.local_only():
            return
        try:
            data = self.body()
            res = {"ok": True}
            if self.path == "/api/engine/install":
                threading.Thread(target=install_engine, daemon=True).start()
            elif self.path == "/api/share":
                set_sharing(bool(data.get("on")))
            elif self.path == "/api/mode":
                res.update(set_mode(str(data.get("mode"))))
            elif self.path == "/api/rename":
                name = str(data.get("name", "")).strip()[:32]
                if name:
                    CONFIG["name"] = name
                    save_config()
            elif self.path == "/api/model/download":
                download_model(str(data.get("url", "")).strip())
            elif self.path == "/api/model/delete":
                (MODEL_DIR / Path(str(data.get("file", ""))).name).unlink(missing_ok=True)
            elif self.path == "/api/peer/add":
                entry = str(data.get("ip", "")).strip()
                if entry and entry not in CONFIG["manual_peers"]:
                    CONFIG["manual_peers"].append(entry)
                    save_config()
            elif self.path == "/api/peer/remove":
                with LOCK:
                    p = PEERS.pop(data.get("id"), None)
                if p:
                    CONFIG["manual_peers"] = [e for e in CONFIG["manual_peers"] if e.partition(":")[0] != p["ip"]]
                    save_config()
            elif self.path == "/api/cluster/start":
                start_cluster(data.get("model", ""), data.get("peers", []), data.get("ctx", 4096))
            elif self.path == "/api/cluster/restart":
                m = dict(LLAMA.meta)
                start_cluster(m.get("model", ""), m.get("peer_ids", []), m.get("ctx", 4096))
            elif self.path == "/api/cluster/stop":
                LLAMA.stop()
            elif self.path == "/api/chats/save":
                save_chat(data)
            elif self.path == "/api/chats/delete":
                delete_chat(data.get("id"))
            elif self.path == "/api/update/check":
                check_update()
            elif self.path == "/api/update/restart":
                restart_to_update()
            elif self.path == "/api/open-folder":
                open_folder(HOME)
            elif self.path == "/api/chat":
                return self.proxy_chat(data)
            else:
                return self.send_json({"error": "not found"}, 404)
            self.send_json(res)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def proxy_chat(self, data):
        data["stream"] = True
        req = urllib.request.Request(f"http://127.0.0.1:{LLAMA_PORT}/v1/chat/completions",
                                     data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        try:
            up = urllib.request.urlopen(req, timeout=900)
        except Exception as e:
            return self.send_json({"error": f"Model not ready: {e}"}, 502)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for line in up:
                if line.startswith(b"data:") and b'"timings"' in line:
                    try:
                        t = json.loads(line[5:])["timings"]
                        with LOCK:
                            TPS_HIST.append({"t": round(time.time()), "tps": round(t.get("predicted_per_second", 0), 2),
                                             "tokens": t.get("predicted_n", 0)})
                    except Exception:
                        pass
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            up.close()


def open_folder(path):
    if os.name == "nt":
        os.startfile(str(path))
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# -------------------------------------------------------------------- main --
def open_window(url):
    """Native app window. Falls back to the web browser if pywebview isn't installed."""
    try:
        import webview
    except ImportError:
        print("pywebview not installed — opening in your browser instead.")
        webbrowser.open(url)
        return False
    webview.create_window("My Data Center", url, width=1320, height=860, min_size=(960, 640),
                          background_color="#0b0f14", text_select=True)
    webview.start()
    return True


def main():
    url = f"http://localhost:{DASH_PORT}"
    try:
        server = ThreadingHTTPServer(("0.0.0.0", DASH_PORT), Handler)
    except OSError:
        # already running: just open another window onto it
        if not ARGS.headless:
            webbrowser.open(url) if ARGS.browser else open_window(url)
        return
    if install_on_launch():  # an update downloaded last time: install it and reopen
        server.server_close()
        return
    server.daemon_threads = True
    refresh_engine()
    for fn in (sampler_loop, announce_loop, listen_loop, manual_peer_loop, update_loop):
        threading.Thread(target=fn, daemon=True).start()
    if CONFIG.get("share_on_start") and ENGINE["state"] == "ready":
        try:
            set_sharing(True)
        except Exception as e:
            print("Could not start sharing:", e)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"My Data Center {VERSION} — {CONFIG['name']} ({local_ip()}) — {url}")
    try:
        if ARGS.headless or ARGS.browser or not open_window(url):
            if ARGS.browser:
                webbrowser.open(url)
            print("Running. Press Ctrl+C to quit.")
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        LLAMA.stop()
        RPC.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
