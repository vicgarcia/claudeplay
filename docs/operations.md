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
| **Servers** | Turns a server on or off. Saves to `config.toml` and restarts the gateway |
| **Copy connector URL** | Copies the address to give Claude |
| **Open config folder** | Opens the folder with `config.toml`, and the `logs` folder inside it |
| **Quit** | Stops everything and closes the tray |

If the tunnel dies, the tray retries every 15 seconds and shows orange until it's back.

## Commands

Run these as `claudeplay <command>`, or `python -m claudeplay <command>` if Smart App Control blocks the launcher.

| Command | What it does |
|---|---|
| `tray` | Runs the tray app, which starts the gateway. `--no-start` leaves it stopped |
| `serve` | Runs only the gateway, in the foreground, with no tunnel. `--console` also logs to the terminal, `--raw` exposes every backend tool |
| `status` | Shows the gateway's last status report |
| `check` | Shows the config with secrets masked |
| `install` / `uninstall` | Adds or removes the shortcut that starts the tray at logon |
| `genkey` | Prints a random signing key |

`--config <path>` goes before the command, as in `claudeplay --config test.toml serve`.

## Applying changes

| You changed | Do this |
|---|---|
| A server's `args` or `env`, or `[auth]` | **Restart** in the tray |
| The toolkit code (`toolkit.py`) | **Restart** in the tray, then reconnect the connector or start a new chat, so Claude re-reads the tool list |
| `[tunnel]`, `port`, or added a new `[servers.*]` section | **Quit** and start the tray again, because it reads these when it launches |
| claudeplay's dependencies | `uv tool install --force --editable .`, then quit and start the tray again |

With an editable install, code changes need only a restart.

## Files

Everything is under `%LOCALAPPDATA%\claudeplay`, and `CLAUDEPLAY_HOME` overrides that location.

| Path | Contents |
|---|---|
| `config.toml` | All settings and secrets |
| `logs\claudeplay.log` | Gateway and tray log, rotated at 1 MB with 5 kept |
| `logs\cloudflared.log` | Tunnel log |
| `status.json` | The gateway's current state, read by the tray |
| `oauth\` | Encrypted client registrations and tokens |

The tunnel's certificate and credentials are in `~/.cloudflared`.

Tool calls are logged by tool name, duration and outcome, never arguments or results, so the log shows that a tool ran but not what it did.

## Replacing a secret

| Secret | Where to change it | Then |
|---|---|---|
| GitHub client secret | Generate a new one on the OAuth App's page, put it in `config.toml`, and delete the old one | **Restart** |
| Pinboard token | Reset at pinboard.in → Settings → Password, and put it in `config.toml` | **Restart** |
| `jwt_signing_key` | Remove the line from `config.toml`; a new one is generated | **Restart**, then sign in to the connector again |

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

### Sign-in fails or I'm locked out

- **GitHub reports a redirect error:** the OAuth App's callback must be exactly `https://<hostname>/auth/callback`.
- **Sign-in works, then every request returns 401:** look for `rejected github user id` in the log. Your account's numeric id isn't in `allowed_user_ids`.
- **Sign-in stopped working after a config change:** changing `jwt_signing_key` logs out every client, so connect again.

### The `claudeplay` or `claudeplay-tray` command silently does nothing

Smart App Control blocks the launcher programs uv generates, because each has a unique hash with no reputation. The standard Python programs are allowed, so use `python -m claudeplay`. The logon shortcut already runs `pythonw.exe -m claudeplay tray` for this reason. To confirm, check the `Microsoft-Windows-CodeIntegrity/Operational` event log.

### Port 8765 is already in use

The tray names the process holding the port. It's often an earlier `claudeplay serve`. Stop that process, or change `port` in `config.toml`.

### A tool doesn't appear in Claude

Check that its server is `ok` in `claudeplay status`, that it has an entry in [the catalog](toolkit.md), and that you've reconnected since the change. The tool counts in `status` are what the backend offers, not what Claude sees.

### `pc_files` can't find a path

Use absolute paths. Relative ones resolve from the Desktop folder, not your home folder.

## Testing without the public endpoint

The live config has a tunnel, which rules out running without sign-in, so use a separate config file on another port:

```toml
# test.toml
[gateway]
port = 8766
insecure_no_auth = true

[servers.obsidian]
command = 'C:/Users/<you>/.local/bin/obsidian-mcp.exe'
args = ['--vault', 'C:/path/to/vault']
```

```powershell
python -m claudeplay --config test.toml serve --console
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8766/mcp --transport http --method tools/list
```

Add `--raw` after `serve` to see every backend tool under its internal name.

## Running the tests

```powershell
uv run --extra test python -m pytest
```

They take a minute or two, because many start real gateways.
