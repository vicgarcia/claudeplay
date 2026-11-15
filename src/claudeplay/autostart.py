'''start the tray at logon with a shortcut in the user's Startup folder (no admin, no service)'''

import os
import sys
from pathlib import Path

from . import winutil

SHORTCUT_NAME = 'claudeplay.lnk'
# the windowless gui-script uv installs next to the interpreter
TRAY_EXE = 'claudeplay-tray.exe'


def startup_dir() -> Path:
    override = os.environ.get('CLAUDEPLAY_STARTUP_DIR')
    if override:
        return Path(override)
    return Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def tray_executable() -> Path:
    ''' the claudeplay-tray launcher in this install, as a full path '''
    return Path(sys.executable).with_name(TRAY_EXE)


def is_installed() -> bool:
    return shortcut_path().exists()


def install(target: Path | None = None) -> Path:
    target = target or tray_executable()
    if not target.exists():
        raise FileNotFoundError(f'{target} not found; install claudeplay as a uv tool first')
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    # start from a new shortcut: saving over an old one keeps any fields this does not set
    link.unlink(missing_ok=True)
    # single-quoted powershell literals: escape embedded quotes only, paths are not interpreted
    esc = lambda p: str(p).replace("'", "''")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
        "$s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; $s.Description = 'claudeplay tray'; $s.Save()"
    ) % (esc(link), esc(target), esc(target.parent))
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
