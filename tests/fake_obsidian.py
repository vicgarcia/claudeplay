'''a stdio backend with the same tool names and arguments as obsidian-mcp, backed by memory'''

from fastmcp import FastMCP

mcp = FastMCP('fake-obsidian')
journal: dict[str, str] = {'2026-10-01': 'went for a run'}
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
def write_file(file_path: str, content: str) -> dict:
    ''' not in the catalog: must never be reachable through the gateway '''
    return {'success': True}


if __name__ == '__main__':
    mcp.run(transport='stdio', show_banner=False)
