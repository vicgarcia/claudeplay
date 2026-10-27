# claudeplay

A Windows system-tray app that exposes local stdio MCP servers (obsidian-mcp, todo-mcp) as **one** custom connector on claude.ai, so they work from the Claude iPhone app and voice mode.

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
4. Put the secrets in user environment variables (new terminals and the next logon pick them up):

   ```powershell
   setx CLAUDEPLAY_GITHUB_CLIENT_ID     <client id>
   setx CLAUDEPLAY_GITHUB_CLIENT_SECRET <client secret>
   setx CLAUDEPLAY_JWT_KEY              (claudeplay genkey)
   ```

   Set `allowed_user_ids = [<your id>]` in `gateway.toml`.
5. `claudeplay check` validates the file and reports which servers would start.

todo-mcp reads `TODO_CLIENT_ID`, `TODO_CLIENT_SECRET` and `TODO_REFRESH_TOKEN` from its environment, so the example config passes them through `env` and nothing secret appears on its command line. It ships `enabled = false`.

## Run

| Command | What it does |
|---|---|
| `claudeplay tray` | the tray app; starts the gateway |
| `claudeplay serve` | the gateway in the foreground (`--console` to also log to the terminal) |
| `claudeplay status` | the last status report: state and per-server health |
| `claudeplay install` / `uninstall` | add or remove a Startup-folder shortcut so the tray starts at logon |
| `claudeplay genkey` | print a random signing key |

`serve` and `tray` refuse to run without an `[auth]` section. `--insecure-no-auth` overrides that for local development only.

Tray icon colour: grey stopped, amber starting, green running, orange degraded (a server failed), red crashed. The menu has start/stop/restart, per-server toggles (a toggle restarts the gateway), copy connector URL, open logs folder, a kill switch and quit. Quitting, or killing the tray process, stops the gateway and its servers.

Logs: `%LOCALAPPDATA%\claudeplay\logs\claudeplay.log` (rotating). Tool calls log the tool name and duration, never arguments or results.

## Test with MCP Inspector

```powershell
claudeplay serve --insecure-no-auth
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8765/mcp --transport http --method tools/list
```

Tool names are always `<server>_<tool>`, for example `obsidian_list_wiki`.

## Develop

```powershell
uv run --extra test pytest
```
