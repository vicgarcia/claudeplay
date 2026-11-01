# claudeplay

A Windows system-tray app that lets the Claude iPhone app, including voice mode, use tools on your laptop: an Obsidian journal, Pinboard bookmarks, files and a shell. They appear to Claude as one custom connector, behind GitHub sign-in and a Cloudflare Tunnel.

```
Claude on your phone -> claude.ai -> Cloudflare -> tunnel -> gateway on 127.0.0.1 -> local MCP servers
```

## Documentation

- [Overview](docs/overview.md): what it is, why it exists, and its limits
- [Setup](docs/setup.md): from nothing to a working connector
- [Operations](docs/operations.md): the tray, commands, logs and troubleshooting
- [Toolkit](docs/toolkit.md): what Claude sees, and how to add a tool
- [Architecture](docs/architecture.md): how the parts work
- [Security](docs/security.md): what protects your data, the accepted risks, and how to shut it off

[plan.md](plan.md) records the project's decisions and history.

## Quick reference

```powershell
uv tool install --editable .              # install
python -m claudeplay check                # show the config, secrets masked
python -m claudeplay status               # show what's running
python -m claudeplay install              # start the tray at logon
uv run --extra test python -m pytest      # run the tests
```

The config and all secrets live in `%LOCALAPPDATA%\claudeplay\config.toml`, outside this repo. Start from [config.example.toml](config.example.toml).
