# Overview

claudeplay lets the Claude iPhone app, including voice mode, use tools that live on a Windows laptop: an Obsidian journal, projects and wiki, Microsoft To Do tasks, Pinboard bookmarks, files and a shell. It runs in the system tray and presents all of them to Claude as one custom connector.

## Why it needs all these parts

The tools are local programs that talk over stdin and stdout (stdio MCP servers). Claude's mobile app can't reach them, for two reasons:

- **Claude's servers make the connection, not the phone.** The connector must be a public HTTPS address, so being on the same network or a VPN doesn't help.
- **A public address needs a login.** Anyone on the internet can reach it, and these tools hold private data.

Each part of claudeplay solves one piece of this:

| Part | Job |
|---|---|
| **Gateway** | Runs the local tools and serves them as one HTTP endpoint |
| **Toolkit** | Decides which tools Claude sees and how they are named and described |
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
obsidian-mcp  todo-mcp  pinboard-mcp  windows-mcp  --+
```

## What Claude can do

| Area | Tools |
|---|---|
| Date and time | `get_todays_date`, `get_current_timestamp` |
| Journal | `journal_list_month`, `journal_read`, `journal_append` |
| Projects | `projects_list`, `projects_files`, `projects_create`, `projects_read`, `projects_write` |
| Wiki | `wiki_list`, `wiki_read` |
| Tasks | `tasks_lists`, `tasks_list`, `tasks_due_today`, `tasks_add`, `tasks_update`, `tasks_complete` |
| Bookmarks | `bookmarks_list`, `bookmarks_add`, `bookmarks_update` |
| Laptop | `pc_files`, `pc_shell` |
| Web | `web_fetch` |

[Toolkit](toolkit.md) has the details.

## Limits

- **The laptop has to be on, awake and online.** A locked screen or screensaver should be fine for these tools, but sleep or shutdown takes the connector offline. It needs no one logged in at the keyboard, but the tray runs at logon, so after a reboot someone must log in once.
- **Nothing visual.** The laptop is expected to be locked, so the toolkit leaves out tools that drive windows, the mouse or the screen.
- **Windows only.** The tray, process handling and autostart all use Windows features.
- **One user.** There is one endpoint, one login and one allow-list. It's built for one person's own data.

## Still to confirm

These haven't been tested end to end:

- Calling the tools from voice mode.
- Using `pc_shell`, `pc_files` and `web_fetch` while the laptop is actually locked.
