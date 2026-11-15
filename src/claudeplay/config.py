'''the claudeplay config file (config.yaml): parsing, in-place edits, optional ${ENV_VAR} expansion, paths'''

import io
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765
# where the winget/msi install puts it
DEFAULT_CLOUDFLARED = 'C:/Program Files (x86)/cloudflared/cloudflared.exe'

CONFIG_NAME = 'config.yaml'
TOOLKIT_NAME = 'toolkit.yaml'

_ENV_REF = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


class ConfigError(Exception):
    ''' raised for a bad config; messages name files, keys and variables, never their values '''


def home_dir() -> Path:
    ''' where configuration and credentials live: config, toolkit, status, token store, tunnel credentials '''
    override = os.environ.get('CLAUDEPLAY_HOME')
    return Path(override) if override else Path.home() / '.claudeplay'


def logs_dir() -> Path:
    ''' where logs live, apart from the credentials so a log folder is safe to open and share '''
    override = os.environ.get('CLAUDEPLAY_LOGS')
    if override:
        return Path(override)
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'claudeplay' / 'logs'


def status_path() -> Path:
    return home_dir() / 'status.json'


def default_config_path() -> Path:
    return home_dir() / CONFIG_NAME


def toolkit_path(config_path: Path | None = None) -> Path:
    ''' toolkit.yaml is always read from the same folder as the config it goes with '''
    return (config_path or default_config_path()).parent / TOOLKIT_NAME


def cloudflared_dir() -> Path:
    return home_dir() / 'cloudflared'


def expand(value: str, environ: dict[str, str] | None = None) -> str:
    ''' replace ${VAR} with its value; an unset variable is an error naming only the variable

    values are normally written directly in config.toml; this is an optional escape hatch
    '''
    environ = os.environ if environ is None else environ

    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in environ:
            raise ConfigError(f'environment variable {name} is not set')
        return environ[name]

    return _ENV_REF.sub(sub, value)


@dataclass(frozen=True)
class ServerConfig:
    ''' one stdio server as written in config.toml; values are NOT expanded yet '''
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
class TunnelConfig:
    ''' a named cloudflare tunnel, run by the tray next to the gateway '''
    name: str
    command: str = DEFAULT_CLOUDFLARED
    enabled: bool = True
    # '' means the one credentials file in ~/.claudeplay/cloudflared
    credentials_file: str = ''


@dataclass(frozen=True)
class TasksConfig:
    ''' account-specific task lists: name to id for the common ones, and the names of the main lists, which tasks_get_due_today and tasks_get_completed_between use '''
    common_lists: dict[str, str] = field(default_factory=dict)
    due_today: tuple[str, ...] = ()


@dataclass(frozen=True)
class GatewayConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    public_base_url: str = ''
    servers: tuple[ServerConfig, ...] = ()
    auth: AuthConfig | None = None
    tunnel: TunnelConfig | None = None
    tasks: TasksConfig = field(default_factory=TasksConfig)
    # local use only: serve without authentication when there is no auth section
    insecure_no_auth: bool = False

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f'http://localhost:{self.port}').rstrip('/')

    @property
    def endpoint_url(self) -> str:
        return f'{self.base_url}/mcp'

    @property
    def public_host(self) -> str:
        ''' the hostname requests arrive with through the tunnel, or '' for local use '''
        return urlsplit(self.public_base_url).hostname or ''

    @property
    def tunnel_enabled(self) -> bool:
        return self.tunnel is not None and self.tunnel.enabled

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


class _Model(BaseModel):
    ''' a config section: unknown keys and wrong types are errors, so a typo fails instead of being ignored '''
    model_config = ConfigDict(extra='forbid', strict=True)


class _GatewayModel(_Model):
    host: str = DEFAULT_HOST
    port: int = Field(DEFAULT_PORT, ge=1, le=65535)
    public_base_url: str = ''
    insecure_no_auth: bool = False


class _AuthModel(_Model):
    client_id: str = ''
    client_secret: str = ''
    jwt_signing_key: str = ''
    allowed_user_ids: list[int] = []


class _TunnelModel(_Model):
    name: str = Field(min_length=1)
    command: str = Field(DEFAULT_CLOUDFLARED, min_length=1)
    enabled: bool = True
    credentials_file: str = ''


