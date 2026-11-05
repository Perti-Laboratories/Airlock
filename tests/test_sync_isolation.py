import threading
from airlock.workers import LocalWorker
from airlock.models import ReleasePolicy
from airlock.memory import DOMAIN


def test_network_work_does_not_wait_for_model_lock(workspace, monkeypatch):
    c, llm, sessions, settings = workspace
    calls=[]
    monkeypatch.setattr('airlock.exchange.exchange_once', lambda sessions: calls.append('exchange'))
    compute=threading.Lock();compute.acquire()
    worker=LocalWorker(sessions,llm,None,compute)
    worker.network_once()
    assert calls==['exchange']
    worker.model_once()  # A busy model simply skips the model heartbeat.
    compute.release()


def test_policy_commit_waits_for_publisher_guard(workspace):
    c, llm, sessions, settings = workspace
    c.put('/api/release-policy',json={'expected_revision':0,'paused':True,'rules':{}})
    with sessions() as db:
        lock=db.info['release_lock']
    attempted, completed=threading.Event(), threading.Event()
    def change():
        with sessions() as db:
            row=db.get(ReleasePolicy,DOMAIN);row.paused=False
            attempted.set();db.commit();completed.set()
    with lock:
        thread=threading.Thread(target=change);thread.start()
        assert attempted.wait(2)
        assert not completed.wait(.1)
    thread.join(2)
    assert completed.is_set()
    # Commit/rollback releases the guard; a following publisher can acquire it.
    assert lock.acquire(blocking=False);lock.release()
