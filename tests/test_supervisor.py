import dataclasses
import socket
import sys
import time

import pytest

from claudeplay import config, supervisor, winutil
from claudeplay.supervisor import Supervisor

from conftest import FAKE_SERVER


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def write_config(tmp_path, port: int):
    path = tmp_path / 'config.toml'
    path.write_text(
        f"[gateway]\nport = {port}\n\n"
        f"[servers.a]\ncommand = '{sys.executable}'\nargs = ['{FAKE_SERVER}']\n\n"
        f"[servers.off]\ncommand = '{sys.executable}'\nenabled = false\n"
    )
    return path


def wait_for(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return False


@pytest.fixture
def sup(tmp_path):
    port = free_port()
    path = write_config(tmp_path, port)
    s = Supervisor(config.load(path), path, ['--insecure-no-auth'])
    yield s
    s.kill()


def test_start_reports_running_then_stop_frees_the_port(sup):
    assert sup.state() == supervisor.STOPPED
    sup.start()
    assert sup.state() in (supervisor.STARTING, supervisor.RUNNING)
    assert wait_for(lambda: sup.state() == supervisor.RUNNING), sup.state()
    servers = sup.servers()
    assert servers['a']['state'] == 'ok' and servers['off']['state'] == 'disabled'
    assert winutil.port_in_use(sup.cfg.host, sup.cfg.port)

    sup.stop()
    assert sup.state() == supervisor.STOPPED
    assert wait_for(lambda: not winutil.port_in_use(sup.cfg.host, sup.cfg.port), 10)


def test_start_is_idempotent(sup):
    sup.start()
    pid = sup._proc.pid
    sup.start()
    assert sup._proc.pid == pid


def test_kill_switch_stops_immediately(sup):
    sup.start()
    assert wait_for(lambda: sup.state() == supervisor.RUNNING)
    sup.kill()
    assert sup.state() == supervisor.STOPPED
    assert wait_for(lambda: not winutil.port_in_use(sup.cfg.host, sup.cfg.port), 10)


def test_unexpected_exit_is_reported_as_crashed(sup):
    sup.start()
    assert wait_for(lambda: sup.state() == supervisor.RUNNING)
    Supervisor.kill_tree(sup._proc.pid)
    assert wait_for(lambda: sup.state() == supervisor.CRASHED, 10)


def test_start_refuses_when_port_is_taken_and_names_the_owner(tmp_path):
    with socket.socket() as blocker:
        blocker.bind(('127.0.0.1', 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        path = write_config(tmp_path, port)
        s = Supervisor(config.load(path), path, ['--insecure-no-auth'])
        with pytest.raises(supervisor.PortInUse) as e:
            s.start()
        assert str(port) in str(e.value)
        assert 'pid' in e.value.owner
        assert s.state() == supervisor.STOPPED


def test_stale_status_file_from_another_process_is_ignored(sup):
    config.status_path().parent.mkdir(parents=True, exist_ok=True)
    config.status_path().write_text('{"pid": 1, "state": "running", "servers": {}}')
    assert sup.state() == supervisor.STOPPED
    assert sup.snapshot() is None


SLEEPER = [sys.executable, '-c', 'import time; time.sleep(120)']


def tunnel_sup(tmp_path, monkeypatch, command=None):
    ''' a supervisor whose "cloudflared" is a sleeping python process (or a given command)

    the tunnel is only in the supervisor's config, not the file: the gateway child refuses no-auth with a tunnel
    '''
    path = write_config(tmp_path, free_port())
    cfg = dataclasses.replace(config.load(path), tunnel=config.TunnelConfig(name='claudeplay'))
    s = Supervisor(cfg, path, ['--insecure-no-auth'])
    monkeypatch.setattr(s, 'tunnel_command', lambda: command or SLEEPER)
    return s


def test_tunnel_command_runs_the_named_tunnel_against_the_gateway(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text("[gateway]\nport = 9999\n\n[tunnel]\nname = 'claudeplay'\ncommand = 'cf.exe'\n")
    cmd = Supervisor(config.load(path), path).tunnel_command()
    assert cmd[0] == 'cf.exe' and cmd[1] == 'tunnel' and '--no-autoupdate' in cmd
    assert cmd[-4:] == ['run', '--url', 'http://127.0.0.1:9999', 'claudeplay']


def test_tunnel_starts_with_the_gateway_and_the_kill_switch_takes_both(tmp_path, monkeypatch):
    s = tunnel_sup(tmp_path, monkeypatch)
    try:
        assert s.tunnel_state() == supervisor.TUNNEL_OFF
        s.start()
        assert s.tunnel_state() == supervisor.TUNNEL_UP
        tunnel_pid = s._tunnel.pid
        assert wait_for(lambda: s.state() == supervisor.RUNNING), s.state()
        s.kill()
        assert s.tunnel_state() == supervisor.TUNNEL_OFF and s.state() == supervisor.STOPPED
        assert wait_for(lambda: not winutil.pid_alive(tunnel_pid), 10)
    finally:
        s.kill()


def test_dead_tunnel_degrades_and_is_restarted(tmp_path, monkeypatch):
    s = tunnel_sup(tmp_path, monkeypatch)
    try:
        s.start()
        assert wait_for(lambda: s.state() == supervisor.RUNNING), s.state()
        first = s._tunnel.pid
        Supervisor.kill_tree(first)
        assert wait_for(lambda: s.tunnel_state() == supervisor.TUNNEL_DOWN, 10)
        assert s.state() == supervisor.DEGRADED
        # within the retry interval nothing happens
        s.check_tunnel()
        assert s.tunnel_state() == supervisor.TUNNEL_DOWN
        monkeypatch.setattr(supervisor, 'TUNNEL_RETRY_SECONDS', 0.0)
        s.check_tunnel()
        assert s.tunnel_state() == supervisor.TUNNEL_UP and s._tunnel.pid != first
        assert s.state() == supervisor.RUNNING
    finally:
        s.kill()


def test_missing_cloudflared_leaves_the_gateway_running(tmp_path, monkeypatch):
    s = tunnel_sup(tmp_path, monkeypatch, command=[str(tmp_path / 'no-such-cloudflared.exe')])
    try:
        s.start()
        assert s.alive() and s.tunnel_state() == supervisor.TUNNEL_DOWN
        assert wait_for(lambda: s.state() == supervisor.DEGRADED), s.state()
    finally:
        s.kill()


def test_gateway_accepts_the_public_host_and_rejects_others(tmp_path, monkeypatch):
    import urllib.error
    import urllib.request
    # no [tunnel] here: only the Host check is under test
    port = free_port()
    path = write_config(tmp_path, port)
    path.write_text(path.read_text().replace('[gateway]\n', "[gateway]\npublic_base_url = 'https://cp-test.example.net'\n"))
    s = Supervisor(config.load(path), path, ['--insecure-no-auth'])
    try:
        s.start()
        assert wait_for(lambda: s.state() == supervisor.RUNNING), s.state()

        def status(host):
            req = urllib.request.Request(f'http://127.0.0.1:{port}/mcp', headers={'Host': host, 'Accept': 'text/event-stream'})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        assert status('elsewhere.example.net') == 421
        assert status('cp-test.example.net') != 421
        assert status(f'localhost:{port}') != 421
    finally:
        s.kill()
