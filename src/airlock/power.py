"""An optional AC-only macOS assertion; never changes lock, display or system preferences."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from .models import LocalState


class PowerManager:
    def __init__(self, sessions):
        self.sessions = sessions
        self.supported = sys.platform == 'darwin' and Path('/usr/bin/caffeinate').is_file()
        self.process = None
        self.error = None
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.thread = None

    def refresh(self):
        with self.lock:
            with self.sessions() as db:
                row = db.get(LocalState, 1)
                enabled = bool(row and row.keep_syncing_plugged_in)
            if not enabled or not self.supported:
                self._release()
                self.error = None
            elif self.process is None or self.process.poll() is not None:
                try:
                    # -s is enforced by macOS ONLY on AC power. No -d/-u assertions,
                    # no lock changes, no battery idle-sleep prevention, no root access.
                    self.process = subprocess.Popen(['/usr/bin/caffeinate', '-s', '-w', str(os.getpid())],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.error = None
                except OSError:
                    self.error = 'Could not request plugged-in keep-awake.'

    def _release(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None

    def status(self):
        with self.lock:
            with self.sessions() as db:
                row = db.get(LocalState, 1)
                enabled = bool(row and row.keep_syncing_plugged_in)
            ac = None
            if self.supported:
                try:
                    output = subprocess.run(['/usr/bin/pmset','-g','batt'],capture_output=True,text=True,timeout=2,check=True).stdout
                    ac = "'AC Power'" in output
                except (OSError, subprocess.SubprocessError):
                    pass
            requested = bool(self.process and self.process.poll() is None)
            return {'enabled':enabled, 'supported':self.supported, 'plugged_in':ac,
                    'assertion_running':requested, 'active':requested and ac is True, 'error':self.error}

    def start(self):
        self.refresh()
        self.stopping.clear()
        def watch():
            while not self.stopping.wait(30):
                try:
                    self.refresh()
                except Exception:
                    # A lost DB must not leave an unmaintained sleep assertion running.
                    with self.lock:
                        self._release()
                        self.error = 'Keep-awake paused until the local database is available.'
        self.thread = threading.Thread(target=watch,daemon=True,name='airlock-power')
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.lock:
            self._release()
