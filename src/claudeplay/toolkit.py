'''the claudeplay toolkit: the curated tool surface presented to claude, over the mounted backends'''

from collections.abc import Sequence
from dataclasses import dataclass, field

from fastmcp.server.transforms import GetToolNext, Transform
from fastmcp.tools import Tool
from fastmcp.tools.tool_transform import ArgTransform
from mcp.types import ToolAnnotations

NAME = 'claudeplay'

INSTRUCTIONS = '''
claudeplay is a personal productivity toolkit: journal and notes now, tasks and bookmarks later.
the user often talks to it by voice, sometimes while driving. keep answers short and spoken-friendly:
no tables, no long lists, summarise instead of reading raw content back. when you write something,
say briefly what was written and where.
'''.strip()


@dataclass(frozen=True)
class Entry:
    ''' one presented tool: its public name, the backend tool it calls, and how it is described '''
    name: str
    source: str
    description: str
    read_only: bool
    args: dict[str, str] = field(default_factory=dict)


CATALOG: tuple[Entry, ...] = (
    Entry(
        name='get_date',
        source='obsidian_get_current_date',
        description="Today's date, as YYYY-MM-DD and spelled out. Use it to resolve 'today', 'yesterday' or 'last tuesday' before other date-based tools.",
        read_only=True,
    ),
    Entry(
        name='journal_list_month',
        source='obsidian_list_journal_entries_by_year_and_month',
        description='List which days have a journal entry in a given month. Use it to find entries before reading them.',
        read_only=True,
        args={
            'year': 'four-digit year, e.g. "2026"',
            'month': 'two-digit month, e.g. "03" for march',
        },
    ),
    Entry(
        name='journal_read',
        source='obsidian_read_journal_entry',
        description="Read the journal entry for one day. Returns exists=false if there is no entry. Summarise it rather than reading it out verbatim.",
        read_only=True,
        args={'date': 'the day, as YYYY-MM-DD'},
    ),
    Entry(
        name='journal_append',
        source='obsidian_append_to_todays_journal',
        description="Add a note to the end of today's journal entry, creating the entry if needed. Never changes what is already there.",
        read_only=False,
        args={'text': 'the note to add, in the words the user wants recorded'},
    ),
)


def _annotations(entry: Entry) -> ToolAnnotations:
    # nothing in the catalog reaches outside the user's own data
    return ToolAnnotations(
        title=entry.name.replace('_', ' '),
        read_only_hint=entry.read_only,
        destructive_hint=False,
        open_world_hint=False,
    )


class Catalog(Transform):
    ''' exposes only catalogued tools, renamed and re-described; everything else, including prompts and resources, is hidden '''

    def __init__(self, entries: Sequence[Entry] = CATALOG):
        names = [e.name for e in entries]
        if len(set(names)) != len(names):
            raise ValueError('duplicate tool names in catalog')
        self._by_source = {e.source: e for e in entries}
        self._by_name = {e.name: e for e in entries}

    def _present(self, tool: Tool, entry: Entry) -> Tool:
        # only describe arguments the backend actually has, so a changed backend does not break the gateway
        known = set(tool.parameters.get('properties', {}))
        return Tool.from_tool(
            tool,
            name=entry.name,
            description=entry.description,
            annotations=_annotations(entry),
            transform_args={a: ArgTransform(description=d) for a, d in entry.args.items() if a in known},
        )

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        presented = [self._present(t, self._by_source[t.name]) for t in tools if t.name in self._by_source]
        order = {e.name: i for i, e in enumerate(self._by_name.values())}
        return sorted(presented, key=lambda t: order[t.name])

    async def get_tool(self, name: str, call_next: GetToolNext, *, version=None) -> Tool | None:
        entry = self._by_name.get(name)
        if entry is None:
            return None
        tool = await call_next(entry.source, version=version)
        return self._present(tool, entry) if tool is not None else None

    async def list_resources(self, resources):
        return []

    async def get_resource(self, uri, call_next, *, version=None):
        return None

    async def list_resource_templates(self, templates):
        return []

    async def get_resource_template(self, uri, call_next, *, version=None):
        return None

    async def list_prompts(self, prompts):
        return []

    async def get_prompt(self, name, call_next, *, version=None):
        return None
