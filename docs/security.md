# Security

claudeplay puts a shell on your laptop behind a public URL. This page covers what protects it, what doesn't, and how to shut it off.

## Turning it off

| Situation | Do this |
|---|---|
| Stop everything now | Tray → **Stop** |
| Something's wrong and you're away from the laptop | Delete the DNS record in the Cloudflare dashboard, or revoke the OAuth App at github.com/settings/applications. Both work from a phone |
| Stop one capability | Tray → **Servers**, and turn that server off |
| Disable the tunnel permanently | Set `enabled: false` under `tunnel` and restart the tray |

## What protects it

**GitHub sign-in with an allow-list is the one real barrier.** The rest supports it or limits the damage.

| Protection | What it does |
|---|---|
| Allow-list on numeric GitHub id | Only your account's requests are accepted, checked on every request |
| No inbound ports | The gateway listens only on 127.0.0.1, and the tunnel is opened outbound |
| Host and Origin checks | Requests must be addressed to localhost or the public hostname |
| No-auth refused with a tunnel | The gateway won't start without sign-in while a tunnel is enabled, or on a non-loopback address |
| Toolkit | Tools of a server that `toolkit.yaml` doesn't expose can't be called, even by name. A server with `expose_all` exposes all of its tools, so use it only for servers you trust |
| Hard-to-guess hostname | Cuts down on scanner traffic. This is noise reduction, not a secret |
| Masked secrets and quiet logs | `check` hides secrets, and logs never contain arguments, results or OAuth codes |
| Encrypted token store | Tokens on disk are encrypted with a key derived from `jwt_signing_key` |
| Pinned versions | The fastmcp version range and windows-mcp version are fixed, so a restart doesn't pull new code |

## What your GitHub account now protects

Anyone who gets into your GitHub account can sign in here and use every tool you expose, which with a shell tool such as the example's `pc_shell` means running commands as you on your laptop. Use two-factor authentication on GitHub.

## Accepted risks

The owner has accepted these knowingly. They're written down so that later decisions are made with them in view.

### `pc_shell` and `pc_files` have full access

These are the example's windows-mcp tools. They run as your user, with no folder or command limits. They can read `config.yaml`, the tunnel credentials in `~/.claudeplay/cloudflared`, browser data and anything else you can read. `pc_shell` isn't marked destructive, so the app may not ask before running it. `pc_files` is.

claudeplay itself adds no limits to any server's tools, including file tools: a server that can read or write anywhere in a vault can do that for Claude. Limits belong in the server.

### Outside content can try to give Claude instructions

Bookmark titles and descriptions, web pages, and any other third-party text a tool returns arrive in the same conversation as your journal and your shell. Hidden text in it could tell Claude to read a private file and send it somewhere, or to run a command. Claude is trained to resist this, but that's no guarantee. claudeplay has no web fetch tool now (it was dropped, and the `web-fetch-signed-in` branch keeps that work), so the main sources are bookmarks and whatever your servers read.

To reduce the risk, keep approval prompts on for `pc_shell` in your connector settings. Without a shell, text from outside has much less to aim at.

### Server text goes to Claude as written

Tool descriptions and instructions from your servers are passed to Claude unchanged unless `toolkit.yaml` replaces them, so a server upgrade changes what Claude is told without you reviewing it. That's intended, and it's why `expose_all` is for servers you trust.

## Who can see your data

| Party | What they see |
|---|---|
| Anthropic | Tool calls and results, like any part of your Claude conversation |
| Cloudflare | Request contents, because HTTPS ends at its edge and the tunnel carries the traffic to you |
| GitHub | That you signed in to this app. Your numeric id is public anyway |
| Pinboard, Microsoft, and any other service a server talks to | What each server sends them |

## Secrets

| Secret | Location | If it leaks |
|---|---|---|
| GitHub client secret | `config.yaml` | Lets someone impersonate the app in an OAuth flow. It doesn't get past the allow-list on its own |
| `jwt_signing_key` | `config.yaml` | Can decrypt the token store and sign gateway tokens. Replace it |
| Tunnel credentials | `~/.claudeplay/cloudflared` | Lets someone serve your hostname. Delete and recreate the tunnel |
| Backend tokens | `config.yaml` | Gives access to that service |

All of these are plain files readable by any program running as you, which is why `config.yaml` and the other files in `~/.claudeplay` must stay out of the repo and out of chat. Anything pasted into a chat has left your machine, so replace it ([how](operations.md#replacing-a-secret)).

`.gitignore` excludes `config.yaml` and `toolkit.yaml`, but only files with those names. Be careful with copies.

## Keeping this repo clean

Examples use placeholders such as `<hostname>`, `<you>` and `example.net`. Don't put real hostnames, ids or vault paths in committed docs or examples.
