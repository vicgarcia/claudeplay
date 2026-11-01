'''the gateway: one fastmcp server that mounts each enabled stdio server under its name'''

import asyncio
import json
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware, MiddlewareContext

from . import config, toolkit

log = logging.getLogger('claudeplay.gateway')

PROBE_TIMEOUT = 30.0

# states a single server can be in
DISABLED = 'disabled'
STARTING = 'starting'
OK = 'ok'
FAILED = 'failed'


@dataclass
class ServerStatus:
    name: str
    state: str
    error: str = ''
    tools: int | None = None


class StatusBoard:
    ''' per-server status, mirrored to status.json so the tray can read it without a network call '''

    def __init__(self, path: Path | None, url: str = ''):
        self.path = path
        self.url = url
        self.state = STARTING
        self.servers: dict[str, ServerStatus] = {}

    def set(self, name: str, state: str, error: str = '', tools: int | None = None) -> None:
        self.servers[name] = ServerStatus(name, state, error, tools)
        self.flush()

    def overall(self) -> str:
        ''' running when every enabled server is ok, degraded when any failed, starting while probing '''
        states = [s.state for s in self.servers.values() if s.state != DISABLED]
        if self.state == 'stopped':
            return 'stopped'
        if any(s == STARTING for s in states):
            return STARTING
        if any(s == FAILED for s in states):
            return 'degraded'
        return 'running'

    def stop(self) -> None:
        self.state = 'stopped'
        self.flush()

    def snapshot(self) -> dict[str, Any]:
        return {
            'pid': os.getpid(),
            # set by the supervisor so it can tell this run from a stale file (a venv launcher's pid differs)
            'run_id': os.environ.get('CLAUDEPLAY_RUN_ID', ''),
            'state': self.overall(),
            'url': self.url,
            'updated': time.time(),
            'servers': {n: asdict(s) for n, s in self.servers.items()},
        }

    def flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.snapshot(), indent=2), encoding='utf-8')
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning('could not write status file: %s', type(e).__name__)


def read_status(path: Path | None = None) -> dict[str, Any] | None:
    ''' the last status snapshot, or None if there is none or it is unreadable '''
    try:
        return json.loads((path or config.status_path()).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


class ToolLogMiddleware(Middleware):
    ''' logs tool name and timing only; arguments and results can hold vault content or secrets '''

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        name = context.message.name
        start = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as e:
            ms = (time.perf_counter() - start) * 1000
            log.info('tool=%s ms=%.0f result=error type=%s', name, ms, type(e).__name__)
            raise
        ms = (time.perf_counter() - start) * 1000
        log.info('tool=%s ms=%.0f result=ok', name, ms)
        return result


def _check_command(command: str) -> None:
    if shutil.which(command) is None:
        raise config.ConfigError('command not found')


def _mount(gw: FastMCP, server: config.ResolvedServer) -> FastMCP:
    ''' proxy one stdio server and mount it under its name (tools become <name>_<tool>) '''
    transport = StdioTransport(command=server.command, args=server.args, env=server.env or None)
    # the backends run the mcp 1.x sdk, which rejects fastmcp 4's default server/discover handshake
    proxy = create_proxy(transport, name=server.name, mode='legacy')
    gw.add_provider(proxy, namespace=server.name)
    return proxy


async def _probe(name: str, proxy: FastMCP, board: StatusBoard) -> None:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with Client(proxy, mode='legacy') as client:
                tools = await client.list_tools()
    except Exception as e:
        # exception class only: messages can echo command lines
        log.warning('server %s failed to start: %s', name, type(e).__name__)
        board.set(name, FAILED, f'failed to start ({type(e).__name__})')
        return
    if not tools:
        # the proxy swallows backend errors and lists nothing, so an empty list means it never came up
        log.warning('server %s exposed no tools', name)
        board.set(name, FAILED, 'started but exposed no tools')
        return
    log.info('server %s ok, %d tools', name, len(tools))
    board.set(name, OK, tools=len(tools))


def build(
    cfg: config.GatewayConfig,
    board: StatusBoard | None = None,
    auth: Any = None,
    extra_middleware: tuple[Middleware, ...] = (),
    environ: dict[str, str] | None = None,
    raw: bool = False,
) -> tuple[FastMCP, StatusBoard]:
    ''' build the gateway; a server that cannot be set up is marked failed and the rest still serve

    by default only the curated toolkit is visible; raw=True exposes every backend tool as <server>_<tool>
    '''
    board = board or StatusBoard(None, cfg.endpoint_url)
    proxies: dict[str, FastMCP] = {}

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        tasks = [asyncio.create_task(_probe(n, p, board)) for n, p in proxies.items()]
        try:
            yield {}
        finally:
            for t in tasks:
                t.cancel()
            board.stop()

    gw = FastMCP(
        toolkit.NAME,
        instructions=toolkit.instructions(cfg.tasks),
        auth=auth,
        lifespan=lifespan,
        middleware=[*extra_middleware, ToolLogMiddleware()],
    )
    if not raw:
        gw.add_transform(toolkit.Catalog(toolkit.catalog(cfg.tasks)))

    for server in cfg.servers:
        if not server.enabled:
            board.set(server.name, DISABLED)
            continue
        try:
            resolved = config.resolve(server, environ)
            _check_command(resolved.command)
            proxies[server.name] = _mount(gw, resolved)
        except config.ConfigError as e:
            log.warning('server %s not started: %s', server.name, e)
            board.set(server.name, FAILED, str(e))
            continue
        board.set(server.name, STARTING)
    board.flush()
    return gw, board


def serve(cfg: config.GatewayConfig, auth: Any = None, extra_middleware: tuple[Middleware, ...] = (), raw: bool = False) -> None:
    ''' run the gateway on the configured host and port until the process is stopped '''
    board = StatusBoard(config.status_path(), cfg.endpoint_url)
    gw, board = build(cfg, board=board, auth=auth, extra_middleware=extra_middleware, raw=raw)
    log.info('gateway starting on %s:%d', cfg.host, cfg.port)
    # fastmcp leaves Host/Origin checks off by default. with them on, only localhost and the tunnel's
    # hostname get through. the origin is listed because the tunnel reaches us over plain http, so
    # fastmcp's same-origin fallback would not match a browser's https origin on the login pages
    public = bool(cfg.public_host)
    try:
        gw.run(
            transport='http',
            host=cfg.host,
            port=cfg.port,
            show_banner=False,
            host_origin_protection=True,
            allowed_hosts=[cfg.public_host] if public else None,
            allowed_origins=[cfg.base_url] if public else None,
            uvicorn_config={'access_log': False},
        )
    finally:
        board.stop()
