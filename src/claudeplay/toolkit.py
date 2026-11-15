'''the claudeplay toolkit: the tool surface presented to claude, read from toolkit.yaml, over the mounted backends'''

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp.server.transforms import GetToolNext, Transform
from fastmcp.tools import Tool
from fastmcp.tools.tool_transform import ArgTransform
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from . import config

log = logging.getLogger('claudeplay.toolkit')

NAME = 'claudeplay'

# claude's rule for a tool name
_NAME_PATTERN = r'^[A-Za-z0-9_-]{1,64}$'


@dataclass(frozen=True)
class Entry:
    ''' one presented tool: its public name, the backend tool it calls, and how it is described '''
    name: str
    # the tool as mounted on the gateway, <server>_<backend name>
    source: str
    description: str
    read_only: bool = False
    args: dict[str, str] = field(default_factory=dict)
    # hidden backend arguments left at the backend's default; they must be optional in the backend
    hide: tuple[str, ...] = ()
    # hidden backend arguments always sent with these values
    fixed: dict[str, Any] = field(default_factory=dict)
    # visible arguments with a different default from the backend's
    defaults: dict[str, Any] = field(default_factory=dict)
    destructive: bool = False
    # true when the tool reaches beyond the user's own data
    open_world: bool = False


@dataclass(frozen=True)
class ServerToolkit:
    ''' what one server contributes: its tools, and instructions sent only while it is enabled '''
    instructions: str = ''
    entries: tuple[Entry, ...] = ()


@dataclass(frozen=True)
class Toolkit:
    ''' the whole presented surface, in the order of toolkit.yaml '''
    instructions: str = ''
    servers: dict[str, ServerToolkit] = field(default_factory=dict)

    def entries(self, built_in: Sequence[Entry] = ()) -> tuple[Entry, ...]:
        ''' every presented tool: the built-in ones first, then each server's in file order '''
        return (*built_in, *(e for s in self.servers.values() for e in s.entries))

    def instructions_for(self, cfg: config.GatewayConfig) -> str:
        ''' the top-level instructions, then those of each enabled server in config order '''
        parts = [self.instructions]
        for server in cfg.servers:
            if server.enabled and server.name in self.servers:
                parts.append(self.servers[server.name].instructions)
        return '\n\n'.join(p.strip() for p in parts if p.strip())

    def counts(self) -> dict[str, int]:
        return {name: len(s.entries) for name, s in self.servers.items()}


class _EntryModel(config.Model):
    source: str = Field(min_length=1)
    name: str | None = Field(None, pattern=_NAME_PATTERN)
    description: str = Field(min_length=1)
    read_only: bool = False
    destructive: bool = False
    open_world: bool = False
    args: dict[str, str] = {}
    hide: list[str] = []
    fixed: dict[str, Any] = {}
    defaults: dict[str, Any] = {}


class _ServerModel(config.Model):
    instructions: str = ''
    tools: list[_EntryModel] = []


class _ToolkitModel(config.Model):
    instructions: str = ''
    servers: dict[str, _ServerModel] = {}


