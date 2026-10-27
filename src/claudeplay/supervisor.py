'''start, stop and observe the gateway as a child process'''

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

from . import config, gateway, winutil

log = logging.getLogger('claudeplay.supervisor')

STOPPED = 'stopped'
STARTING = 'starting'
RUNNING = 'running'
DEGRADED = 'degraded'
# the gateway process exited without being asked to
CRASHED = 'crashed'

class PortInUse(Exception):
    def __init__(self, port: int, owner: str):
        super().__init__(f'port {port} is already in use by {owner}')
        self.port = port
        self.owner = owner


class Supervisor:
    def __init__(self, cfg: config.GatewayConfig, config_path: Path | None = None, extra_args: list[str] | None = None):
        self.cfg = cfg
        self.config_path = config_path
        self.extra_args = extra_args or []
        self._proc: subprocess.Popen | None = None
        self._wanted = False
        self._run_id = ''

    def command(self) -> list[str]:
        ''' full interpreter path, because PATH at logon differs from an interactive shell '''
        cmd = [sys.executable, '-m', 'claudeplay']
        if self.config_path:
            cmd += ['--config', str(self.config_path)]
        return cmd + ['serve', *self.extra_args]

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.alive():
            return
        if winutil.port_in_use(self.cfg.host, self.cfg.port):
            raise PortInUse(self.cfg.port, winutil.port_owner(self.cfg.port))
        # a stale file from an earlier run must not be mistaken for this run's state
        try:
            config.status_path().unlink()
        except FileNotFoundError:
            pass
        self._run_id = uuid.uuid4().hex
        self._proc = subprocess.Popen(
            self.command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=winutil.CREATE_NO_WINDOW,
            env={**os.environ, 'CLAUDEPLAY_RUN_ID': self._run_id},
        )
        self._wanted = True
        log.info('gateway started, pid %d', self._proc.pid)

    def stop(self) -> None:
        ''' stop the gateway and everything under it '''
        self._wanted = False
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        # terminate() would only reach the venv launcher, not the interpreter behind it
        self.kill_tree(proc.pid)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning('gateway did not exit after taskkill')
        log.info('gateway stopped')

    def kill(self) -> None:
        ''' kill switch: the same hard stop, kept separate so the tunnel can join it later '''
        self.stop()

    @staticmethod
    def kill_tree(pid: int) -> None:
        winutil.run_hidden(['taskkill', '/PID', str(pid), '/T', '/F'])

    def restart(self) -> None:
        self.stop()
        self.start()

    def snapshot(self) -> dict | None:
        ''' the gateway's own status report, only if it came from the process we started '''
        data = gateway.read_status()
        if data and self._proc is not None and data.get('run_id') == self._run_id:
            return data
        return None

    def state(self) -> str:
        if self._proc is None:
            return STOPPED
        if self._proc.poll() is not None:
            return CRASHED if self._wanted else STOPPED
        data = self.snapshot()
        if data is None:
            return STARTING
        return data.get('state', STARTING)

    def servers(self) -> dict[str, dict]:
        data = self.snapshot()
        return data['servers'] if data else {}