class _ServerModel(_Model):
    command: str = Field(min_length=1)
    args: list[str] = []
    env: dict[str, str] = {}
    enabled: bool = True


class _TasksModel(_Model):
    common_lists: dict[str, str] = {}
    due_today: list[str] = []


class _ConfigModel(_Model):
    gateway: _GatewayModel = _GatewayModel()
    auth: _AuthModel | None = None
    tunnel: _TunnelModel | None = None
    servers: dict[str, _ServerModel] = {}
    tasks: _TasksModel = _TasksModel()


def _yaml() -> YAML:
    ''' a round-trip parser: edits keep comments, key order and quoting '''
    yaml = YAML(typ='rt')
    yaml.preserve_quotes = True
    # never re-wrap long values
    yaml.width = 1 << 20
    return yaml


def load_yaml(text: str, name: str) -> Any:
    ''' parse yaml text; a syntax error names the file and line, never the text (it may hold secrets) '''
    try:
        return _yaml().load(text)
    except YAMLError as e:
        mark = getattr(e, 'problem_mark', None)
        where = f' line {mark.line + 1}' if mark is not None else ''
        raise ConfigError(f'{name}:{where}: invalid yaml ({getattr(e, "problem", None) or "syntax error"})') from None


def validation_error(name: str, e: ValidationError) -> ConfigError:
    ''' one line per problem: file, key path and what is wrong; pydantic's input values are left out '''
    lines = []
    for err in e.errors(include_url=False, include_context=False, include_input=False):
        path = '.'.join(str(p) for p in err['loc']) or '(top level)'
        lines.append(f'{name}: {path}: {err["msg"]}')
    return ConfigError('\n'.join(lines))


def parse(text: str, name: str = CONFIG_NAME) -> GatewayConfig:
    raw = load_yaml(text, name)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f'{name}: the top level must be a mapping')
    try:
        model = _ConfigModel.model_validate(raw)
    except ValidationError as e:
        raise validation_error(name, e) from None

    tasks = model.tasks
    unknown = [n for n in tasks.due_today if n not in tasks.common_lists]
    if unknown:
        raise ConfigError(f'{name}: tasks.due_today: names lists missing from common_lists: {", ".join(unknown)}')
    return GatewayConfig(
        host=model.gateway.host,
        port=model.gateway.port,
        public_base_url=model.gateway.public_base_url,
        insecure_no_auth=model.gateway.insecure_no_auth,
        servers=tuple(
            ServerConfig(name=n, command=m.command, args=tuple(m.args), env=dict(m.env), enabled=m.enabled)
            for n, m in model.servers.items()
        ),
        auth=None if model.auth is None else AuthConfig(
            client_id=model.auth.client_id,
            client_secret=model.auth.client_secret,
            jwt_signing_key=model.auth.jwt_signing_key,
            allowed_user_ids=tuple(model.auth.allowed_user_ids),
        ),
        tunnel=None if model.tunnel is None else TunnelConfig(
            name=model.tunnel.name,
            command=model.tunnel.command,
            enabled=model.tunnel.enabled,
            credentials_file=model.tunnel.credentials_file,
        ),
        tasks=TasksConfig(common_lists=dict(tasks.common_lists), due_today=tuple(tasks.due_today)),
    )


def load(path: Path | None = None) -> GatewayConfig:
    path = path or default_config_path()
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise ConfigError(f'config not found: {path}') from None
    return parse(text, path.name)


def _edit(path: Path, change) -> None:
    ''' apply change(document) to the config file, keeping its comments, formatting and line endings '''
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    newline = '\r\n' if '\r\n' in text else '\n'
    doc = load_yaml(text.replace('\r\n', '\n'), path.name)
    if doc is None:
        doc = {}
    change(doc)
    out = io.StringIO()
    _yaml().dump(doc, out)
    tmp = path.with_suffix('.tmp')
    # write the file back with the line endings it had
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(out.getvalue().replace('\n', newline))
    os.replace(tmp, path)


