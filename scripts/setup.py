#!/usr/bin/env python3
"""PreReads run script (Python stdlib only).

Usage:
    python3 scripts/setup.py install    venv + pip install (backend) + npm install/build (frontend)
    python3 scripts/setup.py start      Ensure Ollama, build UI if stale, serve app in background
    python3 scripts/setup.py stop       Stop the background app
    python3 scripts/setup.py restart    stop + start
    python3 scripts/setup.py status     App pid/port/health + Ollama version, loaded models
    python3 scripts/setup.py logs       Follow .run/app.log (Ctrl+C to quit)
    python3 scripts/setup.py dev        Backend --reload on :8000 + Vite on :5173 (Ctrl+C stops both)
    python3 scripts/setup.py doctor     Check all prerequisites
    python3 scripts/setup.py help       Show this help

Environment variables:
    PREREADS_HOST=127.0.0.1   bind address (0.0.0.0 to expose on the LAN / phone on same Wi-Fi)
    PREREADS_PORT=8000        app port (the Vite dev proxy expects 8000)
    OLLAMA_BASE_URL, LOCAL_LLM_MODEL, LOCAL_CHAT_MODEL, LOCAL_LLM_MODEL_HEAVY,
    LOCAL_VISION_MODEL, LOCAL_EMBED_MODEL, AI_PROVIDER are read from the environment or
    the repo-root .env, the same way backend/app/core/config.py reads them.

Files:
    .run/app.pid        pid of the background app (process-group leader)
    .run/app.log        app output (previous run kept as .run/app.log.1)
    .run/ollama.log     output of `ollama serve` when this script started it

"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# -- Paths --
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
RUN_DIR = ROOT / ".run"
PID_FILE = RUN_DIR / "app.pid"
URL_FILE = RUN_DIR / "app.url"
LOG_FILE = RUN_DIR / "app.log"
OLLAMA_LOG = RUN_DIR / "ollama.log"
VENV_PY = BACKEND / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / \
    ("python.exe" if platform.system() == "Windows" else "python")

IS_WIN = platform.system() == "Windows"
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not IS_WIN


def _read_dotenv() -> dict[str, str]:
    """Minimal KEY=VALUE parser for the repo-root .env (real env vars win)."""
    out: dict[str, str] = {}
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            out[k] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


_DOTENV = _read_dotenv()


def cfg(name: str, default: str = "") -> str:
    return (os.environ.get(name) or _DOTENV.get(name) or default).strip()


# -- Defaults --
HOST = os.environ.get("PREREADS_HOST", "127.0.0.1")
PORT = os.environ.get("PREREADS_PORT", "8000")
VITE_PORT = "5173"

AI_PROVIDER = cfg("AI_PROVIDER", "ollama").lower()
OLLAMA_URL = cfg("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_PORT = urlparse(OLLAMA_URL).port or 11434
OLLAMA_LOCAL = (urlparse(OLLAMA_URL).hostname or "localhost") in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _list(name: str, default: str) -> list[str]:
    return [m.strip() for m in cfg(name, default).split(",") if m.strip()]


# (label, configured model, fallbacks tried in order); mirrors ai/llm.py resolve_model.
_LLM = cfg("LOCAL_LLM_MODEL", "gpt-oss:20b")
_LLM_FALLBACKS = _list("LOCAL_LLM_FALLBACKS", "gemma3:12b,qwen3.6:35b-a3b")
MODEL_ROLES = (
    ("interactive LLM", _LLM, _LLM_FALLBACKS),
    ("chat LLM", cfg("LOCAL_CHAT_MODEL", "gemma3:12b"), [_LLM, *_LLM_FALLBACKS]),
    ("heavy LLM (precompute)", cfg("LOCAL_LLM_MODEL_HEAVY", "gpt-oss:120b"),
     _list("LOCAL_HEAVY_FALLBACKS", "gemma3:12b,qwen3.6:35b-a3b")),
    ("vision (cover scan)", cfg("LOCAL_VISION_MODEL", "qwen2.5vl:7b"),
     _list("LOCAL_VISION_FALLBACKS", "gemma3:12b")),
    ("embeddings", cfg("LOCAL_EMBED_MODEL", "nomic-embed-text"), []),
)

OPTIONAL_PY_PACKAGES = (
    ("faster_whisper", "faster-whisper", "speech-to-text (voice input)"),
    ("kokoro_onnx", "kokoro-onnx", "text-to-speech (Listen button)"),
)


# ============================================================
# Helpers
# ============================================================

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def ok(msg: str) -> None:
    print(f"  {_c('32', '[ OK ]')} {msg}")


def fail(msg: str) -> None:
    print(f"  {_c('31', '[FAIL]')} {msg}")


def warn(msg: str) -> None:
    print(f"  {_c('33', '[WARN]')} {msg}")


def info(msg: str) -> None:
    print(f"  {_c('36', '[INFO]')} {msg}")


def step(num: str, msg: str) -> None:
    print(f"\n  {_c('1', f'[{num}]')} {msg}")


def header(title: str) -> None:
    print(f"\n  {_c('1', f'=== {title} ===')}")


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = False,
        timeout: int = 1800, env: dict[str, str] | None = None) -> int:
    """Run a command (argv[0] resolved via PATH), return its exit code."""
    resolved = which(cmd[0])
    argv = [resolved, *cmd[1:]] if resolved else list(cmd)
    try:
        return subprocess.run(
            argv, cwd=str(cwd) if cwd else None, timeout=timeout,
            capture_output=quiet, text=True, env=env, stdin=subprocess.DEVNULL,
        ).returncode
    except subprocess.TimeoutExpired:
        fail(f"Command timed out: {' '.join(cmd[:3])}")
        return 1
    except FileNotFoundError:
        fail(f"Command not found: {cmd[0]}")
        return 1


def capture(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and return trimmed stdout ('' on any failure)."""
    resolved = which(cmd[0]) or (cmd[0] if os.path.isabs(cmd[0]) else None)
    if not resolved:
        return ""
    try:
        r = subprocess.run([resolved, *cmd[1:]], capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def http_json(url: str, timeout: float = 3.0):
    """GET a JSON endpoint; None on any error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def port_open(port: int | str, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=1):
            return True
    except OSError:
        return False


def probe_host(host: str) -> str:
    """Address to reach a server bound on ``host`` from this machine."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def app_url(host: str = HOST, port: str = PORT) -> str:
    return f"http://{probe_host(host)}:{port}"


def lan_ip() -> str | None:
    """Best-effort LAN address (no packets are sent by a UDP connect)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


# -- Processes --

def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def pid_command(pid: int) -> str:
    return capture(["ps", "-o", "command=", "-p", str(pid)])


def pid_cwd(pid: int) -> str:
    out = capture(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def listen_pids(port: int | str) -> list[int]:
    out = capture(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
    return sorted({int(x) for x in out.split() if x.isdigit()})


def read_pid() -> int | None:
    """pid from .run/app.pid if that process is still our app, else None."""
    try:
        pid = int(PID_FILE.read_text().strip().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None
    # Guard against pid reuse (e.g. after a reboot): must still be our uvicorn.
    return pid if pid_alive(pid) and "app.main:app" in pid_command(pid) else None


def is_ours(pid: int) -> bool:
    """True when ``pid`` belongs to this repo's app (pid file group or cwd under ROOT)."""
    app = read_pid()
    if app is not None:
        try:
            if pid == app or os.getpgid(pid) == app:
                return True
        except (ProcessLookupError, PermissionError, AttributeError):
            pass
    cwd = pid_cwd(pid)
    return bool(cwd) and (cwd == str(ROOT) or cwd.startswith(str(ROOT) + os.sep))


def describe_pid(pid: int) -> str:
    cmd = (pid_command(pid) or "?").replace(str(ROOT) + os.sep, "")
    return f"pid {pid}: {cmd[:100]}"


def kill_group(pid: int, wait: float = 8.0, group: bool = True) -> None:
    """SIGTERM ``pid`` (its whole process group when ``group``; we started it
    with start_new_session), then SIGKILL after ``wait`` seconds."""
    def _send(sig: int) -> None:
        try:
            if group and hasattr(os, "killpg"):
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def _gone() -> bool:
        try:  # reap it if it is our own child (else it lingers as a zombie)
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
        return not pid_alive(pid)

    _send(signal.SIGTERM)
    deadline = time.time() + wait
    while time.time() < deadline:
        if _gone():
            return
        time.sleep(0.25)
    _send(getattr(signal, "SIGKILL", signal.SIGTERM))
    time.sleep(0.5)
    _gone()


# ============================================================
# Ollama
# ============================================================

def ollama_version() -> str | None:
    data = http_json(f"{OLLAMA_URL}/api/version", timeout=5)
    return data.get("version") if isinstance(data, dict) else None


def ollama_models() -> list[str] | None:
    data = http_json(f"{OLLAMA_URL}/api/tags", timeout=5)
    if not isinstance(data, dict):
        return None
    return [m.get("name", "") for m in data.get("models", [])]


def has_model(models: list[str], name: str) -> bool:
    return name in models or f"{name}:latest" in models


def resolve_model(models: list[str], configured: str, fallbacks: list[str]) -> tuple[str | None, bool]:
    """(model that would be used, is_fallback) — same order as the backend."""
    for i, name in enumerate([configured, *fallbacks]):
        if has_model(models, name):
            return name, i > 0
    return None, False


def wait_ollama(seconds: int = 30) -> str | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        v = ollama_version()
        if v:
            return v
        time.sleep(1)
    return None


def report_models(models: list[str]) -> int:
    """Print the model each role would use; returns the number of warnings."""
    warnings = 0
    for label, configured, fallbacks in MODEL_ROLES:
        used, is_fb = resolve_model(models, configured, fallbacks)
        if used and not is_fb:
            ok(f"{label}: {used}")
            continue
        warnings += 1
        if used:
            warn(f"{label}: {configured} not pulled, falling back to {used}  (ollama pull {configured})")
        else:
            warn(f"{label}: {configured} not pulled and no fallback installed  (ollama pull {configured})")
    return warnings


def ensure_ollama() -> bool:
    """Make sure Ollama is reachable; start `ollama serve` in the background if not."""
    if AI_PROVIDER != "ollama":
        info(f"AI_PROVIDER={AI_PROVIDER} — Ollama not needed")
        return True
    version = ollama_version()
    if not version and port_open(OLLAMA_PORT, urlparse(OLLAMA_URL).hostname or "localhost"):
        info("Ollama port is open but not answering yet — waiting...")
        version = wait_ollama(30)
    if not version:
        if not OLLAMA_LOCAL:
            fail(f"Ollama not reachable at {OLLAMA_URL}")
            return False
        if not which("ollama"):
            fail("ollama not found. Install: brew install ollama (or https://ollama.com)")
            return False
        info("Ollama not running — starting `ollama serve` in the background")
        RUN_DIR.mkdir(exist_ok=True)
        with open(OLLAMA_LOG, "ab") as log:
            subprocess.Popen([which("ollama") or "ollama", "serve"], stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        version = wait_ollama(30)
        if not version:
            fail("Ollama did not come up. See .run/ollama.log")
            return False
        ok(f"Ollama started (v{version}); it keeps running after `stop` — quit it yourself if you want")
    else:
        ok(f"Ollama running (v{version})")
    report_models(ollama_models() or [])
    return True


# ============================================================
# Backend / frontend
# ============================================================

def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for p in paths:
        try:
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        newest = max(newest, f.stat().st_mtime)
            elif p.is_file():
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return newest


def dist_is_stale() -> bool:
    """True when frontend/dist is missing or older than the frontend sources."""
    index = DIST / "index.html"
    if not index.exists():
        return True
    sources = [FRONTEND / "src", FRONTEND / "public", FRONTEND / "index.html",
               FRONTEND / "package.json", *FRONTEND.glob("vite.config.*"),
               *FRONTEND.glob("tsconfig*.json")]
    try:
        return _newest_mtime(sources) > index.stat().st_mtime
    except OSError:
        return False


def node_deps_stale() -> bool:
    marker = FRONTEND / "node_modules" / ".package-lock.json"
    if not marker.exists():
        return True
    m = marker.stat().st_mtime
    return any(f.is_file() and f.stat().st_mtime > m
               for f in (FRONTEND / "package.json", FRONTEND / "package-lock.json"))


def npm_install(force: bool = False) -> bool:
    if not (FRONTEND / "package.json").exists():
        warn("frontend/package.json not found — skipping npm install")
        return False
    if not force and not node_deps_stale():
        info("node_modules up to date — skipping npm install")
        return True
    info("npm install ...")
    if run(["npm", "install", "--no-audit", "--no-fund"], cwd=FRONTEND) != 0:
        fail("npm install failed (see output above)")
        return False
    ok("Frontend dependencies installed")
    return True


def build_frontend() -> bool:
    if not (FRONTEND / "package.json").exists():
        warn("frontend/package.json not found — skipping frontend build")
        return False
    if not npm_install():
        return False
    info("npm run build ...")
    if run(["npm", "run", "build"], cwd=FRONTEND) != 0 or not (DIST / "index.html").exists():
        fail("Frontend build failed (see output above)")
        return False
    ok("Frontend built -> frontend/dist")
    return True


def venv_install() -> bool:
    req = BACKEND / "requirements.txt"
    if not req.exists():
        fail("backend/requirements.txt not found")
        return False
    if not VENV_PY.exists():
        info("python3 -m venv backend/.venv ...")
        if run([sys.executable, "-m", "venv", str(BACKEND / ".venv")]) != 0:
            fail("venv creation failed")
            return False
    info("pip install -r backend/requirements.txt ...")
    if run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(req)], cwd=BACKEND) != 0:
        fail("pip install failed (see output above)")
        return False
    ok("Backend dependencies installed (backend/.venv)")
    return True


