# Architecture

This is how the parts fit together, for anyone changing the code. Start with [Overview](overview.md) if you haven't read it.

## Processes

Everything runs as one process tree under your user account:

```
claudeplay-tray.exe                       tray, status polling, supervisor
|   (a kill-on-close job holds everything below)
+-- python.exe -m claudeplay serve        the gateway, on 127.0.0.1:8765
|   +-- obsidian-mcp.exe                  stdio
|   +-- pinboard-mcp.exe                  stdio
|   +-- uvx.exe -> windows-mcp            stdio
+-- cloudflared.exe tunnel run            the tunnel
```

Because the tray runs inside a Windows job object, killing or crashing it also takes down everything below it, so no gateway keeps serving unsupervised.

## Code

| Module | Responsibility |
|---|---|
| `cli.py` | Commands. Decides whether the gateway may run without auth |
| `config.py` | Paths, parses and validates `config.yaml` (pydantic, unknown keys are errors), edits it in place (ruamel.yaml), masks secrets for display |
| `gateway.py` | Builds the FastMCP server, mounts the backends, checks their health, logs tool calls |
| `toolkit.py` | Loads and validates `toolkit.yaml`, checks it against what a server really lists, and the transform that presents the tools |
| `auth.py` | The OAuth proxy, allow-list and encrypted token store |
| `supervisor.py` | Starts, stops and watches the gateway and tunnel |
| `tray.py` | Icon and menu |
| `autostart.py` | The logon shortcut |
| `winutil.py` | Single-instance lock, job object, port owner, clipboard |
| `logs.py` | Rotating log setup |

## The life of a tool call

Say you ask Claude for yesterday's journal entry:

1. **Claude's servers send a request.** It's a `POST` to `https://<hostname>/mcp` with a bearer token, calling a tool such as `read_journal_entry`.
2. **Cloudflare forwards it.** Cloudflare handles HTTPS at its edge and passes the request down the tunnel. `cloudflared` opened that tunnel from the laptop, so no inbound port is open.
3. **The gateway checks the Host and Origin headers.** Anything other than localhost or the public hostname gets a 421 or 403.
4. **The gateway checks the token.** No valid token gets a 401, and a token for anyone not on the allow-list is rejected.
5. **The toolkit resolves the name.** `read_journal_entry` maps to the mounted tool `obsidian_read_journal_entry`. A name that `toolkit.yaml` doesn't expose is unknown, even if the backend has it.
6. **The proxy calls the backend.** It sends the call over stdio to `obsidian-mcp.exe`, which reads the file.
7. **The result goes back the same way.** The log records `tool=read_journal_entry ms=12 result=ok`, without the arguments or content.

## The gateway

`gateway.build` makes one FastMCP server and mounts one proxy per enabled backend:

```python
proxy = create_proxy(transport, name=server.name, mode='legacy')
gw.add_provider(proxy, namespace=server.name)
```

- **`mode='legacy'` is required.** FastMCP 4 clients otherwise start with a `server/discover` handshake, which MCP 1.x backends reject, and the proxy then silently lists zero tools.
- **Namespacing gives stable names.** Every backend tool becomes `<server>_<tool>` inside the gateway, no matter which other servers are enabled. The toolkit relies on this; Claude sees the names without the prefix.
- **Failures stay contained.** A backend that won't start is marked failed, and the others keep working.

### Health checks

On startup, the gateway connects to each backend and lists its tools, with a 120-second limit (`PROBE_TIMEOUT`), long enough for a `uvx` server that resolves its environment and imports a lot before it answers. A server that hasn't listed its tools by then is marked failed with `TimeoutError`. Zero tools counts as a failure, because the proxy swallows backend errors and returns an empty list.

The same probe checks `toolkit.yaml` against the backend: a listed tool the backend lacks, an argument that tool doesn't take, or an unlisted tool exposed under a name already in use marks the server failed, naming the tool or argument. It also reads the backend's own server instructions.

Server instructions are set on the FastMCP server after each probe, not when it is built, because a backend's instructions are only known once it has started. Sessions that start from then on get them.

The results go to `status.json`, written atomically. The tray reads that file, which means the gateway needs no health endpoint on its public port. Each run writes a run id that the supervisor generated, so a stale file from an earlier run can't be mistaken for the current state. It doesn't use the process id, because a uv environment's `python.exe` is a launcher with a different id from the real interpreter.

## The toolkit transform

`toolkit.Catalog` is a FastMCP `Transform` applied to the whole server. It has two jobs:

- **Listing:** keeps the listed tools, and every tool of an `expose_all` server, then uses `Tool.from_tool` to apply whatever `toolkit.yaml` sets: a new name or description, an appended description, annotations (layered over the backend's own), and argument changes. Anything not set passes through.
- **Calling:** maps the public name back to the mounted name. A backend's own prefixed names fail here as unknown, so hiding a tool also makes it uncallable.

It also returns nothing for resources and prompts. See [Toolkit](toolkit.md) for how to use it.

## Sign-in

GitHub doesn't support the dynamic client registration that Claude needs, so FastMCP's `OAuthProxy` sits in the middle: to Claude it's an OAuth server, and to GitHub it's an ordinary OAuth app.

```
Claude                    gateway (OAuthProxy)               GitHub
  | POST /mcp                  |                                |
  |<---- 401 + metadata URL ---|                                |
  | discover, register ------->|                                |
  | /authorize --------------->|  consent page                  |
  |                            |-- redirect to authorize ------>|
  |                            |<-- /auth/callback + code ------|
  |                            |-- exchange for GitHub token -->|
  |<---- gateway's own token --|                                |
  | POST /mcp + token -------->|-- check user id (cached 5 min)>|
```

- **Claude never holds a GitHub token.** It gets a token issued by the gateway, and the GitHub token stays in the encrypted store.
- **The allow-list runs on every request**, not just at login. A stranger can complete GitHub sign-in and get a token, but every request with it fails. It's enforced in `AllowListVerifier`, and again in `AuthMiddleware` in case a verifier is ever swapped.
- **Identity checks are cached for 5 minutes**, because each one costs two GitHub API calls.
- **The store** is `FileTreeStore` wrapped in Fernet encryption. Its key is derived from `jwt_signing_key`, and it's kept in a folder named after the key's fingerprint, so changing the key orphans old sessions instead of corrupting them.

`OAuthProxy` is built directly because FastMCP's `GitHubProvider` doesn't accept a custom verifier. It requests the `read:user` scope, which is enough to identify you.

## The tunnel

The supervisor runs:

```
cloudflared tunnel --no-autoupdate run --credentials-file ~/.claudeplay/cloudflared/<tunnel-id>.json --url http://127.0.0.1:8765 <tunnel-id>
```

Passing `--url` means there's no second config file. The tunnel settings are all in the `tunnel` section of `config.yaml`, and the credentials are in `~/.claudeplay/cloudflared`.

- **Run by id.** cloudflared documents that a tunnel identified by its id needs only the credentials file, while looking a tunnel up by name needs the account certificate (`cert.pem`). claudeplay takes the id from the credentials file's name, so `cert.pem` isn't used while running and is only needed for admin commands such as `tunnel create`.
- **Logging.** cloudflared's stdout and stderr go to `%LOCALAPPDATA%\claudeplay\logs\cloudflared.log` through a handle claudeplay opens, so failures before it opens a log of its own are kept. cloudflared never rotates its output, so a log over 500 KB is renamed to `cloudflared.log.1` each time the tunnel starts.

- **Start and stop order:** the tunnel starts after the gateway and stops before it, so nothing public points at a gateway that's going away.
- **Recovery:** the tray's 2-second poll calls `check_tunnel`, which restarts a dead tunnel at most every 15 seconds. A failed tunnel leaves the gateway running and shows as degraded.

Cloudflare reaches the gateway over plain HTTP, which has two consequences:

- FastMCP's Host and Origin checks are off by default, so the gateway turns them on and lists the public hostname. `allowed_hosts` has no effect without `host_origin_protection=True`.
- The public origin is listed explicitly, because FastMCP's same-origin fallback would compare the browser's `https://` origin against an `http://` request and refuse it.

## Config handling

- **Two files, two folders.** `config.yaml`, `toolkit.yaml`, the token store, the tunnel credentials and `status.json` are in `~/.claudeplay` (`CLAUDEPLAY_HOME`). Logs are in `%LOCALAPPDATA%\claudeplay\logs` (`CLAUDEPLAY_LOGS`), apart from the credentials. `toolkit.yaml` is always read from the folder of the config it goes with.
- **Edits are in place.** The tray's toggles and the first-run signing key use ruamel.yaml's round-trip mode, so comments, key order, quoting and line endings survive, and a toggle changes only the value. Writes go to a temp file, then replace the original.
- **Who reads what, and when:** the gateway reads both files each time it starts. The tray reads them when it launches (a bad `toolkit.yaml` is reported there rather than as a crash) and `config.yaml` after a toggle. That's why some changes need a tray restart ([which ones](operations.md#applying-changes)).
- **`${NAME}`** in any value is replaced in memory with that environment variable. Nothing uses it today.

## Known gaps

- A crashed gateway doesn't restart by itself.
- File tools passed through from a backend have no size limit on their results beyond the backend's own.
- Two `expose_all` servers that share a tool name can't be told apart in advance: the one earlier in `toolkit.yaml` wins and the other's tool is hidden, with a warning in the log. Listing one of them under another `name` avoids it.
- `web_fetch` was dropped; the `web-fetch-signed-in` branch keeps that work.
