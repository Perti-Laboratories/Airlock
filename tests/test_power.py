from types import SimpleNamespace
import pytest
from airlock.power import PowerManager


class Session:
    enabled=False
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def get(self,*args):return SimpleNamespace(keep_syncing_plugged_in=self.enabled)


class Process:
    ended=False
    def poll(self):return 0 if self.ended else None
    def terminate(self):self.ended=True
    def wait(self,**kwargs):return 0


def test_ac_only_assertion_no_display_or_lock_changes(monkeypatch):
    db=Session();manager=PowerManager(lambda:db);manager.supported=True;calls=[]
    def start(args,**kwargs):calls.append(args);return Process()
    monkeypatch.setattr('airlock.power.subprocess.Popen',start)
    manager.refresh();assert not calls
    db.enabled=True;manager.refresh();manager.refresh()
    assert len(calls)==1 and calls[0][0:3]==['/usr/bin/caffeinate','-s','-w']
    assert not any(flag in calls[0] for flag in ('-d','-u','-i'))
    proc=manager.process
    monkeypatch.setattr('airlock.power.subprocess.run',lambda *a,**k:SimpleNamespace(stdout="Now drawing from 'Battery Power'"))
    status=manager.status();assert status['enabled'] and not status['active'] and status['assertion_running']
    monkeypatch.setattr('airlock.power.subprocess.run',lambda *a,**k:SimpleNamespace(stdout="Now drawing from 'AC Power'"))
    assert manager.status()['active']
    db.enabled=False;manager.refresh();assert proc.ended and manager.process is None
    db.enabled=True;manager.refresh();proc=manager.process;manager.stop();assert proc.ended


def test_power_setting_default_persistence_audit_and_csrf(workspace,monkeypatch):
    client,_,sessions,_=workspace
    monkeypatch.setattr('airlock.power.PowerManager.refresh',lambda self:None)
    monkeypatch.setattr('airlock.power.PowerManager.status',lambda self:{'supported':True})
    # Supported on the target Mac. Non-macOS CI verifies refusal instead.
    response=client.put('/api/power',json={'enabled':True})
    from airlock.models import LocalState,ToolCall
    from sqlalchemy import select
    with sessions() as db:
        if response.status_code==409:
            assert not db.get(LocalState,1).keep_syncing_plugged_in
        else:
            assert response.status_code==200 and response.json()['report_id']
            assert db.get(LocalState,1).keep_syncing_plugged_in
            assert db.scalar(select(ToolCall).where(ToolCall.tool_name=='power.preference'))
    assert client.put('/api/power',json={'enabled':False},headers={'X-Airlock-CSRF':'wrong'}).status_code==403
    assert client.put('/api/power',json={'enabled':False}).status_code==200
