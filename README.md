# claudeplay

A Windows system-tray app that lets the Claude iPhone app, including voice mode, use the MCP servers you run on your own laptop. Whatever stdio MCP servers you point it at (notes, tasks, bookmarks, files, a shell) appear to Claude as one custom connector, behind GitHub sign-in and a Cloudflare Tunnel.

```
Claude on your phone -> claude.ai -> Cloudflare -> tunnel -> gateway on 127.0.0.1 -> your local MCP servers
```

The local tools are stdio MCP servers, which Claude's mobile app can't reach directly. The tray app runs them behind one HTTP endpoint and opens the tunnel without any inbound ports. Only your GitHub account can sign in.

claudeplay holds no tools of its own except a clock. Everything else comes from two YAML files in `~/.claudeplay`:

- **`config.yaml`** says how the gateway runs, who may sign in, which tunnel to use, and how to start each of your MCP servers, with their secrets.
- **`toolkit.yaml`** says which of each server's tools Claude sees. A tool passes through exactly as its server describes it, with its own name, description, arguments and server instructions. The file only picks which tools are exposed and adds to or replaces the text where the server's own doesn't fit your setup. Tools a server offers that you don't expose are hidden and can't be called, even by name.

The laptop has to be on, awake and online, though a locked screen should be fine. Calling the tools from voice mode, and using the laptop tools while it's locked, haven't been tested end to end yet.

## What Claude sees

One built-in tool, always present, which follows the laptop's clock and time zone (which may differ from where you are):

| Tool | What it does |
|---|---|
| `get_current_timestamp` | The current date and time in every common form: `YYYY-MM-DD`, 24-hour and 12-hour time, day of the week, a spoken-style date, ISO 8601 local and UTC, unix seconds, ISO week, time zone name and UTC offset |

Everything else is whatever `toolkit.yaml` exposes from your servers, and only while a server is enabled and running. [toolkit.example.yaml](toolkit.example.yaml) shows the author's setup: an Obsidian vault (every tool exposed), Pinboard bookmarks, and files and a shell on the laptop, which are renamed and described by hand. [Toolkit](docs/toolkit.md) explains how to write your own.

## Documentation

- [Overview](docs/overview.md): what it is, why it exists, and its limits
- [Setup](docs/setup.md): from nothing to a working connector
- [Operations](docs/operations.md): the tray, commands, logs and troubleshooting
- [Toolkit](docs/toolkit.md): writing `toolkit.yaml`
- [Architecture](docs/architecture.md): how the parts work
- [Security](docs/security.md): what protects your data, the accepted risks, and how to shut it off

## Quick reference

```powershell
uv tool install git+https://github.com/vicgarcia/claudeplay   # install
uv tool upgrade claudeplay                # update to the latest main
claudeplay check                          # validate both files; config shown with secrets masked
claudeplay status                         # show what's running
claudeplay install                        # start the tray at logon
```

For development, work in the repo:

```powershell
uv run --extra test python -m pytest      # run the tests
uv run python -m claudeplay serve --raw   # run a gateway from this checkout
```

Configuration and credentials live in `~/.claudeplay` (`CLAUDEPLAY_HOME` changes the folder), outside this repo: start from [config.example.yaml](config.example.yaml) and [toolkit.example.yaml](toolkit.example.yaml). Logs are in `%LOCALAPPDATA%\claudeplay\logs`.
