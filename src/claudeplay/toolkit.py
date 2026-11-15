'''the claudeplay toolkit: the tool surface presented to claude, read from toolkit.yaml, over the mounted backends

by default a tool passes through exactly as its backend describes it; toolkit.yaml says which tools are exposed
and, where the backend's own text is not right for you, what to change
'''

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
    ''' one presented tool: its public name, the backend tool it calls, and what is changed about it

    anything left unset passes the backend's own text and annotations through unchanged
    '''
    name: str
    # the tool as mounted on the gateway, <server>_<backend name>
    source: str
    # replaces the backend's description; description_append is added after whichever description is used
    description: str | None = None
    description_append: str = ''
    read_only: bool | None = None
    args: dict[str, str] = field(default_factory=dict)
    # hidden backend arguments left at the backend's default; they must be optional in the backend
    hide: tuple[str, ...] = ()
    # hidden backend arguments always sent with these values
    fixed: dict[str, Any] = field(default_factory=dict)
    # visible arguments with a different default from the backend's
    defaults: dict[str, Any] = field(default_factory=dict)
    destructive: bool | None = None
    # true when the tool reaches beyond the user's own data
    open_world: bool | None = None


@dataclass(frozen=True)
class ServerToolkit:
    ''' what one server contributes: its tools, and instructions sent only while it is enabled '''
    # replaces the instructions the backend sends ('' sends none); None passes the backend's own through
    instructions: str | None = None
    instructions_append: str = ''
    # every backend tool not listed is exposed too, unchanged and under its own name
    expose_all: bool = False
    entries: tuple[Entry, ...] = ()


@dataclass(frozen=True)
class Toolkit:
    ''' the whole presented surface, in the order of toolkit.yaml '''
    instructions: str = ''
    servers: dict[str, ServerToolkit] = field(default_factory=dict)

    def entries(self, built_in: Sequence[Entry] = ()) -> tuple[Entry, ...]:
        ''' every listed tool: the built-in ones first, then each server's in file order '''
        return (*built_in, *(e for s in self.servers.values() for e in s.entries))

    def passthrough(self) -> tuple[str, ...]:
        ''' the servers whose unlisted tools are exposed too '''
        return tuple(name for name, s in self.servers.items() if s.expose_all)

    def instructions_for(self, cfg: config.GatewayConfig, backend: dict[str, str] | None = None) -> str:
        ''' the top-level instructions, then each enabled server's in config order

        a server's own are the backend's instructions (read when it was probed) unless toolkit.yaml replaces them,
        then its instructions_append. a server that exposes nothing adds nothing
        '''
        backend = backend or {}
        parts = [self.instructions]
        for server in cfg.servers:
            section = self.servers.get(server.name)
            if not server.enabled or section is None or not (section.entries or section.expose_all):
                continue
            own = backend.get(server.name, '') if section.instructions is None else section.instructions
            parts += [own, section.instructions_append]
        return '\n\n'.join(p.strip() for p in parts if p.strip())

    def counts(self) -> dict[str, int]:
        return {name: len(s.entries) for name, s in self.servers.items()}


class _EntryModel(config.Model):
    source: str = Field(min_length=1)
    name: str | None = Field(None, pattern=_NAME_PATTERN)
    description: str | None = Field(None, min_length=1)
    description_append: str = ''
    read_only: bool | None = None
    destructive: bool | None = None
    open_world: bool | None = None
    args: dict[str, str] = {}
    hide: list[str] = []
    fixed: dict[str, Any] = {}
    defaults: dict[str, Any] = {}


class _ServerModel(config.Model):
    instructions: str | None = None
    instructions_append: str = ''
    expose_all: bool = False
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
                description_append=entry.description_append,
                read_only=entry.read_only,
                args=dict(entry.args),
                hide=tuple(entry.hide),
                fixed=dict(entry.fixed),
                defaults=dict(entry.defaults),
                destructive=entry.destructive,
                open_world=entry.open_world,
            ))
        servers[server_name] = ServerToolkit(
            instructions=server.instructions,
            instructions_append=server.instructions_append,
            expose_all=server.expose_all,
            entries=tuple(entries),
        )

    for server in cfg.servers:
        section = servers.get(server.name)
        if section is None or not (section.entries or section.expose_all):
            log.warning('server %s has no tools listed in %s (and no expose_all), so it exposes nothing', server.name, name)
    return Toolkit(instructions=model.instructions, servers=servers)


def load(config_path: Path | None, cfg: config.GatewayConfig, built_in: Sequence[Entry] = ()) -> Toolkit:
    ''' read the toolkit.yaml that sits next to the config file '''
    path = config.toolkit_path(config_path)
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise config.ConfigError(f'toolkit not found: {path}') from None
    return parse(text, cfg, built_in, path.name)


