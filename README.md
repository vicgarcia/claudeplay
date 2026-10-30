# claudeplay

A Windows system-tray app that exposes local stdio MCP servers (obsidian-mcp, todo-mcp, pinboard-mcp) as **one** custom connector on claude.ai, so they work from the Claude iPhone app and voice mode.

One gateway, one endpoint, one login. Auth is GitHub OAuth (through FastMCP's OAuth proxy), restricted to your numeric GitHub user id. See [plan.md](plan.md) for the design and what is verified.

Status: the gateway, auth and tray run locally. The public tunnel (Cloudflare) is not built yet, so the connector is not reachable from claude.ai.

## Install

```powershell
uv tool install --editable .
```

This puts `claudeplay` and the windowless `claudeplay-tray` on the uv tools path.

## Configure

1. Copy [gateway.example.toml](gateway.example.toml) to `%LOCALAPPDATA%\claudeplay\gateway.toml` (or point `CLAUDEPLAY_CONFIG` at another file) and edit the server entries. The file is gitignored; it holds no secrets, only `${ENV_VAR}` references.
2. Create a GitHub OAuth App (GitHub > Settings > Developer settings > OAuth Apps > New OAuth App):

   | Field | Value |
   |---|---|
   | Application name | `claudeplay` (anything) |
   | Homepage URL | `http://localhost:8765` |
   | Authorization callback URL | `http://localhost:8765/auth/callback` |
   | Enable Device Flow | off |

   Then generate a client secret. A GitHub OAuth App holds exactly one callback URL, so when the public hostname exists you edit this field to `https://<host>/auth/callback`.
3. Find your numeric user id: open `https://api.github.com/users/<your-login>` and copy `id`. The allow-list matches this number, not the login name.
4. Set the environment variables below, and `allowed_user_ids = [<your id>]` in `gateway.toml`.
5. `claudeplay check` validates the file and reports which servers would start.

## Environment variables

Secrets never go in `gateway.toml`; it only holds `${NAME}` references. Set them as Windows **user** environment variables, then restart the tray (or sign out and in), because only new processes see them:

```powershell
setx CLAUDEPLAY_GITHUB_CLIENT_ID     "<client id>"
setx CLAUDEPLAY_GITHUB_CLIENT_SECRET "<client secret>"
setx CLAUDEPLAY_JWT_KEY              "$(claudeplay genkey)"
setx PINBOARD_TOKEN                  "<username:TOKEN>"
setx TODO_CLIENT_ID                  "<azure app client id>"
setx TODO_CLIENT_SECRET              "<azure app client secret>"
setx TODO_REFRESH_TOKEN              "<refresh token from todo-mcp --auth>"
```

| Variable | Needed for | Notes |
|---|---|---|
| `CLAUDEPLAY_GITHUB_CLIENT_ID` | GitHub login | from the OAuth App |
| `CLAUDEPLAY_GITHUB_CLIENT_SECRET` | GitHub login | from the OAuth App |
| `CLAUDEPLAY_JWT_KEY` | signing tokens, encrypting the token store | 32+ characters; changing it logs out every client |
| `PINBOARD_TOKEN` | pinboard server | Pinboard settings > Password > API token, format `username:TOKEN` |
| `TODO_CLIENT_ID` | todo server | Azure app (client) id |
| `TODO_CLIENT_SECRET` | todo server | Azure client secret |
| `TODO_REFRESH_TOKEN` | todo server | from `todo-mcp --auth --client-id ... --client-secret ...` |

Optional, for development and diagnostics:

| Variable | Purpose |
|---|---|
| `CLAUDEPLAY_CONFIG` | path to `gateway.toml` instead of `%LOCALAPPDATA%\claudeplay\gateway.toml` |
| `CLAUDEPLAY_HOME` | data directory (logs, status, token store, overrides) instead of `%LOCALAPPDATA%\claudeplay` |
| `CLAUDEPLAY_STARTUP_DIR` | where `install` puts the shortcut (tests use this) |

Servers need only the variables they reference. An unset variable fails just that server (the tray shows it, naming the variable but never a value). Obsidian needs none; `TZ` is set in its `env` table. todo and pinboard ship `enabled = false`: set their variables, then enable them from the tray's Servers menu. pinboard-mcp checks its token against Pinboard at startup and exits if it is wrong.

todo-mcp and pinboard-mcp read their credentials from their own environment, so the gateway passes them through each server's `env` table and nothing secret appears on a command line.

## Run

| Command | What it does |
|---|---|
| `claudeplay tray` | the tray app; starts the gateway |
| `claudeplay serve` | the gateway in the foreground (`--console` to also log to the terminal) |
| `claudeplay status` | the last status report: state and per-server health |
| `claudeplay install` / `uninstall` | add or remove a Startup-folder shortcut so the tray starts at logon |
| `claudeplay genkey` | print a random signing key |

The servers are separate uv tools: `uv tool install` obsidian-mcp, todo-mcp and pinboard-mcp so their `.exe` files exist in `~/.local/bin`.

`serve` and `tray` refuse to run without an `[auth]` section. `--insecure-no-auth` overrides that for local development only.

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
