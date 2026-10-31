'''system-tray ui: status colour, start/stop, per-server toggles, copy url, logs, kill switch'''

import ctypes
import logging
import math
import os
import threading
from pathlib import Path

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


def _arc(cx: float, cy: float, r: float, start: float, end: float) -> list[tuple[float, float]]:
    ''' points along a circle, angles in degrees (0 = right, 90 = down) '''
    steps = 48
    angles = (math.radians(start + (end - start) * i / steps) for i in range(steps + 1))
    return [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]


# the wire of an upright paperclip on a 256px canvas: up the outer left leg, over, down the right,
# under, up the inner left leg, over, and down to the free end
PAPERCLIP = [
    (76, 177),
    *_arc(128, 87, 52, 180, 360),
    *_arc(146, 187, 34, 0, 180),
    *_arc(128, 103, 16, 180, 360),
    (144, 167),
]


def _stroke(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], width: int, fill: str) -> None:
    ''' a polyline with round joints and ends, which ImageDraw.line does not do '''
    draw.line(points, fill=fill, width=width)
    r = width / 2
    for x, y in points:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def make_icon(state: str) -> Image.Image:
    ''' a white paperclip on a disc in the state colour, drawn large and scaled down to smooth the edges '''
    size = 256
    disc = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((4, 4, size - 4, size - 4), fill=COLORS.get(state, COLORS[supervisor.STOPPED]))
    clip = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    _stroke(ImageDraw.Draw(clip), PAPERCLIP, 18, '#ffffff')
    clip = clip.rotate(-40, resample=Image.BICUBIC, center=(128, 128))
    return Image.alpha_composite(disc, clip).resize((64, 64), Image.LANCZOS)


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
    def __init__(self, sup: Supervisor, cfg: config.GatewayConfig, config_path: Path):
        self.sup = sup
        self.cfg = cfg
        self.config_path = config_path
        self.icon = pystray.Icon('claudeplay', make_icon(supervisor.STOPPED), 'claudeplay: stopped', menu=self.build_menu())
        self._last_state = supervisor.STOPPED
        self._stop = threading.Event()

    # menu state

    def running(self) -> bool:
        return self.sup.alive()

    def server_enabled(self, name: str) -> bool:
        server = self.cfg.server(name)
        return server is not None and server.enabled

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
            pystray.MenuItem(lambda _item: f'tunnel: {self.sup.tunnel_state()}', None, enabled=False,
                             visible=lambda _item: self.cfg.tunnel_enabled),
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
        enabled = not self.server_enabled(name)
        try:
            config.set_enabled(self.config_path, name, enabled)
            self.cfg = config.load(self.config_path)
        except (config.ConfigError, OSError) as e:
            log.warning('could not toggle server %s: %s', name, e)
            self.notify(f'could not change {name}: {e}')
            return
        # the gateway re-reads the file when it starts
        self.sup.cfg = self.cfg
        log.info('server %s %s', name, 'enabled' if enabled else 'disabled')
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
        self.sup.check_tunnel()
        state = self.sup.state()
        if state != self._last_state:
            if state == supervisor.CRASHED:
                self.notify('the gateway stopped unexpectedly; see the logs')
            elif state == supervisor.DEGRADED and self.sup.tunnel_state() == supervisor.TUNNEL_DOWN:
                self.notify('the tunnel is down; retrying')
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
        config_path = config_path or config.default_config_path()
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
        TrayApp(sup, cfg, config_path).run(autostart_gateway)
    finally:
        sup.stop()
        guard.release()
    return 0