def ensure_env_file() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        ok(".env present")
    elif example.exists():
        shutil.copy(example, env)
        ok("Copied .env.example -> .env")
    else:
        info("No .env or .env.example — using built-in defaults")


INSTALL_HINTS = {
    "python3": "install Python 3.11+",
    "node": "install Node 18+ (https://nodejs.org or nvm)",
    "npm": "comes with Node.js",
    "ollama": "brew install ollama (or https://ollama.com)",
}


def check_tools(*names: str) -> bool:
    good = True
    for name in names:
        if which(name):
            ok(f"{name} found")
        else:
            fail(f"{name} not found — {INSTALL_HINTS.get(name, 'install it')}")
            good = False
    return good


def check_venv() -> bool:
    if VENV_PY.exists():
        ok("backend/.venv present")
        return True
    fail("backend/.venv missing — run: python3 scripts/setup.py install  (or: make setup)")
    return False


def tail_log(lines: int = 30) -> None:
    try:
        content = LOG_FILE.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return
    print(f"\n  --- last {len(content)} lines of {LOG_FILE.relative_to(ROOT)} ---")
    for line in content:
        print(f"  | {line}")
    print()


# ============================================================
# App lifecycle
# ============================================================

def do_stop(quiet: bool = False) -> bool:
    """Stop the background app. Returns True if something was stopped."""
    stopped = False
    pid = read_pid()
    if pid is not None:
        kill_group(pid)
        stopped = True
        if not quiet:
            ok(f"Stopped app (pid {pid})")
    # Stray PreReads uvicorn still on our port (lost pid file, crashed start).
    # Only that pid is signalled — never a process group we did not create.
    for lp in listen_pids(PORT):
        if "app.main:app" in pid_command(lp) and is_ours(lp):
            kill_group(lp, group=False)
            stopped = True
            if not quiet:
                ok(f"Stopped stray app listener on :{PORT} (pid {lp})")
    for f in (PID_FILE, URL_FILE):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
    return stopped


