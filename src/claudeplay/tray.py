'''system-tray ui: status colour, start/stop, per-server toggles, copy url, logs, kill switch'''

import ctypes
import logging
import os
import threading

import pystray
from PIL import Image, ImageDraw

from . import config, supervisor, winutil
from .supervisor import Supervisor

log = logging.getLogger('claudeplay.tray')

MUTEX_NAME = 'claudeplay-tray'
POLL_SECONDS = 2.0

COLORS = {
    supervisor.STOPPED: '#7d8590',
    supervisor.STARTING: '#d29922',
    supervisor.RUNNING: '#2ea043',
    supervisor.DEGRADED: '#f0883e',
    supervisor.CRASHED: '#da3633',
}


def make_icon(state: str) -> Image.Image:
    ''' a filled circle in the state colour on a transparent background '''
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 4, size - 4), fill=COLORS.get(state, COLORS[supervisor.STOPPED]), outline='#1f2328', width=3)
    return image


def message_box(text: str, title: str = 'claudeplay') -> None:
    ''' the tray runs without a console, so fatal startup problems have to be shown in a dialog '''
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def server_label(name: str, servers: dict[str, dict]) -> str:
    info = servers.get(name)
    if not info:
        return name
    detail = info.get('error') or info.get('state', '')
    return f'{name}: {detail}' if detail else name


class TrayApp:
    def __init__(self, sup: Supervisor, cfg: config.GatewayConfig):
        self.sup = sup
        self.cfg = cfg
        self.overrides = config.load_overrides()
        self.icon = pystray.Icon('claudeplay', make_icon(supervisor.STOPPED), 'claudeplay: stopped', menu=self.build_menu())
        self._last_state = supervisor.STOPPED
        self._stop = threading.Event()

    # menu state

    def running(self) -> bool:
        return self.sup.alive()

    def server_enabled(self, name: str) -> bool:
        server = self.cfg.server(name)
        return server is not None and config.is_enabled(server, self.overrides)

    def server_item(self, name: str) -> pystray.MenuItem:
        # a method (not a loop lambda) so each item closes over its own name
        return pystray.MenuItem(
            lambda _item: server_label(name, self.sup.servers()),
            lambda _icon, _item: self.toggle_server(name),
            checked=lambda _item: self.server_enabled(name),
        )

    def build_menu(self) -> pystray.Menu:
        servers = [self.server_item(s.name) for s in self.cfg.servers]
        return pystray.Menu(
            pystray.MenuItem(lambda _item: f'claudeplay: {self.sup.state()}', None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Start', lambda _i, _m: self.start(), visible=lambda _item: not self.running()),
            pystray.MenuItem('Stop', lambda _i, _m: self.stop(), visible=lambda _item: self.running()),
            pystray.MenuItem('Restart', lambda _i, _m: self.restart(), enabled=lambda _item: self.running()),
            pystray.MenuItem('Servers', pystray.Menu(*servers), enabled=bool(servers)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Copy connector URL', lambda _i, _m: self.copy_url()),
            pystray.MenuItem('Open logs folder', lambda _i, _m: self.open_logs()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Kill switch (stop everything)', lambda _i, _m: self.kill()),
            pystray.MenuItem('Quit', lambda _i, _m: self.quit()),
        )

    # actions

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, 'claudeplay')
        except Exception:
            log.warning('could not show notification')

    def start(self) -> None:
        try:
            self.sup.start()
        except supervisor.PortInUse as e:
            log.warning('%s', e)
            self.notify(str(e))
        except OSError as e:
            log.warning('could not start gateway: %s', type(e).__name__)
            self.notify(f'could not start gateway ({type(e).__name__})')
        self.refresh()

    def stop(self) -> None:
        self.sup.stop()
        self.refresh()

    def restart(self) -> None:
        try:
            self.sup.restart()
        except supervisor.PortInUse as e:
            self.notify(str(e))
        self.refresh()

    def kill(self) -> None:
        self.sup.kill()
        self.refresh()
        self.notify('everything stopped')

    def toggle_server(self, name: str) -> None:
        self.overrides[name] = not self.server_enabled(name)
        config.save_overrides(self.overrides)
        log.info('server %s %s', name, 'enabled' if self.overrides[name] else 'disabled')
        # servers are mounted when the gateway starts, so a toggle takes effect on restart
        if self.running():
            self.restart()
        else:
            self.refresh()

    def copy_url(self) -> None:
        winutil.copy_to_clipboard(self.cfg.endpoint_url)

    def open_logs(self) -> None:
        config.logs_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(config.logs_dir())

    def quit(self) -> None:
        self.sup.stop()
        self._stop.set()
        self.icon.stop()

    # status polling

    def refresh(self) -> None:
        state = self.sup.state()
        if state != self._last_state:
            if state == supervisor.CRASHED:
                self.notify('the gateway stopped unexpectedly; see the logs')
            self._last_state = state
            self.icon.icon = make_icon(state)
            self.icon.title = f'claudeplay: {state}'
        self.icon.update_menu()

    def _poll(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self.refresh()
            except Exception:
                log.exception('status refresh failed')

    def run(self, autostart_gateway: bool = True) -> None:
        def setup(icon: pystray.Icon) -> None:
            icon.visible = True
            if autostart_gateway:
                self.start()
            threading.Thread(target=self._poll, daemon=True).start()

        self.icon.run(setup)


def run(config_path=None, extra_args: list[str] | None = None, autostart_gateway: bool = True) -> int:
    ''' tray entry point; returns a process exit code '''
    from . import logs

    logs.setup()
    guard = winutil.SingleInstance(MUTEX_NAME)
    if not guard.acquired:
        message_box('claudeplay is already running (look for its icon in the system tray).')
        return 1
    try:
        cfg = config.load(config_path)
    except config.ConfigError as e:
        message_box(f'cannot start: {e}')
        return 2
    # if the tray is killed or crashes, the gateway and its stdio servers must not outlive it
    job = winutil.KillOnCloseJob()
    if not job.active:
        log.warning('could not create kill-on-close job; children may outlive a killed tray')
    sup = Supervisor(cfg, config_path, extra_args)
    try:
        TrayApp(sup, cfg).run(autostart_gateway)
    finally:
        sup.stop()
        guard.release()
    return 0
