# claudeplay

Windows tray app exposing local stdio MCP servers as one claude.ai connector. Read [plan.md](plan.md) first: it is the source of truth for decisions, phases and verified API behaviour. Settled decisions (one gateway and endpoint, GitHub OAuth via FastMCP's proxy with a numeric-id allow-list, Cloudflare Tunnel on example.net, runs at logon, uv tool, pystray, own `gateway.toml`, todo-mcp untouched) are not up for re-litigation.

## Structure

```
src/claudeplay/
  config.py      gateway.toml parsing, ${ENV_VAR} expansion, data-dir paths, tray overrides
  gateway.py     fastmcp gateway: one create_proxy provider per server, status board, tool-call logging
  auth.py        OAuthProxy fronting github, AllowListVerifier, encrypted token store
  supervisor.py  runs the gateway as a child process; state from status.json
  tray.py        pystray menu and icon
  autostart.py   Startup-folder shortcut
  winutil.py     mutex, port owner, clipboard, kill-on-close job
  logs.py        rotating file logging
  cli.py         argparse subcommands
tests/           pytest; tests/fake_server.py is a stdio backend
```

## Commands

```bash
~/.local/bin/uv.exe run --extra test pytest     # about 80s: tests spawn real gateways
~/.local/bin/uv.exe run claudeplay check
```

uv is not on PATH. Commit messages are single-line lowercase with no co-author trailer; pass `-c user.name -c user.email` (no global git config).

## Gotchas learned the hard way

- **`mode='legacy'` is required** on every `create_proxy`/`Client` that talks to a backend. fastmcp 4 defaults to a `server/discover` handshake that the mcp 1.x backends reject, and the proxy then lists zero tools silently.
- **Mount per server** with `add_provider(proxy, namespace=name)`. A multi-server `mcpServers` config only prefixes tools when there is more than one server.
- The proxy **swallows backend startup errors** and lists nothing, so the probe treats zero tools as failed.
- **uv venv `python.exe` is a launcher**: the pid from `Popen` is not the interpreter's pid. The supervisor matches status files by `CLAUDEPLAY_RUN_ID`, not pid, and stops with `taskkill /T`.
- Python text-mode writes on Windows produce CRLF. The repo is LF; use the Write/Edit tools or `newline=''`.
- `uvicorn.access` is disabled because it would log OAuth callback query strings.
- Never log arguments, results, tokens or expanded env values. Error messages name the variable, not its value.
- pystray inspects callback arity: no default-arg lambdas in menu items.

## Conventions

Same as obsidian-mcp: lowercase comments and log messages, `''' docstrings '''`, single quotes, type hints.