def do_start() -> int:
    header("PreReads Start")

    step("1/4", "Checking backend...")
    if not (BACKEND / "app" / "main.py").exists():
        fail("backend/app/main.py not found")
        return 1
    ok("backend/app/main.py present")
    if not check_venv():
        return 1
    ensure_env_file()

    step("2/4", "Checking Ollama...")
    if not ensure_ollama():
        warn("Continuing without a healthy Ollama — AI features fall back or fail until it runs")

    step("3/4", "Checking frontend build...")
    if not (FRONTEND / "package.json").exists():
        warn("frontend/package.json not found — serving API only")
    elif dist_is_stale():
        had_dist = (DIST / "index.html").exists()
        info("Frontend source changed since last build — rebuilding..." if had_dist
             else "frontend/dist missing — building...")
        if not check_tools("node", "npm") or not build_frontend():
            warn("Rebuild failed — serving the previous build" if had_dist
                 else "No frontend build — serving API only")
    else:
        ok("frontend/dist up to date")

    step("4/4", f"Starting app on {HOST}:{PORT}...")
    url = app_url()
    pid = read_pid()
    if pid is not None:
        if http_json(f"{url}/api/health", timeout=3) is not None:
            ok(f"Already running (pid {pid}) — use restart to reload")
            _print_banner(url)
            return 0
        warn(f"Stale app process (pid {pid}) not answering — stopping it")
        do_stop(quiet=True)
    busy = listen_pids(PORT) or ([-1] if port_open(PORT, probe_host(HOST)) else [])
    if busy:
        who = describe_pid(busy[0]) if busy[0] > 0 else "unknown process"
        fail(f"Port {PORT} is already in use ({who})")
        info("Stop it (python3 scripts/setup.py stop, or Ctrl+C the dev server) or use PREREADS_PORT=<port>")
        return 1

    RUN_DIR.mkdir(exist_ok=True)
    if LOG_FILE.exists():
        os.replace(LOG_FILE, LOG_FILE.with_suffix(".log.1"))
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with open(LOG_FILE, "ab") as log:
        log.write(f"=== PreReads start {time.strftime('%Y-%m-%d %H:%M:%S')} on {HOST}:{PORT} ===\n".encode())
        log.flush()
        proc = subprocess.Popen(
            [str(VENV_PY), "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", PORT],
            cwd=str(BACKEND), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env, start_new_session=True,
        )
    PID_FILE.write_text(f"{proc.pid}\n")
    URL_FILE.write_text(f"{url}\n")
    info(f"pid {proc.pid}, logs: .run/app.log")

    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            fail(f"App exited during startup (code {proc.returncode})")
            tail_log()
            do_stop(quiet=True)
            return 1
        if http_json(f"{url}/api/health", timeout=2) is not None:
            ok("Health check passed (/api/health)")
            _print_banner(url)
            return 0
        time.sleep(0.5)
    fail("App did not answer /api/health within 90s")
    tail_log()
    do_stop(quiet=True)
    return 1


