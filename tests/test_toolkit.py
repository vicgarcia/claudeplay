import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from claudeplay import config, gateway, toolkit

FAKE_OBSIDIAN = str(Path(__file__).parent / 'fake_obsidian.py')
EXPECTED = ['get_date', 'journal_list_month', 'journal_read', 'journal_append']


def obsidian() -> config.ServerConfig:
    return config.ServerConfig(name='obsidian', command=sys.executable, args=(FAKE_OBSIDIAN,))


async def session(cfg, steps):
    ''' run steps(client) against the curated gateway '''
    gw, _ = gateway.build(cfg, overrides={})
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
    entries = {e.name: e for e in toolkit.CATALOG}
    for name, tool in tools.items():
        assert tool.description == entries[name].description
        assert tool.annotations.read_only_hint is entries[name].read_only
        assert tool.annotations.destructive_hint is False
    assert tools['journal_read'].input_schema['properties']['date']['description'] == 'the day, as YYYY-MM-DD'
    assert tools['journal_read'].input_schema['required'] == ['date']


def test_calls_route_to_the_backend():
    async def steps(client):
        date = payload(await client.call_tool('get_date', {}))
        month = payload(await client.call_tool('journal_list_month', {'year': '2026', 'month': '10'}))
        appended = payload(await client.call_tool('journal_append', {'text': 'saw a heron'}))
        today = payload(await client.call_tool('journal_read', {'date': date['formatted']}))
        return date, month, appended, today

    date, month, appended, today = run(config.GatewayConfig(servers=(obsidian(),)), steps)
    assert date['formatted'] == '2026-10-29'
    assert [e['name'] for e in month] == ['2026-10-01.md']
    assert appended['created'] is True
    assert today == {'path': 'journal/2026-10-29.md', 'exists': True, 'content': 'saw a heron'}


@pytest.mark.parametrize('name', ['write_file', 'obsidian_write_file', 'obsidian_get_current_date'])
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

    assert run(config.GatewayConfig(servers=(off,)), steps) == []


def test_catalog_rejects_duplicate_names():
    entry = toolkit.Entry(name='x', source='a_x', description='d', read_only=True)
    with pytest.raises(ValueError):
        toolkit.Catalog([entry, entry])


def test_catalog_names_are_valid_for_claude():
    for entry in toolkit.CATALOG:
        assert len(entry.name) <= 64 and entry.name.replace('_', '').isalnum() and entry.name.islower()
