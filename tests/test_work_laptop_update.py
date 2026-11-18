"""Release updates must preserve local data and fail before destructive operations."""
import json
from pathlib import Path
import plistlib
import subprocess
import pytest
from test_work_laptop_package import script, repo


def checkout(tmp_path):
    remote = tmp_path / 'remote'; repo(remote)
    subprocess.run(['git', 'checkout', '-qb', 'work-pilot'], cwd=remote, check=True)
    work = tmp_path / 'work'
    subprocess.run(['git', 'clone', '-q', str(remote), str(work)], check=True)
    (work/'.env').write_text('PRIVATE_LOCAL_ENV')
    (work/'.venv/bin').mkdir(parents=True)
    (work/'.venv/bin/python').touch()
    (work/'.git/info/exclude').write_text('.env\n.venv/\n')
    (remote/'next.txt').write_text('next release')
    subprocess.run(['git', 'add', '.'], cwd=remote, check=True)
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'next'], cwd=remote, check=True)
    return work


def test_check_does_not_update_sources_or_local_configuration(tmp_path):
    work=checkout(tmp_path); updater=script('update_work_laptop')
    updater.update(work,tmp_path/'absent.plist',tmp_path/'backups',check=True)
    assert not (work/'next.txt').exists()
    assert (work/'.env').read_text()=='PRIVATE_LOCAL_ENV'
    assert not (tmp_path/'backups').exists()


@pytest.mark.parametrize('problem',['dirty','diverged','other_login'])
def test_update_refuses_unsafe_checkout_before_stopping_services(tmp_path,problem):
    work=checkout(tmp_path); updater=script('update_work_laptop'); plist=tmp_path/'login.plist'
    if problem=='dirty': (work/'README.md').write_text('uncommitted')
    if problem=='diverged':
        (work/'local.txt').write_text('local source change')
        subprocess.run(['git','add','.'],cwd=work,check=True)
        subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','local'],cwd=work,check=True)
    if problem=='other_login':plist.write_bytes(plistlib.dumps({'WorkingDirectory':'/another/install'}))
    with pytest.raises(SystemExit):updater.update(work,plist,tmp_path/'backups')
    assert not (work/'next.txt').exists()
    assert not (tmp_path/'backups').exists()


def test_backup_failure_cannot_advance_release_or_start_app(tmp_path,monkeypatch):
    work=checkout(tmp_path); updater=script('update_work_laptop'); real=updater.run; calls=[]
    def run(args,root,**kw):
        if args[0]=='git':return real(args,root,**kw)
        calls.append(args)
        if 'backup' in args:raise subprocess.CalledProcessError(1,args)
    monkeypatch.setattr(updater,'run',run)
    with pytest.raises(SystemExit,match='Update stopped'):updater.update(work,tmp_path/'absent',tmp_path/'backups')
    assert not (work/'next.txt').exists()
    assert not any('scripts/start.sh' in c for c in calls)


def test_failed_migration_keeps_new_code_and_backup_without_automatic_restore(tmp_path,monkeypatch):
    work=checkout(tmp_path); updater=script('update_work_laptop'); real=updater.run; calls=[]
    def run(args,root,**kw):
        if args[0]=='git':return real(args,root,**kw)
        calls.append(args)
        if 'backup' in args:
            target=Path(args[-1]);target.mkdir(parents=True);(target/'airlock.dump').write_bytes(b'backup')
        if 'scripts/setup.sh' in args:raise subprocess.CalledProcessError(1,args)
    monkeypatch.setattr(updater,'run',run)
    with pytest.raises(SystemExit,match='no automatic database rollback'):updater.update(work,tmp_path/'absent',tmp_path/'backups')
    assert (work/'next.txt').exists() and list((tmp_path/'backups').glob('*/airlock.dump'))
    assert (work/'.env').read_text()=='PRIVATE_LOCAL_ENV'
    assert not any('scripts/start.sh' in c or 'restore-empty' in c for c in calls)


def test_google_install_option_accepts_only_desktop_config(tmp_path):
    installer=script('work_laptop'); p=tmp_path/'oauth.json'
    client={'client_id':'synthetic.apps.googleusercontent.com','client_secret':'synthetic'}
    p.write_text(json.dumps({'web':client}))
    with pytest.raises(SystemExit):installer.google_client_path(p)
    p.write_text(json.dumps({'installed':client}))
    assert installer.google_client_path(p)==p.resolve()


def test_success_backs_up_old_revision_then_restores_login_after_health_check(tmp_path,monkeypatch):
    work=checkout(tmp_path); updater=script('update_work_laptop'); real=updater.run; calls=[]
    plist=tmp_path/'login.plist'
    plist.write_bytes(plistlib.dumps({'WorkingDirectory':str(work)}))
    def run(args,root,**kw):
        if args[0]=='git':return real(args,root,**kw)
        calls.append(args)
        if 'backup' in args:
            assert not (work/'next.txt').exists()
            target=Path(args[-1]);target.mkdir(parents=True);(target/'airlock.dump').write_bytes(b'backup')
        if 'scripts/setup.sh' in args:assert (work/'next.txt').exists()
    monkeypatch.setattr(updater,'run',run)
    updater.update(work,plist,tmp_path/'backups')
    actions=[c[2] if c[1]=='scripts/pilot.py' else c[1] for c in calls]
    assert actions==['login-remove','scripts/stop.sh','backup','scripts/setup.sh','scripts/start.sh','check','login-install']
    assert (work/'.env').read_text()=='PRIVATE_LOCAL_ENV'