def parse(text: str, cfg: config.GatewayConfig, built_in: Sequence[Entry] = (), name: str = config.TOOLKIT_NAME) -> Toolkit:
    ''' parse toolkit.yaml text and check it against the config it goes with; errors name keys, never values '''
    raw = config.load_yaml(text, name, safe=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise config.ConfigError(f'{name}: the top level must be a mapping')
    try:
        model = _ToolkitModel.model_validate(raw)
    except ValidationError as e:
        raise config.validation_error(name, e) from None

    configured = {s.name for s in cfg.servers}
    unknown = [n for n in model.servers if n not in configured]
    if unknown:
        raise config.ConfigError(f'{name}: servers.{unknown[0]}: not a server in config.yaml')

    servers: dict[str, ServerToolkit] = {}
    owner = {e.name: 'the built-in tools' for e in built_in}
    for server_name, server in model.servers.items():
        entries = []
        for i, entry in enumerate(server.tools):
            public = entry.name or entry.source
            if public in owner:
                raise config.ConfigError(f'{name}: servers.{server_name}.tools.{i}: the name {public} is already used by {owner[public]}')
            owner[public] = f'servers.{server_name}'
            entries.append(Entry(
                name=public,
                source=f'{server_name}_{entry.source}',
                description=entry.description,
                read_only=entry.read_only,
                args=dict(entry.args),
                hide=tuple(entry.hide),
                fixed=dict(entry.fixed),
                defaults=dict(entry.defaults),
                destructive=entry.destructive,
                open_world=entry.open_world,
            ))
        servers[server_name] = ServerToolkit(instructions=server.instructions, entries=tuple(entries))

    for server in cfg.servers:
        if server.name not in servers:
            log.warning('server %s has no section in %s, so it exposes nothing', server.name, name)
    return Toolkit(instructions=model.instructions, servers=servers)


def load(config_path: Path | None, cfg: config.GatewayConfig, built_in: Sequence[Entry] = ()) -> Toolkit:
    ''' read the toolkit.yaml that sits next to the config file '''
    path = config.toolkit_path(config_path)
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise config.ConfigError(f'toolkit not found: {path}') from None
    return parse(text, cfg, built_in, path.name)


def check_backend(server: str, tools: Sequence[Any], entries: Sequence[Entry]) -> list[str]:
    ''' problems between a server's entries and the tools it actually lists, naming tools and arguments only

    a renamed backend tool, or an argument it no longer takes, would otherwise disappear without a word
    '''
    by_name = {t.name: t for t in tools}
    prefix = f'{server}_'
    problems = []
    for entry in entries:
        source = entry.source.removeprefix(prefix)
        tool = by_name.get(source)
        if tool is None:
            problems.append(f'{entry.name}: backend tool {source} not found')
            continue
        known = set((tool.input_schema or {}).get('properties', {}))
        for kind, keys in (('args', entry.args), ('hide', entry.hide), ('fixed', entry.fixed), ('defaults', entry.defaults)):
            for key in keys:
                if key not in known:
                    problems.append(f'{entry.name}: {kind} names {key}, which {source} does not take')
    return problems


def _annotations(entry: Entry) -> ToolAnnotations:
    return ToolAnnotations(
        title=entry.name.replace('_', ' '),
        read_only_hint=entry.read_only,
        destructive_hint=entry.destructive,
        open_world_hint=entry.open_world,
    )


class Catalog(Transform):
    ''' exposes only the listed tools, renamed and re-described; everything else, including prompts and resources, is hidden '''

    def __init__(self, entries: Sequence[Entry]):
        names = [e.name for e in entries]
        if len(set(names)) != len(names):
            raise ValueError('duplicate tool names in catalog')
        # one backend tool can sit behind several entries
        self._by_source: dict[str, list[Entry]] = {}
        for entry in entries:
            self._by_source.setdefault(entry.source, []).append(entry)
        self._by_name = {e.name: e for e in entries}

    def _present(self, tool: Tool, entry: Entry) -> Tool:
        # only describe arguments the backend actually has; the gateway reports the rest when it probes the server
        known = set(tool.parameters.get('properties', {}))
        defaults = {a: {'default': v} for a, v in entry.defaults.items()}
        transforms = {a: ArgTransform(description=d, **defaults.get(a, {})) for a, d in entry.args.items() if a in known}
        transforms |= {a: ArgTransform(hide=True) for a in entry.hide if a in known}
        transforms |= {a: ArgTransform(hide=True, default=v) for a, v in entry.fixed.items() if a in known}
        return Tool.from_tool(
            tool,
            name=entry.name,
            description=entry.description,
            annotations=_annotations(entry),
            transform_args=transforms,
        )

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        presented = [self._present(t, e) for t in tools for e in self._by_source.get(t.name, ())]
        order = {e.name: i for i, e in enumerate(self._by_name.values())}
        return sorted(presented, key=lambda t: order[t.name])

    async def get_tool(self, name: str, call_next: GetToolNext, *, version=None) -> Tool | None:
        entry = self._by_name.get(name)
        if entry is None:
            return None
        tool = await call_next(entry.source, version=version)
        return self._present(tool, entry) if tool is not None else None

    async def list_resources(self, resources):
        return []

    async def get_resource(self, uri, call_next, *, version=None):
        return None

    async def list_resource_templates(self, templates):
        return []

    async def get_resource_template(self, uri, call_next, *, version=None):
        return None

    async def list_prompts(self, prompts):
        return []

    async def get_prompt(self, name, call_next, *, version=None):
        return None