def _print_banner(url: str) -> None:
    print()
    print("  ==========================================")
    print(f"   PreReads:     {_c('1;32', url)}")
    if HOST in ("0.0.0.0", "::", ""):
        ip = lan_ip()
        print(f"   On your LAN:  {_c('1;32', f'http://{ip}:{PORT}') if ip else '(LAN address not found)'}")
    else:
        print("   On your LAN:  not exposed (bind with PREREADS_HOST=0.0.0.0)")
    print("   Logs:         python3 scripts/setup.py logs")
    print("   Stop:         python3 scripts/setup.py stop")
    print("  ==========================================")
    print()


# ============================================================
# Commands
# ============================================================

def cmd_install() -> int:
    header("PreReads Install")
    step("1/3", "Checking tools...")
    if not check_tools("python3", "node", "npm"):
        return 1
    step("2/3", "Backend (venv + pip)...")
    ensure_env_file()
    if not venv_install():
        return 1
    step("3/3", "Frontend (npm install + build)...")
    if not (FRONTEND / "package.json").exists():
        warn("frontend/package.json not found — skipping")
    elif not npm_install(force=True) or not build_frontend():
        return 1
    print("\n  Done. Run: python3 scripts/setup.py start\n")
    return 0


def cmd_start() -> int:
    return do_start()


