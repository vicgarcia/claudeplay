'''command line: claudeplay serve | tray | install | uninstall | status | check | genkey | browser login | browser clear'''

import argparse
import logging
import secrets
import sys
from pathlib import Path

from . import config, logs


LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


def _path(path: str | None) -> Path:
    return Path(path) if path else config.default_config_path()


def _load(path: str | None) -> config.GatewayConfig:
    return config.load(_path(path))


def cmd_serve(args: argparse.Namespace) -> int:
    from . import gateway
    logs.setup(console=args.console)
    cfg = _load(args.config)
    if cfg.auth is not None:
        from . import auth
        if config.ensure_signing_key(_path(args.config)):
            logging.getLogger('claudeplay').info('generated jwt_signing_key in the config file')
            cfg = _load(args.config)
        provider, allow_list = auth.build(cfg.auth, cfg.base_url)
        gateway.serve(cfg, auth=provider, extra_middleware=(allow_list,), raw=args.raw)
    elif args.insecure_no_auth or cfg.insecure_no_auth:
        if cfg.host not in LOOPBACK:
            raise config.ConfigError(f'refusing to serve without authentication on {cfg.host}; use 127.0.0.1')
        if cfg.tunnel_enabled:
            raise config.ConfigError('refusing to serve without authentication while a [tunnel] is enabled')
        logging.getLogger('claudeplay').warning('serving WITHOUT authentication (local use only)')
        gateway.serve(cfg, raw=args.raw)
    else:
        raise config.ConfigError('no [auth] section in the config; add one, or set insecure_no_auth = true under [gateway] for local use')
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    ''' show the effective config with secrets masked, and what would start, without launching anything '''
    path = _path(args.config)
    cfg = config.load(path)
    print(f'config:   {path}')
    for line in config.describe(cfg):
        print(line)
    print('checks:')
    for server in cfg.servers:
        if not server.enabled:
            print(f'  {server.name}: disabled')
            continue
        try:
            config.resolve(server)
            print(f'  {server.name}: ok')
        except config.ConfigError as e:
            print(f'  {server.name}: {e}')
    return 0


def cmd_tray(args: argparse.Namespace) -> int:
    from . import tray
    extra = ['--insecure-no-auth'] if args.insecure_no_auth else []
    return tray.run(Path(args.config) if args.config else None, extra, autostart_gateway=not args.no_start)


def cmd_install(_args: argparse.Namespace) -> int:
    from . import autostart
    try:
        link = autostart.install()
    except (FileNotFoundError, RuntimeError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    print(f'installed: {link}')
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    from . import autostart
    print('removed' if autostart.uninstall() else 'not installed')
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    ''' print the gateway's last status report '''
    from . import gateway, winutil
    data = gateway.read_status()
    if data is None:
        print('no status (gateway has not run)')
        return 1
    state = data['state'] if winutil.pid_alive(data['pid']) else 'stopped (stale report)'
    print(f"{state}  pid {data['pid']}  {data['url']}")
    for name, info in data['servers'].items():
        detail = info['error'] or (f"{info['tools']} tools" if info['tools'] is not None else '')
        print(f"  {name}: {info['state']}{'  ' + detail if detail else ''}")
    return 0


def cmd_browser_login(args: argparse.Namespace) -> int:
    ''' open web_fetch's signed-in profile in a window to sign in to sites by hand '''
    from . import browser
    cfg = _load(args.config)
    if not cfg.browser.signed_in_sites:
        print('note: no signed_in_sites under [browser] in the config, so web_fetch will not use these sign-ins yet')
    print(f'signing in with {cfg.browser.channel}; close the window when done')
    browser.login(cfg.browser, args.url)
    return 0


def cmd_browser_clear(_args: argparse.Namespace) -> int:
    ''' delete the signed-in profile, signing web_fetch out of every site '''
    from . import browser
    print('signed out of every site' if browser.clear() else 'no signed-in profile')
    return 0


def cmd_genkey(_args: argparse.Namespace) -> int:
    ''' print a random value suitable for CLAUDEPLAY_JWT_KEY '''
    print(secrets.token_urlsafe(48))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='claudeplay', description='local mcp servers as one claude.ai connector')
    parser.add_argument('--config', help=r'path to config.toml (default: CLAUDEPLAY_CONFIG, else %%LOCALAPPDATA%%\claudeplay\config.toml)')
    sub = parser.add_subparsers(dest='command', required=True)

    serve = sub.add_parser('serve', help='run the gateway in the foreground')
    serve.add_argument('--console', action='store_true', help='also log to the console')
    serve.add_argument('--insecure-no-auth', action='store_true', help='development only: serve without authentication')
    serve.add_argument('--raw', action='store_true', help='debugging: expose every backend tool instead of the curated toolkit')
    serve.set_defaults(func=cmd_serve)

    tray = sub.add_parser('tray', help='run the system-tray app (starts the gateway)')
    tray.add_argument('--no-start', action='store_true', help='do not start the gateway on launch')
    tray.add_argument('--insecure-no-auth', action='store_true', help='development only: gateway without authentication')
    tray.set_defaults(func=cmd_tray)

    sub.add_parser('install', help='start the tray at logon').set_defaults(func=cmd_install)
    sub.add_parser('uninstall', help='stop starting the tray at logon').set_defaults(func=cmd_uninstall)
    sub.add_parser('status', help='show the gateway status').set_defaults(func=cmd_status)

    check = sub.add_parser('check', help='validate the config')
    check.set_defaults(func=cmd_check)
    genkey = sub.add_parser('genkey', help='print a random signing key')
    genkey.set_defaults(func=cmd_genkey)

    browser = sub.add_parser('browser', help="manage web_fetch's signed-in browser profile")
    browser_sub = browser.add_subparsers(dest='browser_command', required=True)
    login = browser_sub.add_parser('login', help='open the profile in a window to sign in to sites by hand')
    login.add_argument('url', nargs='?', help='a page to open first, such as the sign-in page')
    login.set_defaults(func=cmd_browser_login)
    browser_sub.add_parser('clear', help='delete the profile, signing out of every site').set_defaults(func=cmd_browser_clear)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except config.ConfigError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
