# claudeplay

A Windows system-tray app that lets the Claude iPhone app, including voice mode, use tools on your laptop: an Obsidian vault, Microsoft To Do tasks, Pinboard bookmarks, files, a shell and web pages. They appear to Claude as one custom connector, behind GitHub sign-in and a Cloudflare Tunnel.

```
Claude on your phone -> claude.ai -> Cloudflare -> tunnel -> gateway on 127.0.0.1 -> local MCP servers
```

The local tools are stdio MCP servers, which Claude's mobile app can't reach directly. The tray app runs them behind one HTTP endpoint and opens the tunnel without any inbound ports. Only your GitHub account can sign in.

Claude doesn't see those servers' own tools. It sees a short, curated list with generic names and descriptions written for an agent, defined in [toolkit.py](src/claudeplay/toolkit.py). Everything else the servers offer is hidden and can't be called, even by name.

The laptop has to be on, awake and online, though a locked screen should be fine. Calling the tools from voice mode, and using the laptop and web tools while it's locked, haven't been tested end to end yet.

## Tools

There are 28 tools in 8 sections. A section's tools only appear while its backend is enabled and running. The date and time tool and `web_fetch` are built into claudeplay, so they're always there.

### Date and time

It follows the laptop's clock and time zone, which may differ from where you are.

| Tool | What it does | Arguments |
|---|---|---|
| `get_current_timestamp` | Today's date as `YYYY-MM-DD`, plus the day of the week, month, day and year, and the current time to the second with the UTC offset and time zone name | None |

### Journal

Daily entries in the Obsidian vault, one per day. Backend: obsidian-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `journal_list_month` | Lists which days in a month have an entry | `year`, `month` |
| `journal_read` | Reads one day's entry, and says so if there isn't one | `date` |
| `journal_append` | Adds a note to the end of today's entry, creating it if needed. Never changes what's already there | `text` |

### Projects

Folders of notes for ongoing work. Backend: obsidian-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `projects_list` | Lists projects | None |
| `projects_files` | Lists the files in a project, with their paths | `project` |
| `projects_create` | Creates an empty project | `project` |
| `projects_read` | Reads a file in a project | `file_path` |
| `projects_write` | Creates a file in an existing project, or overwrites a whole file | `file_path`, `content` |

`projects_read` and `projects_write` refuse any path outside a project. `projects_write` also refuses a project that doesn't exist yet, so a mistyped name can't create a new one.

### Wiki

Standalone articles. Read-only. Backend: obsidian-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `wiki_list` | Lists articles, with their paths | None |
| `wiki_read` | Reads an article, and refuses any path outside the wiki | `file_path` |

### Tasks

Microsoft To Do lists, tasks and steps, the checklist inside a task. Backend: todo-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `tasks_get_lists` | Lists the task lists, with their ids | None |
| `tasks_get_tasks` | Lists the tasks in one list, open tasks by default. Doesn't include steps | `list_id`, `status`, `limit` |
| `tasks_get_due_today` | Finds open tasks due today in your main lists. Leaves out overdue tasks | None |
| `tasks_get_completed_between` | Finds tasks completed between two dates, grouped by list and day. Checks your main lists unless given others | `start_date`, `end_date`, `list_ids` |
| `tasks_add_task` | Adds a task, optionally with a due date, notes, importance or recurrence | `title`, `list_id`, `due_date`, `body_text`, `importance`, `recurrence_type`, `recurrence_interval`, `recurrence_days_of_week`, `recurrence_day_of_month` |
| `tasks_update_task` | Changes a task, or removes its due date or notes. Only the arguments given change | `task_id`, `list_id`, `title`, `due_date`, `clear_due_date`, `body_text`, `importance`, `status`, `recurrence_type`, `recurrence_interval`, `recurrence_days_of_week`, `recurrence_day_of_month`, `remove_recurrence` |
| `tasks_complete_task` | Marks a task as completed | `task_id`, `list_id` |
| `tasks_get_steps` | Lists a task's steps, and whether each is checked off | `task_id`, `list_id` |
| `tasks_add_step` | Adds a step to the end of a task | `task_id`, `list_id`, `name` |
| `tasks_update_step` | Renames a step, or checks or unchecks it | `item_id`, `task_id`, `list_id`, `name`, `is_checked` |
| `tasks_complete_step` | Checks a step off | `item_id`, `task_id`, `list_id` |

The `[tasks]` section of your config sets the main lists, with `due_today`. `tasks_get_due_today` only appears when it's set, and `tasks_get_completed_between` uses it as its default. Ids in `common_lists` are added to the `tasks_get_lists` description so Claude can often skip that call. There are no tools for deleting tasks, steps or lists.

### Bookmarks

Pinboard bookmarks. Backend: pinboard-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `bookmarks_list` | Lists bookmarks, newest first, filtered by tag and date. Returns 50 by default, and there's no keyword search | `tags`, `start_date`, `end_date`, `limit` |
| `bookmarks_add` | Saves a new bookmark, and fails if the URL is already saved | `url`, `title`, `description`, `tags`, `private`, `toread` |
| `bookmarks_update` | Changes a bookmark, found by its URL. Only the arguments given change | `url`, `title`, `description`, `tags`, `private`, `toread` |

The server instructions tell Claude to mark new bookmarks private unless you ask otherwise, but that's only an instruction. The backend's own default is public.

### Laptop

Files and a shell on the laptop, acting as you. Nothing with a window or a prompt will work, because the laptop is usually locked. Backend: windows-mcp.

| Tool | What it does | Arguments |
|---|---|---|
| `pc_files` | Reads, writes, copies, moves, deletes, lists, searches or gets info on files, using absolute paths | `mode`, `path`, `destination`, `content`, `pattern`, `recursive`, `append`, `overwrite`, `offset`, `limit`, `show_hidden` |
| `pc_shell` | Runs a PowerShell command and returns its output | `command`, `timeout` |

These two can reach the whole laptop, including the vault, so the project and wiki limits don't apply to them. See [Security](docs/security.md) for the accepted risks.

### Web

Built into claudeplay, using Playwright and the laptop's Edge.

| Tool | What it does | Arguments |
|---|---|---|
| `web_fetch` | Gets the title and visible text of a web page, after its JavaScript runs | `url` |

It loads the page in a fresh headless browser that isn't signed in to anything, so it works while the laptop is locked and pages behind a login come back as the login page. Each fetch takes a few seconds, and some sites block it. The text is cut off at 100,000 characters.

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
python -m claudeplay install              # start the tray at logonuv run --extra test python -m pytest      # run the tests
```

The config and all secrets live in `%LOCALAPPDATA%\claudeplay\config.toml`, outside this repo. Start from [config.example.toml](config.example.toml).