def cmd_stop() -> int:
    header("PreReads Stop")
    if not do_stop():
        info("App was not running")
    print()
    return 0


def cmd_restart() -> int:
    header("PreReads Restart")
    if not do_stop():
        info("App was not running")
    return do_start()


def cmd_status() -> int:
    header("PreReads Status")

    step("app", "PreReads")
    saved_url = URL_FILE.read_text().strip() if URL_FILE.exists() else ""
    url = saved_url or app_url()
    port = url.rsplit(":", 1)[-1]
    pid = read_pid()
    listeners = listen_pids(port)
    if pid is not None:
        ok(f"Background app running (pid {pid})")
    elif PID_FILE.exists():
        warn("Stale .run/app.pid (process gone) — run start")
    else:
        info("No background app (not started with `start`)")
    if listeners:
        for lp in listeners:
            ours = is_ours(lp)
            (ok if ours else warn)(f"Port {port} listener [{'PreReads' if ours else 'OTHER'}] {describe_pid(lp)}")
    else:
        info(f"Nothing listening on port {port}")
    health = http_json(f"{url}/api/health", timeout=3)
    if health is not None:
        ok(f"Health {url}/api/health -> {json.dumps(health)[:160]}")
        ok(f"URL: {url}")
    else:
        info(f"No answer from {url}/api/health")

    step("ollama", OLLAMA_URL)
    version = ollama_version()
    if not version:
        (fail if AI_PROVIDER == "ollama" else info)(f"Ollama not reachable at {OLLAMA_URL}")
    else:
        ok(f"Ollama v{version}")
        ps = http_json(f"{OLLAMA_URL}/api/ps", timeout=5) or {}
        loaded = ps.get("models", []) if isinstance(ps, dict) else []
        if loaded:
            for m in loaded:
                gb = (m.get("size_vram") or m.get("size") or 0) / 1e9
                ok(f"Loaded: {m.get('name')}  ({gb:.1f} GB, until {str(m.get('expires_at', ''))[11:19]})")
        else:
            info("No models loaded in memory (they load on first request)")
        report_models(ollama_models() or [])
    print()
    return 0


