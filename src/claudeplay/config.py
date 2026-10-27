'''configuration for the gateway: gateway.toml parsing, ${ENV_VAR} expansion, paths'''

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765

_ENV_REF = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


class ConfigError(Exception):
    ''' raised for a bad config; messages name variables, never their values '''


def data_dir() -> Path:
    ''' per-user state directory (logs, status, token store, overrides) '''
    override = os.environ.get('CLAUDEPLAY_HOME')
    if override:
        return Path(override)
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'claudeplay'


def logs_dir() -> Path:
    return data_dir() / 'logs'


def status_path() -> Path:
    return data_dir() / 'status.json'


def overrides_path() -> Path:
    return data_dir() / 'overrides.json'


def default_config_path() -> Path:
    ''' CLAUDEPLAY_CONFIG wins, otherwise gateway.toml in the data dir '''
    override = os.environ.get('CLAUDEPLAY_CONFIG')
    return Path(override) if override else data_dir() / 'gateway.toml'


def expand(value: str, environ: dict[str, str] | None = None) -> str:
    ''' replace ${VAR} with its value; an unset variable is an error naming only the variable '''
    environ = os.environ if environ is None else environ

    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in environ:
            raise ConfigError(f'environment variable {name} is not set')
        return environ[name]

    return _ENV_REF.sub(sub, value)


@dataclass(frozen=True)
class ServerConfig:
    ''' one stdio server as written in gateway.toml; values are NOT expanded yet '''
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedServer:
    ''' a server with ${ENV_VAR} references expanded, ready to launch '''
    name: str
    command: str
    args: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class AuthConfig:
    ''' github oauth settings; values may hold ${ENV_VAR} references '''
    client_id: str = ''
    client_secret: str = ''
    jwt_signing_key: str = ''
    allowed_user_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GatewayConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    public_base_url: str = ''
    servers: tuple[ServerConfig, ...] = ()
    auth: AuthConfig | None = None

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f'http://localhost:{self.port}').rstrip('/')

    @property
    def endpoint_url(self) -> str:
        return f'{self.base_url}/mcp'

    def server(self, name: str) -> ServerConfig | None:
        return next((s for s in self.servers if s.name == name), None)


def resolve(server: ServerConfig, environ: dict[str, str] | None = None) -> ResolvedServer:
    ''' expand env references for one server; raises ConfigError if any variable is unset '''
    return ResolvedServer(
        name=server.name,
        command=expand(server.command, environ),
        args=[expand(a, environ) for a in server.args],
        env={k: expand(v, environ) for k, v in server.env.items()},
    )


def _parse_server(name: str, raw: dict) -> ServerConfig:
    command = raw.get('command')
    if not isinstance(command, str) or not command:
        raise ConfigError(f'server {name}: command is required')
    args = raw.get('args', [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ConfigError(f'server {name}: args must be a list of strings')
    env = raw.get('env', {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise ConfigError(f'server {name}: env must be a table of strings')
    enabled = raw.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ConfigError(f'server {name}: enabled must be true or false')
    return ServerConfig(name=name, command=command, args=tuple(args), env=dict(env), enabled=enabled)


def _parse_auth(raw: dict) -> AuthConfig:
    ids = raw.get('allowed_user_ids', [])
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ConfigError('auth: allowed_user_ids must be a list of numeric github user ids')
    return AuthConfig(
        client_id=str(raw.get('client_id', '')),
        client_secret=str(raw.get('client_secret', '')),
        jwt_signing_key=str(raw.get('jwt_signing_key', '')),
        allowed_user_ids=tuple(ids),
    )


def parse(text: str) -> GatewayConfig:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f'invalid toml: {e}') from None

    gw = raw.get('gateway', {})
    host = gw.get('host', DEFAULT_HOST)
    port = gw.get('port', DEFAULT_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigError('gateway: port must be an integer between 1 and 65535')

    servers_raw = raw.get('servers', {})
    if not isinstance(servers_raw, dict):
        raise ConfigError('servers must be a table of tables, e.g. [servers.obsidian]')
    servers = tuple(_parse_server(name, s) for name, s in servers_raw.items())

    auth = _parse_auth(raw['auth']) if 'auth' in raw else None
    return GatewayConfig(
        host=host,
        port=port,
        public_base_url=gw.get('public_base_url', ''),
        servers=servers,
        auth=auth,
    )


def load(path: Path | None = None) -> GatewayConfig:
    path = path or default_config_path()
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise ConfigError(f'config not found: {path}') from None
    return parse(text)


def load_overrides() -> dict[str, bool]:
    ''' enable/disable toggles set from the tray; kept out of gateway.toml so it stays hand-edited '''
    try:
        data = json.loads(overrides_path().read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    enabled = data.get('enabled', {}) if isinstance(data, dict) else {}
    return {k: v for k, v in enabled.items() if isinstance(v, bool)}


def save_overrides(enabled: dict[str, bool]) -> None:
    overrides_path().parent.mkdir(parents=True, exist_ok=True)
    overrides_path().write_text(json.dumps({'enabled': enabled}, indent=2), encoding='utf-8')


def is_enabled(server: ServerConfig, overrides: dict[str, bool]) -> bool:
    return overrides.get(server.name, server.enabled)
