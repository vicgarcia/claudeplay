'''a stdio backend with the same task tool names and arguments as todo-mcp, backed by memory'''

from fastmcp import FastMCP

mcp = FastMCP('fake-todo')


@mcp.tool()
def get_lists() -> dict:
    return {'success': True, 'lists': [{'list_id': 'id-chores', 'name': 'Chores'}]}


@mcp.tool()
def get_tasks_due_today(list_ids: list[str]) -> dict:
    return {'success': True, 'list_ids': list_ids}


@mcp.tool()
def get_tasks_by_completed_date_range(list_ids: list[str], start_date: str, end_date: str | None = None) -> dict:
    return {'success': True, 'list_ids': list_ids, 'start_date': start_date, 'end_date': end_date}


@mcp.tool()
def get_steps(task_id: str, list_id: str) -> dict:
    return {'success': True, 'steps': [{'item_id': 'step-1', 'name': 'buy primer', 'is_checked': False}], 'task_id': task_id}


if __name__ == '__main__':
    mcp.run(transport='stdio', show_banner=False)