def cmd_logs() -> int:
    if not LOG_FILE.exists():
        fail("No .run/app.log yet — run: python3 scripts/setup.py start")
        return 1
    if not which("tail"):
        print(LOG_FILE.read_text(errors="replace"))
        return 0
    try:
        return subprocess.run(["tail", "-n", "100", "-f", str(LOG_FILE)]).returncode
    except KeyboardInterrupt:
        print()
        return 0


def cmd_dev() -> int:
    header("PreReads Dev")
    step("1/3", "Checking tools...")
    if not check_tools("node", "npm") or not check_venv():
        return 1
    if not (BACKEND / "app" / "main.py").exists() or not (FRONTEND / "package.json").exists():
        fail("backend/app/main.py or frontend/package.json missing")
        return 1
    if PORT != "8000":
        warn(f"PREREADS_PORT={PORT} — the Vite /api proxy expects 8000")

    step("2/3", "Checking Ollama + ports...")
    if not ensure_ollama():
        warn("Continuing without a healthy Ollama")
    if read_pid() is not None:
        info("Stopping the background app (dev replaces it)...")
        do_stop(quiet=True)
    for port in (PORT, VITE_PORT):
        busy = listen_pids(port)
        if busy:
            fail(f"Port {port} is in use ({describe_pid(busy[0])})")
            return 1
    ok(f"Ports {PORT} and {VITE_PORT} free")
    if not npm_install():
        return 1

    step("3/3", "Starting backend (--reload) + Vite...")
    base_env = {**os.environ}
    if USE_COLOR:
        base_env["FORCE_COLOR"] = "1"
    specs = [
        ("api", "36", BACKEND,
         [str(VENV_PY), "-m", "uvicorn", "app.main:app", "--reload",
          "--host", HOST, "--port", PORT] + (["--use-colors"] if USE_COLOR else []),
         {**base_env, "PYTHONUNBUFFERED": "1"}),
        ("web", "35", FRONTEND,
         [which("npm") or "npm", "run", "dev", "--", "--port", VITE_PORT, "--strictPort"],
         base_env),
    ]
    print_lock = threading.Lock()
    procs: list[tuple[str, subprocess.Popen]] = []

    def pump(name: str, color: str, proc: subprocess.Popen) -> None:
        prefix = _c(color, f"{name} |")
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            with print_lock:
                print(f"{prefix} {text}", flush=True)

    def stop_all() -> None:
        for _, p in procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, AttributeError):
                    p.terminate()
        deadline = time.time() + 6
        for _, p in procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, AttributeError):
                    p.kill()

    def on_signal(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, on_signal)

    rc = 0
    try:
        for name, color, cwd, argv, env in specs:
            p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            procs.append((name, p))
            threading.Thread(target=pump, args=(name, color, p), daemon=True).start()
        print()
        print("  ==========================================")
        print(f"   UI (hot reload):  {_c('1;32', f'http://localhost:{VITE_PORT}')}")
        print(f"   API:              {app_url()}/api/health")
        print("   Ctrl+C stops both")
        print("  ==========================================")
        print()
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    with print_lock:
                        fail(f"{name} exited (code {p.returncode}) — stopping the other")
                    rc = p.returncode or 1
                    raise KeyboardInterrupt
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        stop_all()
        print()
        ok("Dev servers stopped")
    return rc


def _py_package_present(module: str) -> bool:
    """Is ``module`` importable from the backend venv (falls back to this interpreter)?"""
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    return subprocess.run([py, "-c", f"import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('{module}') else 1)"],
                          capture_output=True, stdin=subprocess.DEVNULL).returncode == 0


