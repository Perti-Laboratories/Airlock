"""Independent network and model workers; release commits serialize with publication."""
import logging
import threading
from sqlalchemy import select
from .models import CalendarSource
from .memory import DOMAIN
from .calendar_sync import run_sync
from .agents import recover_runs, tick_schedules, process_next


class LocalWorker:
    def __init__(self, sessions, llm, google, compute_lock, release_lock=None):
        self.sessions, self.llm, self.google = sessions, llm, google
        self.compute_lock = compute_lock
        self.release_lock = release_lock or threading.RLock()
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        recover_runs(self.sessions)
        for name, target in [('network', self.network_once), ('model', self.model_once)]:
            thread = threading.Thread(target=self.loop, args=(target,),
                                      name='airlock-' + name, daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)

    def network_once(self):
        from .exchange import exchange_once
        # Deliver revocations/renewals before potentially slow provider requests.
        with self.release_lock:
            exchange_once(self.sessions)
        with self.sessions() as db:
            sources = list(db.scalars(select(CalendarSource.id).where(
                CalendarSource.domain_id == DOMAIN, CalendarSource.enabled.is_(True))))
        for source in sources:
            if self.stop_event.is_set():
                return
            with self.release_lock:
                run_sync(self.sessions, self.google, source)

    def model_once(self):
        if not self.compute_lock.acquire(blocking=False):
            return
        try:
            tick_schedules(self.sessions)
            process_next(self.sessions, self.llm)
            from .company import extract_once
            with self.sessions() as db:
                extract_once(db, self.llm)
                db.commit()
        finally:
            self.compute_lock.release()

    def loop(self, action):
        while not self.stop_event.wait(3):
            try:
                action()
            except Exception:
                logging.getLogger(__name__).error('Local worker failed; retrying next heartbeat.')
