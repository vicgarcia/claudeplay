'''command line: claudeplay serve | check'''

import argparse
import sys
from pathlib import Path

from . import config, logs


def _load(path: str | None) -> config.GatewayConfig:
    return config.load(Path(path) if path else None)


def cmd_serve(args: argparse.Namespace) -> int:
    from . import gateway
    logs.setup(console=args.console)
    cfg = _load(args.config)
    gateway.serve(cfg)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='claudeplay', description='local mcp servers as one claude.ai connector')
    parser.add_argument('--config', help='path to gateway.toml (default: CLAUDEPLAY_CONFIG or the data dir)')
    sub = parser.add_subparsers(dest='command', required=True)

    serve = sub.add_parser('serve', help='run the gateway in the foreground')
    serve.add_argument('--console', action='store_true', help='also log to the console')
    serve.set_defaults(func=cmd_serve)

    check = sub.add_parser('check', help='validate the config')
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.func(args))
    except config.ConfigError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
