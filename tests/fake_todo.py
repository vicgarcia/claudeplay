'''a stdio backend with the same task tool names and arguments as todo-mcp, backed by memory'''

from fastmcp import FastMCP

mcp = FastMCP('fake-todo')


@mcp.tool()
def get_lists() -> dict:
    return {'success': True, 'lists': [{'list_id': 'id-chores', 'name': 'Chores'}]}


@mcp.tool()
def get_tasks_due_today(list_ids: list[str]) -> dict:
    return {'success': True, 'list_ids': list_ids}


if __name__ == '__main__':
    mcp.run(transport='stdio', show_banner=False)
