"""Own only the two Airlock processes recorded in this checkout's private data directory."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import http.client
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
from airlock.config import Settings

settings = Settings()
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True, mode=0o700)


def running(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def command(pid):
    return subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    ).stdout.strip()


def started(pid):
    return subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True
    ).stdout.strip()


def identity(name, pid):
    value = command(pid)
    # macOS may resolve Python's executable path after launch; bind to the owned script.
    if name == "app" and value.endswith(str(ROOT / ".venv/bin/airlock") + " serve"):
        return str(ROOT / ".venv/bin/airlock") + " serve"
    return value


def owned(name):
    path = DATA / f"{name}.pid.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if (
        running(record["pid"])
        and identity(name, record["pid"]) == record["command"]
        and started(record["pid"]) == record.get("started")
    ):
        return record["pid"]
    path.unlink()
    return None


def responds(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", path)
        return conn.getresponse().status == 200
    except OSError:
        return False
    finally:
        conn.close()


def stop(name):
    pid = owned(name)
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not running(pid):
                break
            time.sleep(0.1)
        if running(pid):
            raise SystemExit(f"{name} is still stopping; retry shortly.")
    (DATA / f"{name}.pid.json").unlink(missing_ok=True)


def start(name, args, port, health, env):
    if owned(name):
        if responds(port, health):
            return
        raise SystemExit(
            f"{name} has a recorded process but is not ready. Check data/{name}.log."
        )
    if responds(port, health):
        raise SystemExit(
            f"Port {port} already serves an unowned process. Airlock will not reuse it."
        )
    log = DATA / f"{name}.log"
    with log.open("ab") as out:
        log.chmod(0o600)
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )
    time.sleep(0.3)
    if process.poll() is not None:
        raise SystemExit(f"{name} failed to start. Check {log}.")
    pidfile = DATA / f"{name}.pid.json"
    pidfile.write_text(
        json.dumps(
            {
                "pid": process.pid,
                "command": identity(name, process.pid),
                "started": started(process.pid),
            }
        )
    )
    pidfile.chmod(0o600)
    for _ in range(60):
        if responds(port, health):
            return
        if process.poll() is not None:
            break
        time.sleep(0.25)
    raise SystemExit(f"{name} did not become ready. Check {log}.")


action = sys.argv[1] if len(sys.argv) == 2 else ""
if action not in {"start", "stop", "restart"}:
    raise SystemExit("Usage: scripts/manage.py start|stop|restart")
if action in {"stop", "restart"}:
    stop("app")
    stop("ollama")
if action in {"start", "restart"}:
    subprocess.run(["docker", "compose", "up", "-d", "--wait"], check=True)
    env = dict(os.environ)
    for key in list(env):
        if key.lower().endswith("_proxy") or key.startswith("OLLAMA_"):
            del env[key]
    u = urlsplit(settings.ollama_url)
    if u.hostname != "127.0.0.1" or u.port != 11435:
        raise SystemExit(
            "The managed launcher requires the dedicated 127.0.0.1:11435 Ollama endpoint."
        )
    env.update(
        OLLAMA_HOST="127.0.0.1:11435",
        OLLAMA_NO_CLOUD="1",
        OLLAMA_MODELS=str(Path.home() / ".ollama/models"),
    )
    start("ollama", ["ollama", "serve"], 11435, "/api/version", env)
    start(
        "app", [str(ROOT / ".venv/bin/airlock"), "serve"], settings.port, "/health", env
    )
    print(f"Airlock is ready at {settings.origin}")
else:
    print(
        "Airlock app and dedicated model server stopped. Database and stored memory are retained."
    )
