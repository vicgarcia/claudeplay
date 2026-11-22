# Overview

claudeplay lets the Claude iPhone app, including voice mode, use the MCP servers you run on a Windows laptop: your notes, tasks, bookmarks, files, a shell, or anything else with a stdio MCP server. It runs in the system tray and presents all of them to Claude as one custom connector.

## Why it needs all these parts

The tools are local programs that talk over stdin and stdout (stdio MCP servers). Claude's mobile app can't reach them, for two reasons:

- **Claude's servers make the connection, not the phone.** The connector must be a public HTTPS address, so being on the same network or a VPN doesn't help.
- **A public address needs a login.** Anyone on the internet can reach it, and these tools hold private data.

Each part of claudeplay solves one piece of this:

| Part | Job |
|---|---|
| **Gateway** | Runs the local servers and serves them as one HTTP endpoint |
| **Toolkit** | Decides which of their tools Claude sees, and adds to their text where needed |
| **GitHub sign-in** | Lets only your GitHub account in |
| **Cloudflare Tunnel** | Gives the laptop a public HTTPS address without opening any inbound ports |
| **Tray app** | Starts, stops and shows the state of everything |

## The big picture

```
Claude on your phone
        |
Claude's servers (claude.ai)
        |  HTTPS
Cloudflare
        |  tunnel, opened outbound from the laptop
cloudflared                                  --+
        |                                      |
claudeplay gateway on 127.0.0.1:8765           |  all on your laptop,
   sign-in check, then the toolkit             |  all run by the tray app
        |  stdio                               |
your MCP servers (from config.yaml)          --+
```

## What Claude can do

Whatever your `toolkit.yaml` exposes from your servers, plus `get_current_timestamp`, which is built in. The shipped [toolkit.example.yaml](../toolkit.example.yaml) shows one setup: an Obsidian vault, Pinboard and the laptop itself. [Toolkit](toolkit.md) explains how to write your own.

## Limits

- **The laptop has to be on, awake and online.** A locked screen or screensaver should be fine for tools that need no window, but sleep or shutdown takes the connector offline. It needs no one logged in at the keyboard, but the tray runs at logon, so after a reboot someone must log in once.
- **Nothing visual.** The laptop is expected to be locked, so tools that drive windows, the mouse or the screen won't work.
- **Windows only.** The tray, process handling and autostart all use Windows features.
- **One user.** There is one endpoint, one login and one allow-list. It's built for one person's own data.

## Still to confirm

These haven't been tested end to end:

- Calling the tools from voice mode.
- Using laptop file and shell tools while the laptop is actually locked.