def check_backend(server: str, tools: Sequence[Any], entries: Sequence[Entry], expose_all: bool = False, taken: Sequence[str] = ()) -> list[str]:
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
    if expose_all:
        # an unlisted tool is exposed under its own name, which must not be one already in use
        listed = {e.source.removeprefix(prefix) for e in entries}
        for tool in tools:
            if tool.name not in listed and tool.name in taken:
                problems.append(f'{tool.name}: backend tool is exposed under a name already used by another tool')
    return problems


def _annotations(entry: Entry, backend: ToolAnnotations | None) -> ToolAnnotations | None:
    ''' the backend's annotations with whatever toolkit.yaml sets on top; none at all if neither says anything '''
    def pick(mine: bool | None, theirs: str) -> bool | None:
        return mine if mine is not None else getattr(backend, theirs, None)

    values = {
        'read_only_hint': pick(entry.read_only, 'read_only_hint'),
        'destructive_hint': pick(entry.destructive, 'destructive_hint'),
        'open_world_hint': pick(entry.open_world, 'open_world_hint'),
        'idempotent_hint': getattr(backend, 'idempotent_hint', None),
    }
    if backend is None and all(v is None for v in values.values()):
        return None
    title = getattr(backend, 'title', None) or entry.name.replace('_', ' ')
    return ToolAnnotations(title=title, **values)


class Catalog(Transform):
    ''' exposes the listed tools, and every tool of an expose_all server, with the changes toolkit.yaml lists;
    everything else, including prompts and resources, is hidden '''

    def __init__(self, entries: Sequence[Entry], passthrough: Sequence[str] = ()):
        names = [e.name for e in entries]
        if len(set(names)) != len(names):
            raise ValueError('duplicate tool names in catalog')
        # one backend tool can sit behind several entries
        self._by_source: dict[str, list[Entry]] = {}
        for entry in entries:
            self._by_source.setdefault(entry.source, []).append(entry)
        self._by_name = {e.name: e for e in entries}
        self._passthrough = tuple(passthrough)

    def _present(self, tool: Tool, entry: Entry) -> Tool:
        # only describe arguments the backend actually has; the gateway reports the rest when it probes the server
        known = set(tool.parameters.get('properties', {}))
        defaults = {a: {'default': v} for a, v in entry.defaults.items()}
        transforms = {a: ArgTransform(description=d, **defaults.get(a, {})) for a, d in entry.args.items() if a in known}
        transforms |= {a: ArgTransform(hide=True) for a in entry.hide if a in known}
        transforms |= {a: ArgTransform(hide=True, default=v) for a, v in entry.fixed.items() if a in known}
        # a default for an argument with no description of its own still has to reach the schema
        transforms |= {a: ArgTransform(default=v) for a, v in entry.defaults.items() if a in known and a not in transforms}
        description = entry.description if entry.description is not None else tool.description
        if entry.description_append:
            description = f'{description or ""}\n\n{entry.description_append}'.strip()
        return Tool.from_tool(
            tool,
            name=entry.name,
            description=description,
            annotations=_annotations(entry, tool.annotations),
            transform_args=transforms,
        )

    def _passthrough_entry(self, source: str) -> Entry | None:
        ''' the unchanged entry for a tool of an expose_all server, unless it is listed under some name already '''
        if source in self._by_source:
            return None
        for server in self._passthrough:
            if source.startswith(f'{server}_'):
                return Entry(name=source.removeprefix(f'{server}_'), source=source)
        return None

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        presented = [self._present(t, e) for t in tools for e in self._by_source.get(t.name, ())]
        order = {e.name: i for i, e in enumerate(self._by_name.values())}
        presented.sort(key=lambda t: order[t.name])
        taken = {t.name for t in presented}
        for tool in tools:
            entry = self._passthrough_entry(tool.name)
            if entry is None:
                continue
            if entry.name in taken:
                log.warning('tool %s of an expose_all server is hidden: its name is already used', entry.name)
                continue
            taken.add(entry.name)
            presented.append(self._present(tool, entry))
        return presented

    async def get_tool(self, name: str, call_next: GetToolNext, *, version=None) -> Tool | None:
        entry = self._by_name.get(name)
        if entry is not None:
            tool = await call_next(entry.source, version=version)
            return self._present(tool, entry) if tool is not None else None
        for server in self._passthrough:
            passthrough = self._passthrough_entry(f'{server}_{name}')
            tool = await call_next(passthrough.source, version=version) if passthrough else None
            if tool is not None:
                return self._present(tool, passthrough)
        return None

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
