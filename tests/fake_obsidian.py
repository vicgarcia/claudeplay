'''a stdio backend with the same tool names and arguments as obsidian-mcp, backed by memory'''

from fastmcp import FastMCP

FAKE_INSTRUCTIONS = 'fake obsidian instructions: call get_todays_date, then add_note_to_journal_entry.'
mcp = FastMCP('fake-obsidian', instructions=FAKE_INSTRUCTIONS)
journal: dict[str, str] = {'2026-10-01': 'went for a run'}
files: dict[str, str] = {
    'projects/garage/plan.md': 'shelves',
    'wiki/docker networking.md': 'bridges',
    'journal/2026/10/2026-10-01.md': 'went for a run',
    'projects/loose.md': 'not in a project',
}
TODAY = '2026-10-29'


@mcp.tool()
def get_todays_date() -> dict:
    ''' today's date in the user's time zone. '''
    return {'date': TODAY}


@mcp.tool()
def list_journal_entries_by_year_and_month(year: str, month: str) -> list:
    prefix = f'{year}-{month}-'
    return [{'path': f'journal/{year}/{month}/{d}.md', 'name': f'{d}.md'} for d in sorted(journal) if d.startswith(prefix)]


@mcp.tool()
def read_journal_entry(date: str) -> dict:
    return {'path': f'journal/{date}.md', 'exists': date in journal, 'content': journal.get(date, '')}


@mcp.tool()
def append_to_journal_entry(text: str, date: str | None = None) -> dict:
    day = date or TODAY
    created = day not in journal
    journal[day] = journal.get(day, '') + text
    return {'success': True, 'path': f'journal/{day}.md', 'created': created}


@mcp.tool()
def prepend_to_journal_entry(text: str, date: str | None = None) -> dict:
    day = date or TODAY
    created = day not in journal
    journal[day] = text + journal.get(day, '')
    return {'success': True, 'path': f'journal/{day}.md', 'created': created}


@mcp.tool()
def add_note_to_journal_entry(text: str, date: str | None = None) -> dict:
    day = date or TODAY
    created = day not in journal
    journal[day] = (journal.get(day) or '\n\n# Daily Notes\n') + f'{text}\n{TODAY} 09:00\n\n'
    return {'success': True, 'path': f'journal/{day}.md', 'created': created, 'timestamp': f'{TODAY} 09:00'}


@mcp.tool()
def write_journal_entry(content: str, date: str | None = None) -> dict:
    ''' not in the catalog: overwrites a whole entry '''
    journal[date or TODAY] = content
    return {'success': True}


@mcp.tool()
def list_projects() -> list:
    return [{'path': 'projects/garage', 'name': 'garage'}]


@mcp.tool()
def list_project_content(project: str) -> list:
    return [{'path': p, 'name': p.rsplit('/', 1)[1]} for p in sorted(files) if p.startswith(f'projects/{project}/')]


@mcp.tool()
def create_project(project: str) -> dict:
    return {'success': True}


@mcp.tool()
def list_wiki() -> list:
    return [{'path': p, 'name': p.rsplit('/', 1)[1]} for p in sorted(files) if p.startswith('wiki/')]


@mcp.tool()
def read_file(file_path: str) -> dict:
    return {'content': files[file_path]}


@mcp.tool()
def write_file(file_path: str, content: str) -> dict:
    files[file_path] = content
    return {'success': True}


@mcp.tool()
def start_daily_notes_session() -> str:
    ''' not in the catalog: must never be reachable through the gateway '''
    return 'be curious'


if __name__ == '__main__':
    mcp.run(transport='stdio', show_banner=False)
