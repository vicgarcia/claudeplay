'''command line: claudeplay serve | tray | install | uninstall | status | check | genkey'''

import argparse
import logging
import secrets
import sys
from pathlib import Path

from . import config, logs


def _load(path: str | None) -> config.GatewayConfig:
    return config.load(Path(path) if path else None)


def cmd_serve(args: argparse.Namespace) -> int:
    from . import gateway
    logs.setup(console=args.console)
    cfg = _load(args.config)
    if cfg.auth is not None:
        from . import auth
        provider, allow_list = auth.build(cfg.auth, cfg.base_url)
        gateway.serve(cfg, auth=provider, extra_middleware=(allow_list,))
    elif args.insecure_no_auth:
        logging.getLogger('claudeplay').warning('serving WITHOUT authentication (--insecure-no-auth)')
        gateway.serve(cfg)
    else:
        raise config.ConfigError('no [auth] section in the config; add one, or pass --insecure-no-auth for local development')
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    ''' validate the config and report what would start, without launching anything '''
    cfg = _load(args.config)
    overrides = config.load_overrides()
    print(f'endpoint: {cfg.endpoint_url}')
    for server in cfg.servers:
        if not config.is_enabled(server, overrides):
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


def cmd_genkey(_args: argparse.Namespace) -> int:
    ''' print a random value suitable for CLAUDEPLAY_JWT_KEY '''
    print(secrets.token_urlsafe(48))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='claudeplay', description='local mcp servers as one claude.ai connector')
    parser.add_argument('--config', help='path to gateway.toml (default: CLAUDEPLAY_CONFIG or the data dir)')
    sub = parser.add_subparsers(dest='command', required=True)

    serve = sub.add_parser('serve', help='run the gateway in the foreground')
    serve.add_argument('--console', action='store_true', help='also log to the console')
    serve.add_argument('--insecure-no-auth', action='store_true', help='development only: serve without authentication')
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
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except config.ConfigError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
