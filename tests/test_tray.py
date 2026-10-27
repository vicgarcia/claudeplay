import subprocess
import sys
import uuid

import pytest

from claudeplay import autostart, config, supervisor, tray, winutil

from conftest import fake


class StubSupervisor:
    ''' enough of Supervisor for the tray to drive, with no processes '''

    def __init__(self):
        self.calls = []
        self._alive = False
        self.status = {}

    def alive(self):
        return self._alive

    def state(self):
        return supervisor.RUNNING if self._alive else supervisor.STOPPED

    def servers(self):
        return self.status

    def start(self):
        self.calls.append('start')
        self._alive = True

    def stop(self):
        self.calls.append('stop')
        self._alive = False

    def restart(self):
        self.calls.append('restart')
        self._alive = True

    def kill(self):
        self.calls.append('kill')
        self._alive = False


@pytest.fixture
def app():
    cfg = config.GatewayConfig(servers=(fake('obsidian'), fake('todo', enabled=False)))
    return tray.TrayApp(StubSupervisor(), cfg)


def test_icon_color_follows_state():
    seen = {}
    for state, color in tray.COLORS.items():
        image = tray.make_icon(state)
        assert image.size == (64, 64)
        seen[state] = image.getpixel((32, 32))[:3]
    assert len(set(seen.values())) == len(tray.COLORS)
    assert seen[supervisor.RUNNING] == (0x2e, 0xa0, 0x43)


def test_unknown_state_falls_back_to_stopped_colour():
    assert tray.make_icon('weird').getpixel((32, 32)) == tray.make_icon(supervisor.STOPPED).getpixel((32, 32))


def test_server_label_shows_state_or_error():
    servers = {'a': {'state': 'ok', 'error': ''}, 'b': {'state': 'failed', 'error': 'command not found'}}
    assert tray.server_label('a', servers) == 'a: ok'
    assert tray.server_label('b', servers) == 'b: command not found'
    assert tray.server_label('c', servers) == 'c'


def test_menu_has_the_required_controls(app):
    labels = [item.text for item in app.build_menu().items if item.text]
    for expected in ('Start', 'Stop', 'Restart', 'Servers', 'Copy connector URL', 'Open logs folder',
                     'Kill switch (stop everything)', 'Quit'):
        assert expected in labels


def test_start_and_stop_are_mutually_visible(app):
    items = {i.text: i for i in app.build_menu().items if i.text and i.text != 'Servers'}
    assert items['Start'].visible and not items['Stop'].visible
    app.sup.start()
    assert not items['Start'].visible and items['Stop'].visible


def test_toggle_server_persists_and_restarts_only_when_running(app):
    assert app.server_enabled('obsidian') and not app.server_enabled('todo')
    app.toggle_server('todo')
    assert app.server_enabled('todo')
    assert config.load_overrides() == {'todo': True}
    assert app.sup.calls == []

    app.sup.start()
    app.toggle_server('obsidian')
    assert not app.server_enabled('obsidian')
    assert config.load_overrides() == {'todo': True, 'obsidian': False}
    assert app.sup.calls == ['start', 'restart']


def test_kill_switch_calls_kill_not_stop(app):
    app.sup.start()
    app.kill()
    assert app.sup.calls == ['start', 'kill']


def test_copy_url_uses_the_connector_endpoint(app, monkeypatch):
    copied = []
    monkeypatch.setattr(winutil, 'copy_to_clipboard', copied.append)
    app.copy_url()
    assert copied == ['http://localhost:8765/mcp']


def test_single_instance_guard():
    name = f'claudeplay-test-{uuid.uuid4().hex}'
    first = winutil.SingleInstance(name)
    second = winutil.SingleInstance(name)
    assert first.acquired and not second.acquired
    first.release()
    second.release()
    third = winutil.SingleInstance(name)
    assert third.acquired
    third.release()


def test_port_owner_names_this_process():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        s.listen()
        port = s.getsockname()[1]
        assert winutil.port_in_use('127.0.0.1', port)
        assert 'python' in winutil.port_owner(port).lower()
    assert winutil.port_owner(1) == 'an unknown process'


def test_autostart_install_and_uninstall(tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDEPLAY_STARTUP_DIR', str(tmp_path / 'startup'))
    target = tmp_path / 'bin' / 'claudeplay-tray.exe'
    target.parent.mkdir()
    target.write_bytes(b'')
    assert not autostart.is_installed()
    link = autostart.install(target)
    assert link.exists() and autostart.is_installed()
    assert autostart.uninstall() is True
    assert not autostart.is_installed()
    assert autostart.uninstall() is False


def test_autostart_refuses_missing_target(tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDEPLAY_STARTUP_DIR', str(tmp_path / 'startup'))
    with pytest.raises(FileNotFoundError):
        autostart.install(tmp_path / 'missing.exe')
    assert not autostart.is_installed()


JOB_PARENT = '''
import subprocess, sys, time
from claudeplay import winutil
job = winutil.KillOnCloseJob()
assert job.active
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
print(child.pid, flush=True)
time.sleep(120)
'''


def test_kill_on_close_job_takes_children_down_with_the_parent():
    parent = subprocess.Popen([sys.executable, '-c', JOB_PARENT], stdout=subprocess.PIPE, text=True)
    try:
        child_pid = int(parent.stdout.readline())
        assert winutil.pid_alive(child_pid)
        # kill only the parent (no /T): the job, not the process tree, must take the child
        winutil.run_hidden(['taskkill', '/PID', str(parent.pid), '/F'])
        parent.wait(timeout=10)
        for _ in range(40):
            if not winutil.pid_alive(child_pid):
                break
            import time
            time.sleep(0.25)
        assert not winutil.pid_alive(child_pid)
    finally:
        parent.kill()