def _set_value(mapping, key: str, value: bool) -> None:
    ''' set a scalar and keep its end-of-line comment where it was, relative to the value '''
    old = mapping.get(key)
    mapping[key] = value
    comment = getattr(mapping, 'ca', None) and mapping.ca.items.get(key)
    if comment and len(comment) > 2 and comment[2] is not None and isinstance(old, bool):
        # ruamel pins a comment to its column, so a longer or shorter value would shift it
        comment[2].column += len(str(value).lower()) - len(str(old).lower())


def set_enabled(path: Path, name: str, enabled: bool) -> None:
    ''' flip a server's enabled flag in the config file (used by the tray toggles) '''
    def change(doc):
        servers = doc.get('servers') or {}
        if name not in servers:
            raise ConfigError(f'server {name} is not in the config')
        _set_value(servers[name], 'enabled', enabled)
    _edit(path, change)


def ensure_signing_key(path: Path) -> bool:
    ''' write a random jwt_signing_key into the auth section if it is missing or empty; returns True if one was written '''
    written = False

    def change(doc):
        nonlocal written
        auth = doc.get('auth')
        if auth is None or auth.get('jwt_signing_key'):
            return
        auth['jwt_signing_key'] = secrets.token_urlsafe(48)
        written = True

    _edit(path, change)
    return written


def tunnel_credentials(tunnel: TunnelConfig) -> Path:
    ''' the tunnel credentials file: the configured one, else the only .json in ~/.claudeplay/cloudflared '''
    if tunnel.credentials_file:
        path = Path(expand(tunnel.credentials_file))
        if not path.is_file():
            raise ConfigError('tunnel: credentials_file does not exist')
        return path
    found = sorted(cloudflared_dir().glob('*.json'))
    if not found:
        raise ConfigError(f'tunnel: no credentials file (<tunnel-id>.json) in {cloudflared_dir()}')
    if len(found) > 1:
        raise ConfigError(f'tunnel: more than one .json in {cloudflared_dir()}; set tunnel.credentials_file')
    return found[0]


def tunnel_id(credentials: Path) -> str:
    ''' the tunnel's uuid: the file's name if it is one (cloudflared names it that), else its TunnelID field '''
    try:
        return str(uuid.UUID(credentials.stem))
    except ValueError:
        pass
    try:
        found = json.loads(credentials.read_text(encoding='utf-8'))['TunnelID']
        return str(uuid.UUID(str(found)))
    except (OSError, ValueError, KeyError, TypeError):
        raise ConfigError('tunnel: cannot find the tunnel id in the credentials file') from None


MASK = '********'


def describe(cfg: GatewayConfig) -> list[str]:
    ''' the effective config as text, with every secret masked, safe to paste when debugging '''
    lines = [f'endpoint: {cfg.endpoint_url}', f'listen:   {cfg.host}:{cfg.port}']
    if cfg.auth is None:
        lines.append('auth:     NONE (insecure_no_auth, local use only)' if cfg.insecure_no_auth else 'auth:     none')
    else:
        lines.append(f'auth:     github client {cfg.auth.client_id or "(missing)"}, allowed ids {list(cfg.auth.allowed_user_ids)}')
        lines.append(f'          client secret {MASK if cfg.auth.client_secret else "(missing)"}, '
                     f'signing key {MASK if cfg.auth.jwt_signing_key else "(missing)"}')
    if cfg.tunnel is None:
        lines.append('tunnel:   none (local only)')
    else:
        lines.append(f'tunnel:   {cfg.tunnel.name} {"enabled" if cfg.tunnel.enabled else "disabled"}, {cfg.tunnel.command}')
        lines.append(f'          credentials {cfg.tunnel.credentials_file or str(cloudflared_dir()) + " (default)"}')
    if cfg.tasks.common_lists:
        lines.append(f'tasks:    common lists {", ".join(cfg.tasks.common_lists)}; due today {", ".join(cfg.tasks.due_today) or "(off)"}')
    for s in cfg.servers:
        lines.append(f'server {s.name}: {"enabled" if s.enabled else "disabled"}')
        lines.append(f'  command {s.command}')
        if s.args:
            lines.append(f'  args    {list(s.args)}')
        # env values are where credentials live, so only their names are shown
        if s.env:
            lines.append(f'  env     {", ".join(f"{k}={MASK}" for k in s.env)}')
    return lines
