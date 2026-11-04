import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from claudeplay import config, gateway, toolkit

FAKE_OBSIDIAN = str(Path(__file__).parent / 'fake_obsidian.py')
EXPECTED = ['get_current_timestamp', 'journal_list_month', 'journal_read', 'journal_append', 'projects_list', 'projects_files',
            'projects_create', 'projects_read', 'projects_write', 'wiki_list', 'wiki_read', 'web_fetch']
# the tools built into the gateway, there with no backends at all
BUILT_IN = ['get_current_timestamp', 'web_fetch']


def obsidian() -> config.ServerConfig:
    return config.ServerConfig(name='obsidian', command=sys.executable, args=(FAKE_OBSIDIAN,))


async def session(cfg, steps):
    ''' run steps(client) against the curated gateway '''
    gw, _ = gateway.build(cfg)
    async with Client(gw, mode='legacy') as client:
        return await steps(client)


def run(cfg, steps):
    return asyncio.run(session(cfg, steps))


def payload(result) -> dict:
    return json.loads(result.content[0].text)


def test_only_catalogued_tools_are_exposed_in_catalog_order():
    async def steps(client):
        return [t.name for t in await client.list_tools()]

    assert run(config.GatewayConfig(servers=(obsidian(),)), steps) == EXPECTED


def test_descriptions_annotations_and_argument_docs_come_from_the_catalog():
    async def steps(client):
        return {t.name: t for t in await client.list_tools()}

    tools = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    entries = {e.name: e for e in toolkit.catalog(config.TasksConfig())}
    for name, tool in tools.items():
        assert tool.description == entries[name].description
        assert tool.annotations.read_only_hint is entries[name].read_only
        assert tool.annotations.destructive_hint is entries[name].destructive
    assert tools['journal_read'].input_schema['properties']['date']['description'] == 'the day, as YYYY-MM-DD'
    assert tools['journal_read'].input_schema['required'] == ['date']


def test_calls_route_to_the_backend():
    async def steps(client):
        month = payload(await client.call_tool('journal_list_month', {'year': '2026', 'month': '10'}))
        appended = payload(await client.call_tool('journal_append', {'text': 'saw a heron'}))
        today = payload(await client.call_tool('journal_read', {'date': '2026-10-29'}))
        return month, appended, today

    month, appended, today = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert [e['name'] for e in month] == ['2026-10-01.md']
    assert appended['created'] is True
    assert today == {'path': 'journal/2026-10-29.md', 'exists': True, 'content': 'saw a heron'}


def test_clock_tool_works_with_no_backends_and_does_not_use_obsidian():
    async def steps(client):
        names = [t.name for t in await client.list_tools()]
        stamp = payload(await client.call_tool('get_current_timestamp', {}))
        return names, stamp

    names, stamp = run(config.GatewayConfig(servers=()), steps)
    assert names == BUILT_IN
    assert set(stamp) == {'date', 'day_of_week', 'month', 'day', 'year', 'timestamp', 'timezone'}
    assert stamp['timestamp'].startswith(stamp['date'])


def test_listed_paths_work_with_the_read_and_write_tools():
    async def steps(client):
        project = payload(await client.call_tool('projects_files', {'project': 'garage'}))
        wiki = payload(await client.call_tool('wiki_list', {}))
        article = payload(await client.call_tool('wiki_read', {'file_path': wiki[0]['path']}))
        await client.call_tool('projects_write', {'file_path': project[0]['path'], 'content': 'more shelves'})
        plan = payload(await client.call_tool('projects_read', {'file_path': project[0]['path']}))
        return article, plan

    article, plan = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert article == {'content': 'bridges'}
    assert plan == {'content': 'more shelves'}


def test_general_file_tools_are_only_reachable_through_guards():
    general = [e for e in toolkit.CATALOG if e.source in ('obsidian_read_file', 'obsidian_write_file')]
    assert {e.name for e in general} == {'projects_read', 'projects_write', 'wiki_read'}
    assert all(e.guard for e in general)


OUTSIDE_A_PROJECT = ['journal/2026/10/2026-10-01.md', 'wiki/docker networking.md', 'projects/loose.md', 'projects',
                     'projects/garage/../../journal/2026/10/2026-10-01.md', '/etc/passwd', 'C:/Windows/system.ini',
                     'projects\\garage\\..\\..\\journal\\2026\\10\\2026-10-01.md', 'projects/garage/plan.md:hidden']


@pytest.mark.parametrize('path', OUTSIDE_A_PROJECT)
def test_project_tools_refuse_paths_outside_a_project(path):
    async def steps(client):
        read = await client.call_tool('projects_read', {'file_path': path}, raise_on_error=False)
        write = await client.call_tool('projects_write', {'file_path': path, 'content': 'overwritten'}, raise_on_error=False)
        journal = payload(await client.call_tool('journal_read', {'date': '2026-10-01'}))
        return read, write, journal

    read, write, journal = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert read.is_error and write.is_error
    assert journal['content'] == 'went for a run'


