'''a stdio backend with the same tool names and arguments as obsidian-mcp, backed by memory'''

from fastmcp import FastMCP

mcp = FastMCP('fake-obsidian')
journal: dict[str, str] = {'2026-10-01': 'went for a run'}
files: dict[str, str] = {
    'projects/garage/plan.md': 'shelves',
    'wiki/docker networking.md': 'bridges',
    'journal/2026/10/2026-10-01.md': 'went for a run',
    'projects/loose.md': 'not in a project',
}
TODAY = '2026-10-29'


@mcp.tool()
def get_current_date() -> dict:
    return {'formatted': TODAY, 'human': 'Thursday October 29, 2026'}


@mcp.tool()
def list_journal_entries_by_year_and_month(year: str, month: str) -> list:
    prefix = f'{year}-{month}-'
    return [{'path': f'journal/{year}/{month}/{d}.md', 'name': f'{d}.md'} for d in sorted(journal) if d.startswith(prefix)]


@mcp.tool()
def read_journal_entry(date: str) -> dict:
    return {'path': f'journal/{date}.md', 'exists': date in journal, 'content': journal.get(date, '')}


@mcp.tool()
def append_to_todays_journal(text: str) -> dict:
    created = TODAY not in journal
    journal[TODAY] = (journal.get(TODAY, '') + '\n\n' + text).strip()
    return {'success': True, 'path': f'journal/{TODAY}.md', 'created': created}


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
