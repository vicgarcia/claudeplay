# Setup

This goes from nothing to a working connector. Allow an hour or so, plus however long your DNS change takes.

**You need:**

- Windows 11 with Smart App Control turned off (Windows Security, App & browser control). It blocks the unsigned programs uv installs, and has no way to allow just these
- [uv](https://docs.astral.sh/uv/)
- a domain you can move to Cloudflare (the free plan is enough)
- a GitHub account
- a Claude plan that allows custom connectors

Do the steps in order, because the hostname you pick in step 3 is used in steps 4 and 5.

## 1. Install claudeplay and the backends

Install claudeplay as a uv tool, from GitHub. Its repo is private, so it installs over SSH:

```powershell
uv tool install git+https://github.com/vicgarcia/claudeplay
```

Then install whichever MCP servers you want to use, in whatever way they're distributed. The author's, for example:

```powershell
uv tool install git+https://github.com/vicgarcia/obsidian-mcp
uv tool install git+https://github.com/vicgarcia/todo-mcp
uv tool install git+https://github.com/vicgarcia/pinboard-mcp
```

Each puts its command in `~/.local/bin`: `claudeplay.exe`, `claudeplay-tray.exe`, `obsidian-mcp.exe` and so on. `config.yaml` runs the servers by those paths. A server that runs through `uvx`, such as windows-mcp, needs no install, and the config can pin its version. `uv tool upgrade --all` updates the installed tools to their latest `main`.

Then install cloudflared:

```powershell
winget install --id Cloudflare.cloudflared --exact
```

Windows shows an admin prompt for this, which can hide behind other windows. If the install seems stuck, look for it on the taskbar. Open a new terminal afterwards so `cloudflared` is on your PATH.

## 2. Create the two files

Make the folder `~/.claudeplay` (`CLAUDEPLAY_HOME` changes it) and copy in two files from the repo:

- [config.example.yaml](../config.example.yaml) as `config.yaml`: settings, sign-in, the tunnel, and how to start each server. It holds secrets once filled in.
- [toolkit.example.yaml](../toolkit.example.yaml) as `toolkit.yaml`: which of your servers' tools Claude sees ([how to write it](toolkit.md)). It holds no secrets, but ids in it are specific to your account.

Both stay outside the repo. Don't commit or paste `config.yaml`. To check both files at any time, with secrets masked:

```powershell
claudeplay check
```

## 3. Move your domain to Cloudflare and pick a hostname

1. In the Cloudflare dashboard, choose **Add a domain**, enter your domain and pick the Free plan.
2. Review the DNS records it imports. Keep any you still use, such as mail. Moving a domain with records you need but Cloudflare missed will break them.
3. Cloudflare shows two nameservers. Set them at your registrar. On Namecheap, that's **Domain List → Manage → Nameservers → Custom DNS**, and you must click the green checkmark to save.
4. Wait for Cloudflare to mark the domain **Active**, which can take from minutes to hours.

An empty record list is fine. Cloudflare warns about it, but activation depends only on the nameservers.

Pick a hard-to-guess hostname, which keeps scanners away from your login page:

```powershell
python -c "import secrets; print('cp-' + secrets.token_hex(6))"
```

Your hostname is that label under your domain, such as `cp-1a2b3c4d5e6f.example.net`. This guide calls it `<hostname>`.

## 4. Create the GitHub OAuth App

Go to [github.com/settings/applications/new](https://github.com/settings/applications/new):

| Field | Value |
|---|---|
| Application name | `claudeplay` |
| Homepage URL | `https://<hostname>` |
| Authorization callback URL | `https://<hostname>/auth/callback` |
| Enable Device Flow | off |
| Expire user tokens | off |

Register it and generate a client secret. GitHub shows the secret only once.

Find your numeric user id at `https://api.github.com/users/<your-login>`, in the `id` field. The allow-list matches this number, not your login name.

Fill in `config.yaml`, pasting the secret straight into the file:

```yaml
auth:
  client_id: '<client id>'
  client_secret: '<client secret>'
  allowed_user_ids: [<your numeric id>]
```

Leave out `jwt_signing_key`. It's generated and saved on the first run.

## 5. Create the tunnel

```powershell
cloudflared tunnel login
cloudflared tunnel create claudeplay
cloudflared tunnel route dns claudeplay <hostname>
```

`login` opens a browser, where you pick your domain. These commands save a certificate and the tunnel's credentials in `~/.cloudflared`. Copy the tunnel's credentials file, `<tunnel-id>.json`, into `~/.claudeplay/cloudflared`. That's the only file claudeplay needs: it runs the tunnel by its id, which doesn't use the certificate. The certificate (`cert.pem`) is needed only for admin commands such as `tunnel create`, so keep it where it is, or copy it too if you want everything in one place.

Add these to `config.yaml`:

```yaml
gateway:
  public_base_url: https://<hostname>

tunnel:
  name: claudeplay
```

Make sure `insecure_no_auth` is not set. The gateway refuses to run without sign-in while a tunnel is enabled.

## 6. Configure your servers

Under `servers:` in `config.yaml`, give each server its `command`, `args` and `env`, and set `enabled: true` on the ones you want. Then, in `toolkit.yaml`, say which of their tools Claude should see (`expose_all: true`, or a list). A server with nothing listed in `toolkit.yaml` exposes nothing.

For the servers in the example files:

| Server | What it needs |
|---|---|
| obsidian | `--vault` path in `args`. "Today" follows the laptop's time zone. Set `TZ` only to override that |
| pinboard | `PINBOARD_TOKEN`, from pinboard.in → Settings → Password, as `username:TOKEN`. It checks the token at startup and exits if it's wrong |
| windows | the path to `uvx.exe`. Keep `ANONYMIZED_TELEMETRY: 'false'`, because telemetry is on otherwise |
| todo | `TODO_CLIENT_ID`, `TODO_CLIENT_SECRET`, and `TODO_REFRESH_TOKEN` from `todo-mcp --auth --client-id ... --client-secret ...`. The list ids in `toolkit.yaml` come from its `get_lists` tool |

Each server's `env` values go only to that server's process, and nothing secret appears on a command line.

> **Before enabling windows:** it gives whoever signs in a shell and full file access on the laptop. Read [Security](security.md) first.

## 7. Start it

```powershell
claudeplay install
```

This adds a shortcut that starts the tray at logon. To start it now, double-click `claudeplay` in your Startup folder (`shell:startup` in the Run dialog). A sparkle icon appears in the system tray, and it turns green once everything is up.

Check it:

```powershell
claudeplay status
curl.exe -i -X POST https://<hostname>/mcp
```

The status should list your servers as `ok`. The `curl` should return **401 Unauthorized**, which means the tunnel works and sign-in is being enforced. The first start of windows can report a timeout while `uvx` downloads its packages. If so, choose **Restart** in the tray.

## 8. Connect Claude

1. In claude.ai, go to **Settings → Connectors → Add custom connector**.
2. Enter `https://<hostname>/mcp`. **Copy connector URL** in the tray gives you this.
3. Click **Connect** and sign in with GitHub.
4. On your phone, open the Claude app and ask "what's today's date?".

Connectors are tied to your account, so it should also appear in the iPhone app and Claude Desktop. If you previously added an `mcp-remote` entry to Claude Desktop's config for local use, remove it.

## Local use without a tunnel

To try the gateway on this machine only, skip steps 3 to 5, and in `config.yaml` set `insecure_no_auth: true` under `gateway` and leave out `auth` and `tunnel`. This only works on 127.0.0.1. If `auth` is present, sign-in is required regardless of this setting.

Claude Desktop can't reach localhost through Connectors, so add a bridge to its `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claudeplay": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote", "http://localhost:8765/mcp"]
    }
  }
}
```
