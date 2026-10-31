# claudeplay

A Windows system-tray app that exposes local stdio MCP servers (obsidian-mcp, todo-mcp, pinboard-mcp) as **one** custom connector on claude.ai, so they work from the Claude iPhone app and voice mode.

One gateway, one endpoint, one login. Auth is GitHub OAuth (through FastMCP's OAuth proxy), restricted to your numeric GitHub user id. See [plan.md](plan.md) for the design and what is verified.

Status: the tray runs the gateway and a named Cloudflare tunnel together, so the connector is reachable from claude.ai behind GitHub sign-in. Add a `[tunnel]` section to the config to enable it; the steps are in [config.example.toml](config.example.toml). Without one, it stays local.

## Install

```powershell
uv tool install --editable .
```

This puts `claudeplay` and the windowless `claudeplay-tray` on the uv tools path.

## Configure

Everything lives in one file: `%LOCALAPPDATA%\claudeplay\config.toml` (`C:\Users\<you>\AppData\Local\claudeplay\config.toml`). It holds secrets once filled in, so it stays outside the repo; never commit or paste it. `--config <path>` or `CLAUDEPLAY_CONFIG` points at a different file.

1. Copy [config.example.toml](config.example.toml) there and set the server paths.
2. Create a GitHub OAuth App (GitHub > Settings > Developer settings > OAuth Apps > New OAuth App):

   | Field | Value |
   |---|---|
   | Application name | `claudeplay` (anything) |
   | Homepage URL | `http://localhost:8765` |
   | Authorization callback URL | `http://localhost:8765/auth/callback` |
   | Enable Device Flow | off |

   Then generate a client secret. A GitHub OAuth App holds exactly one callback URL, so when the public hostname exists you edit this field to `https://<host>/auth/callback`.
3. Find your numeric user id: open `https://api.github.com/users/<your-login>` and copy `id`. The allow-list matches this number, not the login name.
4. Fill in the values below in `config.toml`.
5. `claudeplay check` prints the effective config with every secret masked, and which servers would start.

| Setting | Needed for | Notes |
|---|---|---|
| `[auth] client_id`, `client_secret` | GitHub login | from the OAuth App |
| `[auth] allowed_user_ids` | GitHub login | your numeric id, e.g. `[123456]` |
| `[auth] jwt_signing_key` | signing tokens, encrypting the token store | generated and written into the file on first run; changing it logs out every client |
| `[servers.pinboard.env] PINBOARD_TOKEN` | pinboard | Pinboard settings > Password > API token, format `username:TOKEN` |
| `[servers.todo.env] TODO_CLIENT_ID`, `TODO_CLIENT_SECRET` | todo | Azure app id and client secret |
| `[servers.todo.env] TODO_REFRESH_TOKEN` | todo | from `todo-mcp --auth --client-id ... --client-secret ...` |

todo-mcp and pinboard-mcp read their credentials from their environment, so the gateway passes the server's `env` table to just that process and nothing secret appears on a command line. todo and pinboard ship `enabled = false`: fill in their values, then enable them from the tray's Servers menu (which edits the `enabled` line in `config.toml`, keeping your comments). pinboard-mcp checks its token against Pinboard at startup and exits if it is wrong.

Any value may instead be written as `${NAME}`, which is replaced in memory with the environment variable `NAME` when used. Nothing needs it today; it is there for later.

Environment variables for development only:

| Variable | Purpose |
|---|---|
| `CLAUDEPLAY_CONFIG` | config file to use instead of `%LOCALAPPDATA%\claudeplay\config.toml` |
| `CLAUDEPLAY_HOME` | data directory (config, logs, status, token store) instead of `%LOCALAPPDATA%\claudeplay` |
| `CLAUDEPLAY_STARTUP_DIR` | where `install` puts the shortcut (tests use this) |

## Run

| Command | What it does |
|---|---|
| `claudeplay tray` | the tray app; starts the gateway |
| `claudeplay serve` | the gateway in the foreground (`--console` to also log to the terminal) |
| `claudeplay status` | the last status report: state and per-server health |
| `claudeplay check` | the effective config with secrets masked, and what would start |
| `claudeplay install` / `uninstall` | add or remove a Startup-folder shortcut so the tray starts at logon |
| `claudeplay genkey` | print a random signing key |

The servers are separate uv tools: `uv tool install` obsidian-mcp, todo-mcp and pinboard-mcp so their `.exe` files exist in `~/.local/bin`.

`serve` and `tray` refuse to run without an `[auth]` section, unless `insecure_no_auth = true` is set under `[gateway]` (or `--insecure-no-auth` is passed). That is for local use only: it is refused unless the gateway listens on 127.0.0.1, and also while a `[tunnel]` is enabled.

The logon shortcut runs `pythonw.exe -m claudeplay tray` from the tool's environment rather than the `claudeplay-tray.exe` stub: Smart App Control blocks the per-install stubs uv generates, but allows the standard interpreter.

Tray icon colour: grey stopped, amber starting, green running, orange degraded (a server failed), red crashed. The menu has start/stop/restart, per-server toggles (a toggle restarts the gateway), copy connector URL, open logs folder, a kill switch and quit. Quitting, or killing the tray process, stops the gateway and its servers.

Logs: `%LOCALAPPDATA%\claudeplay\logs\claudeplay.log` (rotating). Tool calls log the tool name and duration, never arguments or results.

## The toolkit

Claude does not see the backends directly. It sees one server, `claudeplay`, with a curated set of tools defined in [toolkit.py](src/claudeplay/toolkit.py):

| Tool | What it does | Backend |
|---|---|---|
| `get_date` | today's date | obsidian |
| `journal_list_month` | which days in a month have an entry | obsidian |
| `journal_read` | read one day's entry | obsidian (`read_journal_entry`, needs obsidian-mcp with the journal tools) |
| `journal_append` | add a note to the end of today's entry | obsidian (`append_to_todays_journal`) |

Every other backend tool is hidden. `claudeplay serve --raw` exposes all of them as `<server>_<tool>` for debugging.

## Test with MCP Inspector

```powershell
claudeplay serve --insecure-no-auth
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8765/mcp --transport http --method tools/list
```

With the curated toolkit you see the four tools above; with `--raw`, backend names like `obsidian_list_wiki`.

## Develop

```powershell
uv run --extra test python -m pytest
```
