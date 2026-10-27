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
    path = tmp_path / 'gateway.toml'
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
