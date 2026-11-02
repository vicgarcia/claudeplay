# Toolkit

Claude doesn't see the backends. It sees one server called `claudeplay` with a short, curated list of tools. That list is `CATALOG` in [toolkit.py](../src/claudeplay/toolkit.py), and it's the only thing that decides what Claude can call.

## Current tools

| Tool | What it does | Backend tool |
|---|---|---|
| `get_todays_date` | Today's date, day of the week, month, day and year, in the laptop's time zone | built into claudeplay |
| `get_current_timestamp` | The current time to the second, with the UTC offset and time zone name | built into claudeplay |
| `journal_list_month` | Which days in a month have an entry | obsidian `list_journal_entries_by_year_and_month` |
| `journal_read` | Reads one day's entry | obsidian `read_journal_entry` |
| `journal_append` | Adds a note to the end of today's entry | obsidian `append_to_todays_journal` |
| `projects_list` | Lists projects | obsidian `list_projects` |
| `projects_files` | Lists the files in a project | obsidian `list_project_content` |
| `projects_create` | Creates an empty project | obsidian `create_project` |
| `projects_read` | Reads a file in a project | obsidian `read_file`, limited by claudeplay |
| `projects_write` | Creates a file in an existing project, or overwrites a whole one | obsidian `write_file`, limited by claudeplay |
| `wiki_list` | Lists wiki articles | obsidian `list_wiki` |
| `wiki_read` | Reads a wiki article. There's no tool for writing to the wiki | obsidian `read_file`, limited by claudeplay |
| `tasks_lists` | Lists task lists with their ids | todo `get_lists` |
| `tasks_list` | Lists the tasks in one list | todo `get_tasks` |
| `tasks_due_today` | Finds open tasks due today in the lists set in `[tasks]`. Takes no arguments. Only appears when `due_today` is set | todo `get_tasks_due_today` |
| `tasks_add` | Adds a task | todo `create_task` |
| `tasks_update` | Changes a task | todo `update_task` |
| `tasks_complete` | Marks a task as completed | todo `complete_task` |
| `bookmarks_list` | Lists bookmarks, filtered by tag and date. There is no keyword search | pinboard `get_bookmarks` |
| `bookmarks_add` | Saves a new bookmark, and fails if the URL is already saved. The server instructions tell Claude to mark bookmarks private unless you ask otherwise, but the backend's own default is public | pinboard `add_bookmark` |
| `bookmarks_update` | Changes a bookmark, found by its URL | pinboard `update_bookmark` |
| `pc_files` | Reads, writes, copies, moves, deletes, lists, searches or gets info on files. Use absolute paths | windows `FileSystem` |
| `pc_shell` | Runs a PowerShell command | windows `PowerShell` |
| `web_fetch` | Gets a page's text. Headless by default, which works while locked but can't run JavaScript. With `use_dom`, reads the front tab of an open browser instead, which needs the laptop unlocked | windows `Scrape` |

The `[tasks]` section of `config.toml` holds your account's lists. `common_lists` maps list names to ids, which are added to the `tasks_lists` description so Claude can often skip that call. `due_today` names which of them `tasks_due_today` covers. They live in the config, not the repo, because they're specific to your account. To find an id, call `tasks_lists`.

claudeplay enforces the project and wiki limits, in `PathGuard` in `toolkit.py`, because obsidian-mcp only offers general `read_file` and `write_file` tools. `projects_read` and `projects_write` refuse any path outside a project, `projects_write` also refuses a project that doesn't exist yet, and `wiki_read` refuses any path outside the wiki. The check reads the path's text, so a link inside the vault could still lead elsewhere in the vault. The general tools can't be called directly. `pc_files` and `pc_shell` are separate and can still reach the whole laptop, including the vault.

A tool only appears when its backend is enabled and running. Everything else a backend offers, including prompts and resources, is hidden and can't be called even by name.

## What Claude actually receives

The backends' docstrings never reach Claude. FastMCP builds a tool listing from each backend function, and the gateway replaces most of it before Claude sees it. For `journal_read`:

| | From obsidian-mcp | What Claude gets |
|---|---|---|
| Name | `read_journal_entry` | `journal_read` |
| Description | Full docstring, including `Args:` and `Returns:` | `Read the journal entry for one day. Returns exists=false if there is no entry.` |
| `date` argument | A string with no description | A string described as `the day, as YYYY-MM-DD` |
| Annotations | None | read-only, non-destructive, closed-world |

Claude gets these, in rough order of how much they steer it:

1. **Which tools exist.** Fewer, clearly distinct tools lead to better choices.
2. **Tool names.** A domain prefix plus a plain verb.
3. **Descriptions.** When to use the tool, what it returns, and how it relates to other tools.
4. **Argument names, types and descriptions.**
5. **Server instructions** (`INSTRUCTIONS`), sent once on connecting, for ideas that span tools and your common workflows. Keep these about how to use the tools, not how Claude should sound.
6. **Results and error messages.** These go straight into the conversation, so a clear error teaches Claude as well as a description does.

Annotations matter mainly to the app, which may use them when deciding whether to ask before running a tool.

## Adding a tool

1. Find the backend tool's name. It's `<server>_<tool>`, and `serve --raw` lists them all ([how](operations.md#testing-without-the-public-endpoint)).
2. Add an `Entry` to `CATALOG`:

   ```python
   Entry(
       name='wiki_list',
       source='obsidian_list_wiki',
       description='List the wiki articles, with their paths.',
       read_only=True,
   ),
   ```

3. **Restart** in the tray, then reconnect the connector.

| `Entry` field | Purpose |
|---|---|
| `name` | What Claude calls it |
| `source` | The backend tool, as `<server>_<tool>` |
| `description` | Replaces the backend's docstring |
| `read_only` | True if it changes nothing |
| `args` | Descriptions for arguments, keyed by name. Names the backend doesn't have are ignored |
| `hide` | Arguments Claude can't see or set, so the backend's default applies. They must be optional |
| `fixed` | Arguments Claude can't see or set, always sent with the value given here |
| `defaults` | Visible arguments with a different default from the backend's |
| `guard` | A `PathGuard` limiting `file_path` to one part of the vault |
| `destructive` | True if it can delete or overwrite |
| `open_world` | True if it reaches beyond your own data |

## What belongs where

The catalog mostly changes how a tool is presented. It can rename, describe, hide, filter or limit a tool's paths, but it can't change what a tool returns.

| You want to | Do it in |
|---|---|
| Rename, describe, or hide a tool or argument | `toolkit.py` |
| Change behaviour or results | The backend's repo |
| Limit a general backend tool for your own use | A `guard` in `toolkit.py`, leaving the backend general |
| Combine two backends in one tool | A new tool in claudeplay. There are none so far |

## Adding a backend

Any stdio MCP server can be added:

1. Add a `[servers.<name>]` section to `config.toml` with its `command`, `args` and `env`. Pin the version if it's downloaded at run time.
2. **Quit** and start the tray again, so its menu picks up the new server.
3. Add catalog entries. Without them, Claude sees nothing from it.

Backends are assumed to use the older MCP 1.x protocol, so the gateway connects to all of them in `legacy` mode.
