"""Distribution must exclude workstation state and refuse accidental data reuse."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo(path):
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    (path/'README.md').write_text('Source only\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=path, check=True)
    subprocess.run(['git', '-c', 'user.name=Package test', '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'fixture'], cwd=path, check=True)


def test_archive_uses_committed_source_and_omits_untracked_secrets(tmp_path):
    checkout = tmp_path/'checkout';repo(checkout)
    (checkout/'.env').write_text('SECRET_SENTINEL')
    (checkout/'data').mkdir()
    (checkout/'data/invitation.json').write_text('PRIVATE_PAIRING_SENTINEL')
    target = script('package_work_laptop').build(checkout, tmp_path/'output')
    with tarfile.open(target) as archive:
        assert set(archive.getnames()) == {'Airlock/README.md', 'Airlock/AIRLOCK_BUILD.json'}
        manifest = json.load(archive.extractfile('Airlock/AIRLOCK_BUILD.json'))
        assert manifest['runtime_state_included'] is False
        assert set(manifest['sha256']) == {'README.md'}
    assert target.with_name(target.name+'.sha256').is_file()


def test_archive_refuses_uncommitted_tracked_changes(tmp_path):
    repo(tmp_path)
    (tmp_path/'README.md').write_text('untested changes')
    with pytest.raises(subprocess.CalledProcessError):
        script('package_work_laptop').build(tmp_path, tmp_path/'output')


def test_login_finds_installed_tools_without_inheriting_shell_environment(monkeypatch, tmp_path):
    pilot = script('pilot')
    monkeypatch.setattr(pilot.shutil, 'which', lambda name: {'docker':'/opt/homebrew/bin/docker',
                                                         'ollama':'/usr/local/bin/ollama'}[name])
    plist = pilot.login_plist(tmp_path)
    assert plist['EnvironmentVariables'] == {'PATH':'/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
    assert plist['ProgramArguments'][0] == str(tmp_path/'.venv/bin/python')
    assert plist['WorkingDirectory'] == str(tmp_path)


def test_login_refuses_missing_tools(monkeypatch):
    pilot = script('pilot')
    monkeypatch.setattr(pilot.shutil, 'which', lambda _: None)
    with pytest.raises(SystemExit, match='installed'):
        pilot.login_plist()


def test_first_install_refuses_existing_workspace_before_running_commands(monkeypatch, tmp_path):
    install = script('work_laptop')
    monkeypatch.setattr(install.sys, 'platform', 'darwin')
    run = Mock();monkeypatch.setattr(install.subprocess, 'run', run)
    (tmp_path/'.env').write_text('existing')
    with pytest.raises(SystemExit, match='already has local state'):
        install.preflight(tmp_path, 'America/New_York')
    run.assert_not_called()


def test_first_install_refuses_preexisting_database_volume(monkeypatch, tmp_path):
    install = script('work_laptop')
    monkeypatch.setattr(install.sys, 'platform', 'darwin')
    monkeypatch.setattr(install.shutil, 'which', lambda name: '/usr/local/bin/'+name)
    monkeypatch.setattr(install.subprocess, 'run', lambda *a, **kw: Mock(returncode=0))
    monkeypatch.setattr(install.subprocess, 'check_output', lambda *a, **kw: 'airlock-local_airlock-data\n')
    with pytest.raises(SystemExit, match='database volume already exists'):
        install.preflight(tmp_path, 'America/New_York')
    assert not list(tmp_path.iterdir())