@pytest.mark.parametrize('path', ['projects/garage/plan.md', 'journal/2026/10/2026-10-01.md', 'wiki', 'wiki/../journal/2026/10/2026-10-01.md'])
def test_wiki_read_refuses_paths_outside_the_wiki(path):
    async def steps(client):
        return await client.call_tool('wiki_read', {'file_path': path}, raise_on_error=False)

    assert run(config.GatewayConfig(servers=(obsidian(),)), steps).is_error


def test_projects_write_will_not_create_a_project():
    async def steps(client):
        bad = await client.call_tool('projects_write', {'file_path': 'projects/typo/plan.md', 'content': 'x'}, raise_on_error=False)
        new = await client.call_tool('projects_write', {'file_path': 'projects/garage/notes/new.md', 'content': 'hello'})
        return bad, new, payload(await client.call_tool('projects_read', {'file_path': 'projects/garage/notes/new.md'}))

    bad, new, read = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert bad.is_error and 'project not found' in bad.content[0].text
    assert not new.is_error
    assert read == {'content': 'hello'}


def test_guarded_tools_describe_their_arguments():
    async def steps(client):
        return {t.name: t for t in await client.list_tools()}

    tools = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert tools['wiki_read'].input_schema['properties']['file_path']['description'] == 'the path, from wiki_list'
    assert set(tools['projects_write'].input_schema['properties']) == {'file_path', 'content'}
    assert tools['projects_write'].input_schema['required'] == ['file_path', 'content']


def test_wiki_tools_are_read_only():
    assert all(e.read_only for e in toolkit.CATALOG if e.name.startswith('wiki_'))


@pytest.mark.parametrize('name', ['read_file', 'write_file', 'obsidian_write_file', 'obsidian_get_current_date', 'start_daily_notes_session'])
def test_uncatalogued_and_raw_names_are_not_callable(name):
    async def steps(client):
        with pytest.raises(Exception):
            await client.call_tool(name, {})
        return True

    assert run(config.GatewayConfig(servers=(obsidian(),)), steps)


def test_server_presents_itself_as_claudeplay():
    async def steps(client):
        return client.initialize_result

    result = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert result.server_info.name == 'claudeplay'
    assert 'productivity toolkit' in result.instructions


def test_disabled_backend_simply_removes_its_tools():
    off = config.ServerConfig(name='obsidian', command=sys.executable, args=(FAKE_OBSIDIAN,), enabled=False)

    async def steps(client):
        return [t.name for t in await client.list_tools()]

    assert run(config.GatewayConfig(servers=(off,)), steps) == BUILT_IN


def test_catalog_rejects_duplicate_names():
    entry = toolkit.Entry(name='x', source='a_x', description='d', read_only=True)
    with pytest.raises(ValueError):
        toolkit.Catalog([entry, entry])


def test_catalog_names_are_valid_for_claude():
    for entry in toolkit.CATALOG:
        assert len(entry.name) <= 64 and entry.name.replace('_', '').isalnum() and entry.name.islower()


def test_tasks_tools_route_to_todo_and_never_delete():
    tasks = [e for e in toolkit.CATALOG if e.name.startswith('tasks_')]
    assert [e.name for e in tasks] == ['tasks_get_lists', 'tasks_get_tasks', 'tasks_get_completed_between', 'tasks_add_task', 'tasks_update_task',
                                       'tasks_complete_task', 'tasks_get_steps', 'tasks_add_step', 'tasks_update_step', 'tasks_complete_step']
    assert all(e.source.startswith('todo_') and 'delete' not in e.source for e in tasks)


TASKS = config.TasksConfig(common_lists={'Chores': 'id-chores', 'Health': 'id-health', 'Grocery': 'id-grocery'},
                           due_today=('Chores', 'Health'))


def todo_config(tasks: config.TasksConfig) -> config.GatewayConfig:
    todo = config.ServerConfig(name='todo', command=sys.executable, args=(str(Path(__file__).parent / 'fake_todo.py'),))
    return config.GatewayConfig(servers=(todo,), tasks=tasks)


def test_common_list_ids_are_published_with_a_note_about_other_lists():
    async def steps(client):
        return {t.name: t for t in await client.list_tools()}, client.initialize_result

    tools, result = run(todo_config(TASKS), steps)
    description = tools['tasks_get_lists'].description
    for name, list_id in TASKS.common_lists.items():
        assert f'{name} = {list_id}' in description
    assert 'other lists' in description
    assert 'tasks_get_lists description' in result.instructions


def test_tasks_due_today_always_uses_the_configured_lists():
    async def steps(client):
        tool = next(t for t in await client.list_tools() if t.name == 'tasks_get_due_today')
        ok = payload(await client.call_tool('tasks_get_due_today', {}))
        bad = await client.call_tool('tasks_get_due_today', {'list_ids': ['id-other']}, raise_on_error=False)
        return tool, ok, bad

    tool, ok, bad = run(todo_config(TASKS), steps)
    assert ok['list_ids'] == ['id-chores', 'id-health']
    assert not tool.input_schema.get('properties')
    assert 'Chores, Health' in tool.description and 'Grocery' not in tool.description
    assert bad.is_error


