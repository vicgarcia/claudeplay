# Toolkit

Claude doesn't see your servers directly. It sees one server called `claudeplay` with the tools `toolkit.yaml` exposes. That file, in the same folder as `config.yaml`, is the only thing that decides what Claude can call. [toolkit.example.yaml](../toolkit.example.yaml) is a complete, commented example, and `claudeplay check` validates your file.

## Passthrough by default

A tool you list with only a `source` reaches Claude exactly as its server defines it: the same name, description, argument names and descriptions, and annotations. The server's own instructions go to Claude too. The point is that a server's text is written to go with its own tools, so it stays correct without a second copy to maintain. When the server is upgraded, Claude sees the upgrade, which is the behaviour you want from servers you trust.

```yaml
servers:
  notes:
    tools:
      - source: read_file
      - source: write_file
```

Change as little as you need. Everything below is optional, per tool or per server.

## Exposing tools

| Setting | What it does |
|---|---|
| `tools` | A list of the tools to expose, in the order Claude sees them. Each has a `source`, the server's own tool name |
| `expose_all: true` | Exposes every tool the server has, unchanged and under its own name, after the ones you list. Any tools you list are then changes to some of them. New tools in a server appear on their own, so use this for servers you trust to add only safe tools |

A server named in `config.yaml` with nothing listed and no `expose_all` exposes nothing, and a warning says so. A tool the server has but you don't expose, including its prompts and resources, is hidden and can't be called even by name.

## Changing a tool

| Field | What it does |
|---|---|
| `name` | The name Claude sees; left out, it's the server's name. Rename only when the server's text doesn't refer to its tools by name, because Claude would be told to call tools by names it can't see |
| `description` | Replaces the server's description |
| `description_append` | Added after the description, whichever it is. The place for what only you know, such as which lists are your main ones |
| `read_only`, `destructive`, `open_world` | Annotations: the tool only reads, can overwrite or delete, or reaches beyond your own data. Left out, the server's own are used. Many servers set none, and then Claude may ask before it uses a tool |
| `args` | Argument name to a description, replacing the server's |
| `hide` | Arguments Claude can't see or set, so the server's default applies. They must be optional |
| `fixed` | Arguments Claude can't see or set, always sent with the value given here |
| `defaults` | Visible arguments with a different default from the server's |

YAML anchors (`&name`, `*name`) avoid repeating a value, such as a set of list ids used by two tools.

## Server instructions

Each server's own instructions, which it sends when a client connects, are read when the gateway starts that server and passed to Claude. A session that connects before a server has started gets that server's part the next time it connects.

| Setting | What it does |
|---|---|
| `label` | Says what the server is, in the heading above its instructions |
| `instructions_append` | Added after the server's instructions |
| `instructions` | Replaces the server's instructions; an empty string sends none |
| top-level `instructions` | Sent first, for ideas that span servers |

Claude receives the top level, then each enabled server's, in the order of `config.yaml`. Each server's part starts with a heading naming it, `## notes: the user's notes vault` with a `label` or `## notes` without, so Claude can tell which part is about which server. The tools themselves don't say which server they come from, so the top level can use these names to tie the user's words to a server. A disabled server, or one that exposes nothing or has no instructions, adds nothing. Keep these about how to use the tools, not how Claude should sound.

## Checks at startup

Both files are validated, and an unknown key or a wrong type is an error that names the file and the key, never the value. A server named in `toolkit.yaml` must be in `config.yaml`, and two tools can't share a name.

When the gateway starts a server it also compares what you listed with what the server actually offers. A listed tool the server lacks, an argument named in `args`, `hide`, `fixed` or `defaults` that the tool doesn't take, or an unlisted tool whose name another tool already uses, marks that server `failed`, with the tool or argument named. This catches a renamed tool in an upgraded server, which would otherwise just vanish from Claude's list.

## What Claude actually receives

FastMCP builds a tool listing from each server's functions, and the gateway passes it on with the changes you list. Claude is steered, roughly in this order, by:

1. **Which tools exist.** Fewer, clearly distinct tools lead to better choices.
2. **Tool names.**
3. **Descriptions.** When to use the tool, what it returns, and how it relates to other tools.
4. **Argument names, types and descriptions.**
5. **Server instructions**, sent once on connecting, for ideas that span tools and common workflows.
6. **Results and error messages.** These go straight into the conversation.

Annotations matter mainly to the app, which may use them to decide whether to ask before running a tool.

## What belongs where

The toolkit only changes how a tool is presented. It can pick, rename, describe, hide and fix arguments of a tool, but it can't change what a tool returns or limit what it can do.

| You want to | Do it in |
|---|---|
| Pick, describe or annotate a tool or argument | `toolkit.yaml` |
| Change behaviour or results, or limit what a tool may touch | The server's own repo |
| Make a server's own text correct for Claude | The server's repo, so it stays right everywhere it's used |

claudeplay checks no paths and holds no logic about any server. A server that exposes general file tools exposes them to Claude as they are, so put the limits you want in that server.

## Adding a server

Any stdio MCP server can be added:

1. Add it under `servers:` in `config.yaml` with its `command`, `args` and `env`. Pin the version if it's downloaded at run time.
2. Add a section for it in `toolkit.yaml`: `expose_all: true`, or the tools you want.
3. **Quit** and start the tray again, so its menu picks up the new server.

Servers are assumed to use the older MCP 1.x protocol, so the gateway connects to all of them in `legacy` mode.
