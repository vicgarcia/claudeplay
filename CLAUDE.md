# claudeplay

Windows tray app exposing local stdio MCP servers as one claude.ai connector. [docs/](docs/README.md) describes how it works now; update it when behaviour changes, and keep real hostnames and ids out of it. Settled decisions (one gateway and endpoint, GitHub OAuth via FastMCP's proxy with a numeric-id allow-list, Cloudflare Tunnel on the user's own domain, runs at logon, uv tool, pystray, two YAML files in `~/.claudeplay` with logs in `%LOCALAPPDATA%\claudeplay\logs`, backend text passed through by default) are not up for re-litigation.

Two goals pull in the same direction: a claudeplay that anyone can run over their own MCP servers, and the author's own config and install. So the code holds no knowledge of any particular server: anything about obsidian, pinboard or windows lives in `toolkit.yaml` or in the backend's repo.

## Structure

```
src/claudeplay/
  config.py      config.yaml: pydantic validation (unknown keys are errors), in-place edits (ruamel.yaml round trip), masked describe, optional ${ENV_VAR}, paths (home_dir, logs_dir)
  gateway.py     fastmcp gateway: one create_proxy provider per server, probe + toolkit check, status board, tool-call logging
  toolkit.py     toolkit.yaml: loader and validation, Entry, Catalog transform (passthrough by default), instructions assembly
  clock.py       the one built-in tool, get_current_timestamp, and its Entry
  auth.py        OAuthProxy fronting github, AllowListVerifier, encrypted token store
  supervisor.py  runs the gateway and the cloudflared tunnel as child processes; state from status.json
  tray.py        pystray menu and icon
  autostart.py   Startup-folder shortcut
  winutil.py     mutex, port owner, clipboard, kill-on-close job
  logs.py        rotating file logging
  cli.py         argparse subcommands
tests/           pytest; tests/fake_*.py are stdio backends
config.example.yaml, toolkit.example.yaml    the shipped examples (tests parse them)
```

## Commands

```bash
uv run --extra test python -m pytest     # about 3 minutes: tests spawn real gateways
uv run python -m claudeplay check
```

Commit messages are single-line lowercase.

## The toolkit

Claude sees only what `toolkit.yaml` exposes (plus the built-in clock). A listed tool passes through as its backend defines it: name, description, argument docs, annotations, and the backend's own server instructions (read in the probe and set on the gateway after it, since they're unknown when it is built). `toolkit.yaml` changes only what it sets: `name`, `description`, `description_append`, `args`, `hide`, `fixed`, `defaults`, annotations, `instructions`, `instructions_append`, and `expose_all` for a server whose tools should all be exposed unchanged. To add a tool, list it; put real logic in the backend repo, not here, and don't rename tools of a backend whose own text names them. `claudeplay serve --raw` exposes every backend tool for debugging.

Both files are strict: unknown keys fail, and errors name the file and key path, never a value. The probe marks a server `failed` when `toolkit.yaml` names a tool or argument it doesn't have.

## Gotchas learned the hard way

- **`mode='legacy'` is required** on every `create_proxy`/`Client` that talks to a backend. fastmcp 4 defaults to a `server/discover` handshake that the mcp 1.x backends reject, and the proxy then lists zero tools silently.
- **Mount per server** with `add_provider(proxy, namespace=name)`. A multi-server `mcpServers` config only prefixes tools when there is more than one server. Tools are `<server>_<tool>` inside the gateway; the toolkit strips the prefix for Claude.
- The proxy **swallows backend startup errors** and lists nothing, so the probe treats zero tools as failed.
- **uv venv `python.exe` is a launcher**: the pid from `Popen` is not the interpreter's pid. The supervisor matches status files by `CLAUDEPLAY_RUN_ID`, not pid, and stops with `taskkill /T`.
- Python text-mode writes on Windows produce CRLF. The repo is LF; use the Write/Edit tools or `newline=''`.
- **YAML, not TOML:** edits use ruamel.yaml in round-trip mode. It pins a trailing comment to its column, so `set_enabled` shifts the comment when the value's length changes, keeping a toggle byte-for-byte. `${NAME}` inside a flow list (`[a, ${X}]`) must be quoted.
- **Quiet errors:** yaml syntax errors and pydantic errors are reported without the text or values (a duplicate-key message would quote both), and `check_backend` problems name tools and arguments only.
- **cloudflared runs by tunnel id** with `--credentials-file`, which needs no `cert.pem`; its output goes to `cloudflared.log` through our own file handle, rotated at tunnel start.
- `uvicorn.access` is disabled because it would log OAuth callback query strings.
- Never log arguments, results, tokens or expanded env values. Error messages name the variable, not its value. Don't print config files, the oauth store or the tunnel credentials.
- pystray inspects callback arity: no default-arg lambdas in menu items.
- **Smart App Control must be off.** Everything uv installs (launchers, interpreters, `.pyd` extensions) is unsigned, so it runs only on reputation, which changes without warning; it has no per-app exceptions. Don't work around it with `python -c`/`pythonw -m` launches: run the installed `.exe` entry points. A silent failure to start shows in the `Microsoft-Windows-CodeIntegrity/Operational` event log.
- When patching files from shell scripts, backslash escapes get mangled by the tool layer; use the Edit/Write tools for anything with `\n` in it.

## Conventions

Same as obsidian-mcp: lowercase comments and log messages, `''' docstrings '''`, single quotes, type hints.
