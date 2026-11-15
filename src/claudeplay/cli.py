'''command line: claudeplay serve | tray | install | uninstall | status | check | genkey'''

import argparse
import logging
import secrets
import sys
from pathlib import Path

from . import clock, config, logs, toolkit


LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


def _path(path: str | None) -> Path:
    return Path(path) if path else config.default_config_path()


def _load(path: str | None) -> config.GatewayConfig:
    return config.load(_path(path))


def cmd_serve(args: argparse.Namespace) -> int:
    from . import gateway
    logs.setup(console=args.console)
    cfg = _load(args.config)
    # --raw is for debugging a backend and needs no toolkit
    tk = None if args.raw else toolkit.load(_path(args.config), cfg, (clock.ENTRY,))
    if cfg.auth is not None:
        from . import auth
        if config.ensure_signing_key(_path(args.config)):
            logging.getLogger('claudeplay').info('generated jwt_signing_key in the config file')
            cfg = _load(args.config)
        provider, allow_list = auth.build(cfg.auth, cfg.base_url)
        gateway.serve(cfg, tk, auth=provider, extra_middleware=(allow_list,), raw=args.raw)
    elif args.insecure_no_auth or cfg.insecure_no_auth:
        if cfg.host not in LOOPBACK:
            raise config.ConfigError(f'refusing to serve without authentication on {cfg.host}; use 127.0.0.1')
        if cfg.tunnel_enabled:
            raise config.ConfigError('refusing to serve without authentication while a tunnel is enabled')
        logging.getLogger('claudeplay').warning('serving WITHOUT authentication (local use only)')
        gateway.serve(cfg, tk, raw=args.raw)
    else:
        raise config.ConfigError('no auth section in the config; add one, or set insecure_no_auth: true under gateway for local use')
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    ''' show the effective config with secrets masked, and what would start, without launching anything '''
    path = _path(args.config)
    cfg = config.load(path)
    print(f'config:   {path}')
    for line in config.describe(cfg):
        print(line)
    tk = toolkit.load(path, cfg, (clock.ENTRY,))
    print(f'toolkit:  {config.toolkit_path(path)}')
    counts = tk.counts()
    print('checks:')
    for server in cfg.servers:
        listed = f'{counts[server.name]} tools listed' if server.name in counts else 'no toolkit section, exposes nothing'
        if not server.enabled:
            print(f'  {server.name}: disabled, {listed}')
            continue
        try:
            config.resolve(server)
            print(f'  {server.name}: ok, {listed}')
        except config.ConfigError as e:
            print(f'  {server.name}: {e}, {listed}')
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


def cmd_genkey(_args: argparse.Namespace) -> int:
    ''' print a random value suitable for CLAUDEPLAY_JWT_KEY '''
    print(secrets.token_urlsafe(48))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='claudeplay', description='local mcp servers as one claude.ai connector')
    parser.add_argument('--config', help='path to config.yaml (default: config.yaml in CLAUDEPLAY_HOME, else ~/.claudeplay); toolkit.yaml is read from the same folder')
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

    check = sub.add_parser('check', help='validate config.yaml and toolkit.yaml')
    check.set_defaults(func=cmd_check)
    genkey = sub.add_parser('genkey', help='print a random signing key')
    genkey.set_defaults(func=cmd_genkey)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except config.ConfigError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
