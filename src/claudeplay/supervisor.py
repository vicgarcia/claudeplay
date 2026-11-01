'''start, stop and observe the gateway as a child process'''

import logging
import os
import subprocess
import sys
import time
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

# tunnel states, shown in the tray menu
TUNNEL_OFF = 'off'
TUNNEL_UP = 'up'
TUNNEL_DOWN = 'down'
# seconds between attempts to bring a dead tunnel back
TUNNEL_RETRY_SECONDS = 15.0

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
        self._tunnel: subprocess.Popen | None = None
        self._tunnel_started = 0.0

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
        self.start_tunnel()

    # the tunnel

    def tunnel_command(self) -> list[str]:
        tunnel = self.cfg.tunnel
        return [
            tunnel.command, 'tunnel', '--no-autoupdate',
            '--logfile', str(config.logs_dir() / 'cloudflared.log'),
            'run', '--url', f'http://{self.cfg.host}:{self.cfg.port}', tunnel.name,
        ]

    def tunnel_alive(self) -> bool:
        return self._tunnel is not None and self._tunnel.poll() is None

    def start_tunnel(self) -> None:
        if not self.cfg.tunnel_enabled or self.tunnel_alive():
            return
        config.logs_dir().mkdir(parents=True, exist_ok=True)
        self._tunnel_started = time.monotonic()
        try:
            self._tunnel = subprocess.Popen(
                self.tunnel_command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=winutil.CREATE_NO_WINDOW,
            )
        except OSError as e:
            # a missing cloudflared must not take the local gateway down with it
            self._tunnel = None
            log.warning('could not start tunnel: %s', e)
            return
        log.info('tunnel %s started, pid %d', self.cfg.tunnel.name, self._tunnel.pid)

    def stop_tunnel(self) -> None:
        proc, self._tunnel = self._tunnel, None
        if proc is None or proc.poll() is not None:
            return
        self.kill_tree(proc.pid)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning('tunnel did not exit after taskkill')
        log.info('tunnel stopped')

    def tunnel_state(self) -> str:
        if not self.cfg.tunnel_enabled or not self._wanted:
            return TUNNEL_OFF
        return TUNNEL_UP if self.tunnel_alive() else TUNNEL_DOWN

    def check_tunnel(self) -> None:
        ''' called on every status poll: bring a dead tunnel back, at most once per retry interval '''
        if self.tunnel_state() != TUNNEL_DOWN or not self.alive():
            return
        if time.monotonic() - self._tunnel_started < TUNNEL_RETRY_SECONDS:
            return
        log.warning('tunnel is down, restarting it')
        self.start_tunnel()

    def stop(self) -> None:
        ''' stop the tunnel, then the gateway and everything under it '''
        self._wanted = False
        # tunnel first, so nothing public points at a gateway that is going away
        self.stop_tunnel()
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
        state = data.get('state', STARTING)
        if state == RUNNING and self.tunnel_state() == TUNNEL_DOWN:
            return DEGRADED
        return state

    def servers(self) -> dict[str, dict]:
        data = self.snapshot()
        return data['servers'] if data else {}
