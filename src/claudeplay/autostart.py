'''start the tray at logon with a shortcut in the user's Startup folder (no admin, no service)'''

import os
import sys
from pathlib import Path

from . import winutil

SHORTCUT_NAME = 'claudeplay.lnk'
# Smart App Control blocks the per-install launcher stubs uv generates (claudeplay-tray.exe), because
# each has a unique hash with no reputation; the standard pythonw.exe is allowed, so run the module with it
TRAY_ARGS = '-m claudeplay tray'


def startup_dir() -> Path:
    override = os.environ.get('CLAUDEPLAY_STARTUP_DIR')
    if override:
        return Path(override)
    return Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def tray_executable() -> Path:
    ''' the windowless interpreter next to this one, as a full path '''
    return Path(sys.executable).with_name('pythonw.exe')


def is_installed() -> bool:
    return shortcut_path().exists()


def install(target: Path | None = None) -> Path:
    target = target or tray_executable()
    if not target.exists():
        raise FileNotFoundError(f'{target} not found; install claudeplay as a uv tool first')
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    # single-quoted powershell literals: escape embedded quotes only, paths are not interpreted
    esc = lambda p: str(p).replace("'", "''")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
        "$s.TargetPath = '%s'; $s.Arguments = '%s'; $s.WorkingDirectory = '%s'; $s.Description = 'claudeplay tray'; $s.Save()"
    ) % (esc(link), esc(target), esc(TRAY_ARGS), esc(target.parent))
    result = winutil.run_hidden(['powershell', '-NoProfile', '-NonInteractive', '-Command', script])
    if result.returncode != 0 or not link.exists():
        raise RuntimeError(f'could not create startup shortcut: {result.stderr.strip()}')
    return link


def uninstall() -> bool:
    ''' remove the shortcut; returns False if there was none '''
    try:
        shortcut_path().unlink()
        return True
    except FileNotFoundError:
        return False