def cmd_doctor() -> int:
    header("PreReads Doctor")
    issues = 0
    warnings = 0

    step("tools", "Toolchain")
    if sys.version_info >= (3, 11):
        ok(f"Python {platform.python_version()}")
    else:
        fail(f"Python {platform.python_version()} — backend needs 3.11+")
        issues += 1
    for name in ("node", "npm"):
        if which(name):
            ver = (capture([name, "--version"]).splitlines() or [""])[0]
            ok(f"{name} {ver}".rstrip())
        else:
            fail(f"{name} not found — {INSTALL_HINTS[name]}")
            issues += 1
    node_v = version_tuple(capture(["node", "--version"])) if which("node") else ()
    if node_v and node_v < (18,):
        fail("Node < 18 — frontend needs Node 18+")
        issues += 1

    step("ollama", f"Ollama models — AI_PROVIDER={AI_PROVIDER}")
    if AI_PROVIDER != "ollama":
        info("AI_PROVIDER is not ollama — Ollama models are not used")
    elif not which("ollama") and not ollama_version():
        warn(f"ollama not found — {INSTALL_HINTS['ollama']}  (the app still runs; AI falls back to heuristics)")
        warnings += 1
    else:
        running = ollama_version()
        if running:
            ok(f"Ollama server running at {OLLAMA_URL} (v{running})")
        else:
            warn(f"Ollama server not running at {OLLAMA_URL} — `start` will run `ollama serve`")
            warnings += 1
        models = ollama_models() if running else None
        if models is None:
            warn("Cannot list models (Ollama not running)")
            warnings += 1
        else:
            missing = report_models(models)
            warnings += missing
            if not missing:
                ok("All configured models installed")

    step("speech", "Optional speech (Python packages in backend/.venv)")
    for module, pkg, what in OPTIONAL_PY_PACKAGES:
        if _py_package_present(module):
            ok(f"{pkg}: {what}")
        else:
            info(f"{pkg} not installed (optional) — {what}; pip install {pkg}")

    step("project", "Repo layout")
    for rel, label, hint, required in (
        ("backend/requirements.txt", "backend deps file", "missing", True),
        ("backend/app/main.py", "backend entrypoint", "missing", True),
        ("backend/.venv", "backend venv", "run: python3 scripts/setup.py install", False),
        ("frontend/package.json", "frontend project", "missing", True),
        ("frontend/node_modules", "frontend deps", "run: python3 scripts/setup.py install", False),
        (".env", ".env", "optional; copy .env.example if you have one (defaults are used otherwise)", False),
    ):
        if (ROOT / rel).exists():
            ok(f"{label}: {rel}")
        elif required:
            fail(f"{label}: {rel} {hint}")
            issues += 1
        else:
            warn(f"{label}: {rel} missing — {hint}")
            warnings += 1
    if not (DIST / "index.html").exists():
        warn("frontend/dist missing — `start` will build it")
        warnings += 1
    elif dist_is_stale():
        warn("frontend/dist is older than frontend sources — `start` will rebuild it")
        warnings += 1
    else:
        ok("frontend/dist up to date")

    step("ports", "Ports")
    for port, label in ((PORT, "app"), (VITE_PORT, "vite dev")):
        pids = listen_pids(port)
        if not pids:
            if port_open(port, probe_host(HOST)):
                warn(f"Port {port} ({label}) is in use (owner unknown)")
                warnings += 1
            else:
                ok(f"Port {port} ({label}) free")
        elif all(is_ours(p) for p in pids):
            ok(f"Port {port} ({label}) in use by PreReads ({describe_pid(pids[0])})")
        else:
            warn(f"Port {port} ({label}) in use by another process ({describe_pid(pids[0])})")
            warnings += 1

    print()
    if issues:
        fail(f"{issues} issue(s), {warnings} warning(s) — fix the [FAIL] lines above\n")
        return 1
    ok(f"All required checks passed ({warnings} warning(s))\n")
    return 0


def cmd_help() -> int:
    print(__doc__)
    return 0


# ============================================================
# Main
# ============================================================

COMMANDS = {
    "install": cmd_install,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "dev": cmd_dev,
    "doctor": cmd_doctor,
    "help": cmd_help,
    "-h": cmd_help,
    "--help": cmd_help,
}


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "help"
    handler = COMMANDS.get(cmd)
    if not handler:
        fail(f"Unknown command: {cmd}")
        print("  Run: python3 scripts/setup.py help")
        return 2
    try:
        return handler() or 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
