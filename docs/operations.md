# Operations

## The tray

The sparkle icon's colour shows the overall state:

| Colour | State | Meaning |
|---|---|---|
| Grey | stopped | Nothing is running |
| Amber | starting | The gateway is checking its servers |
| Green | running | Everything enabled is up |
| Orange | degraded | The gateway is up, but a server failed or the tunnel is down |
| Red | crashed | The gateway exited unexpectedly. It does not restart by itself; choose **Start** |

| Menu item | What it does |
|---|---|
| **Start / Stop / Restart** | Controls the gateway and tunnel together. **Stop** takes the connector offline immediately, and the tray stays open |
| **Servers** | Turns a server on or off. Saves to `config.yaml` (only that value changes) and restarts the gateway |
| **Copy connector URL** | Copies the address to give Claude |
| **Open config folder** | Opens `~/.claudeplay`, with `config.yaml` and `toolkit.yaml` |
| **Open logs folder** | Opens `%LOCALAPPDATA%\claudeplay\logs` |
| **Quit** | Stops everything and closes the tray |

If the tunnel dies, the tray retries every 15 seconds and shows orange until it's back.

## Commands

Run these as `claudeplay <command>`.

| Command | What it does |
|---|---|
| `tray` | Runs the tray app, which starts the gateway. `--no-start` leaves it stopped |
| `serve` | Runs only the gateway, in the foreground, with no tunnel. `--console` also logs to the terminal, `--raw` exposes every backend tool |
| `status` | Shows the gateway's last status report |
| `check` | Validates `config.yaml` and `toolkit.yaml`, shows the config with secrets masked, and counts the tools listed for each server |
| `install` / `uninstall` | Adds or removes the shortcut that starts the tray at logon |
| `genkey` | Prints a random signing key |

`--config <path>` goes before the command and points at a `config.yaml`, as in `claudeplay --config test.yaml serve`. `toolkit.yaml` is always read from the same folder as the config.

## Applying changes

| You changed | Do this |
|---|---|
| A server's `args` or `env`, or `auth` | **Restart** in the tray |
| `toolkit.yaml` | **Restart** in the tray, then reconnect the connector or start a new chat, so Claude re-reads the tool list |
| `tunnel`, `port`, or added a new server under `servers:` | **Quit** and start the tray again, because it reads these when it launches |
| claudeplay's dependencies | `uv tool install --force --editable .`, then quit and start the tray again |

With an editable install, code changes need only a restart.

## Files

Configuration and credentials are in `~/.claudeplay`, and `CLAUDEPLAY_HOME` overrides that location. Logs are kept apart, in `%LOCALAPPDATA%\claudeplay\logs`, and `CLAUDEPLAY_LOGS` overrides that.

| Path | Contents |
|---|---|
| `~/.claudeplay/config.yaml` | Settings and secrets |
| `~/.claudeplay/toolkit.yaml` | Which tools Claude sees, and the text added to them |
| `~/.claudeplay/status.json` | The gateway's current state, read by the tray |
| `~/.claudeplay/oauth/` | Encrypted client registrations and tokens |
| `~/.claudeplay/cloudflared/` | The tunnel's credentials file, `<tunnel-id>.json` (and `cert.pem` if you copied it) |
| `logs\claudeplay.log` | Gateway and tray log, rotated at 1 MB with 5 kept |
| `logs\cloudflared.log` | Tunnel log, including its errors. Moved to `.log.1` at tunnel start once over 500 KB |

Tool calls are logged by tool name, duration and outcome, never arguments or results, so the log shows that a tool ran but not what it did.

## Replacing a secret

| Secret | Where to change it | Then |
|---|---|---|
| GitHub client secret | Generate a new one on the OAuth App's page, put it in `config.yaml`, and delete the old one | **Restart** |
| Pinboard token | Reset at pinboard.in → Settings → Password, and put it in `config.yaml` | **Restart** |
| `jwt_signing_key` | Remove the line from `config.yaml`; a new one is generated | **Restart**, then sign in to the connector again |

## Troubleshooting

### Claude says the connector is unavailable

Work from the laptop outward:

1. Is the laptop awake and the icon green? `claudeplay status` shows why if it isn't.
2. Does `curl.exe -i -X POST https://<hostname>/mcp` return 401?

| Result | Meaning |
|---|---|
| 401 | The laptop side is fine. Reconnect the connector in claude.ai |
| 530 or 1033 | Cloudflare can't reach the tunnel. Check `logs\cloudflared.log`. A few of these right after a start are normal |
| 502 | The tunnel is up but the gateway isn't. Check `logs\claudeplay.log` |
| 421 | The Host header isn't allowed. `public_base_url` doesn't match the hostname you're using |

### A server shows `failed to start`

Run `claudeplay check`, then look in `logs\claudeplay.log`. The error shows only the exception type, because messages can contain command lines.

- **TimeoutError:** the server took more than 30 seconds to start, usually while `uvx` downloads packages on its first run. **Restart** should fix it.
- **Exposed no tools:** it started and then failed. Run its command by hand to see the error. For pinboard, this usually means a bad token.
- **`toolkit.yaml: ...` naming a tool or argument:** the server started, but `toolkit.yaml` lists a tool it doesn't have, an argument a tool doesn't take, or an unlisted tool under a name already used. It usually means the server was upgraded and renamed something. Fix the name in `toolkit.yaml` and restart.

### Sign-in fails or I'm locked out

- **GitHub reports a redirect error:** the OAuth App's callback must be exactly `https://<hostname>/auth/callback`.
- **Sign-in works, then every request returns 401:** look for `rejected github user id` in the log. Your account's numeric id isn't in `allowed_user_ids`.
- **Sign-in stopped working after a config change:** changing `jwt_signing_key` logs out every client, so connect again.

### The `claudeplay` or `claudeplay-tray` command silently does nothing

Smart App Control is probably back on. It blocks the unsigned programs uv installs, so claudeplay needs it off ([setup](setup.md)). To confirm, check the `Microsoft-Windows-CodeIntegrity/Operational` event log.

### Port 8765 is already in use

The tray names the process holding the port. It's often an earlier `claudeplay serve`. Stop that process, or change `port` in `config.yaml`.

### A tool doesn't appear in Claude

Check that its server is `ok` in `claudeplay status`, that `toolkit.yaml` lists it or sets `expose_all` for its server ([how](toolkit.md)), and that you've reconnected since the change. The tool counts in `status` are what the backend offers, not what Claude sees.

### A laptop file tool can't find a path

With the example's windows-mcp file tool (`pc_files`), use absolute paths. Relative ones resolve from the Desktop folder, not your home folder.

## Testing without the public endpoint

The live config has a tunnel, which rules out running without sign-in, so use a separate config file on another port:

```yaml
# test/config.yaml, with a toolkit.yaml next to it (expose_all: true for obsidian)
gateway:
  port: 8766
  insecure_no_auth: true

servers:
  obsidian:
    command: C:/Users/<you>/.local/bin/obsidian-mcp.exe
    args: [--vault, C:/path/to/vault]
```

```powershell
claudeplay --config test/config.yaml serve --console
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8766/mcp --transport http --method tools/list
```

Add `--raw` after `serve` to see every backend tool under its internal name, with no `toolkit.yaml` needed.

## Running the tests

```powershell
uv run --extra test python -m pytest
```

They take a minute or two, because many start real gateways.