def test_completed_search_defaults_to_the_main_lists_and_takes_others():
    async def steps(client):
        tool = next(t for t in await client.list_tools() if t.name == 'tasks_get_completed_between')
        main = payload(await client.call_tool('tasks_get_completed_between', {'start_date': '2026-11-01'}))
        other = payload(await client.call_tool('tasks_get_completed_between', {'start_date': '2026-11-01', 'list_ids': ['id-grocery']}))
        return tool, main, other

    tool, main, other = run(todo_config(TASKS), steps)
    assert main['list_ids'] == ['id-chores', 'id-health']
    assert other['list_ids'] == ['id-grocery']
    assert tool.input_schema['required'] == ['start_date']
    assert 'Chores, Health' in tool.description


def test_without_task_config_the_completed_search_needs_list_ids():
    async def steps(client):
        return next(t for t in await client.list_tools() if t.name == 'tasks_get_completed_between')

    tool = run(todo_config(config.TasksConfig()), steps)
    assert set(tool.input_schema['required']) == {'list_ids', 'start_date'}


def test_steps_route_to_todo():
    async def steps(client):
        return payload(await client.call_tool('tasks_get_steps', {'task_id': 'task-1', 'list_id': 'id-chores'}))

    result = run(todo_config(TASKS), steps)
    assert result['task_id'] == 'task-1'
    assert result['steps'][0]['name'] == 'buy primer'


def test_without_task_config_nothing_account_specific_is_published():
    async def steps(client):
        return {t.name: t for t in await client.list_tools()}, client.initialize_result

    tools, result = run(todo_config(config.TasksConfig()), steps)
    assert 'tasks_get_due_today' not in tools
    assert 'Commonly used' not in tools['tasks_get_lists'].description
    assert result.instructions == toolkit.INSTRUCTIONS


def test_instructions_cover_the_common_workflows():
    assert 'narrative' not in toolkit.INSTRUCTIONS
    workflows = toolkit.INSTRUCTIONS.split('common workflows:')[1]
    for tool in ('tasks_get_due_today', 'tasks_get_completed_between', 'journal_append', 'journal_read', 'projects_write'):
        assert tool in workflows
    assert 'bookmarks' in workflows


def test_web_fetch_is_the_built_in_browser_and_takes_only_a_url():
    async def steps(client):
        return next(t for t in await client.list_tools() if t.name == 'web_fetch')

    tool = run(config.GatewayConfig(servers=()), steps)
    assert list(tool.input_schema['properties']) == ['url']
    assert tool.annotations.read_only_hint is True and tool.annotations.open_world_hint is True
    assert 'not signed in to any site' in tool.description


def test_web_fetch_names_its_signed_in_sites():
    cfg = config.GatewayConfig(servers=(), browser=config.BrowserConfig(signed_in_sites=('github.com', 'reddit.com')))

    async def steps(client):
        return next(t for t in await client.list_tools() if t.name == 'web_fetch')

    description = run(cfg, steps).description
    assert 'these sites only: github.com, reddit.com' in description
    assert 'not signed in' not in description


def test_a_changed_default_is_visible_sent_and_can_be_overridden():
    from fastmcp import FastMCP

    backend = FastMCP('backend')

    @backend.tool
    def fetch(limit: int = 200) -> int:
        return limit

    entry = toolkit.Entry(name='web', source='fetch', description='d', read_only=True,
                          args={'limit': 'how many'}, defaults={'limit': 50})
    backend.add_transform(toolkit.Catalog((entry,)))

    async def steps():
        async with Client(backend) as client:
            tool = (await client.list_tools())[0]
            return tool, await client.call_tool('web', {}), await client.call_tool('web', {'limit': 7})

    tool, default, chosen = asyncio.run(steps())
    assert tool.input_schema['properties']['limit']['default'] == 50
    assert default.content[0].text == '50'
    assert chosen.content[0].text == '7'


def test_hidden_arguments_are_invisible_and_cannot_be_overridden():
    from fastmcp import FastMCP

    backend = FastMCP('backend')

    @backend.tool
    def fetch(url: str, query: str = 'default') -> str:
        return f'{url} {query}'

    entry = toolkit.Entry(name='web', source='fetch', description='d', read_only=True,
                          hide=('query',), destructive=True, open_world=True)
    backend.add_transform(toolkit.Catalog((entry,)))

    async def steps():
        async with Client(backend) as client:
            tool = (await client.list_tools())[0]
            ok = await client.call_tool('web', {'url': 'u'})
            bad = await client.call_tool('web', {'url': 'u', 'query': 'x'}, raise_on_error=False)
            return tool, ok, bad

    tool, ok, bad = asyncio.run(steps())
    assert list(tool.input_schema['properties']) == ['url']
    assert tool.annotations.destructive_hint is True and tool.annotations.open_world_hint is True
    assert ok.content[0].text == 'u default'
    assert bad.is_error
