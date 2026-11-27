import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from claudeplay import config, gateway, toolkit

from fake_obsidian import FAKE_INSTRUCTIONS

HERE = Path(__file__).parent
FAKE_OBSIDIAN = str(HERE / 'fake_obsidian.py')
EXAMPLE = HERE.parent / 'toolkit.example.yaml'

# everything the fake obsidian has, under its own names, in backend order
OBSIDIAN_TOOLS = ['get_todays_date', 'list_journal_entries_by_year_and_month', 'read_journal_entry', 'append_to_journal_entry',
                  'prepend_to_journal_entry', 'add_note_to_journal_entry', 'write_journal_entry', 'list_projects', 'list_project_content',
                  'create_project', 'list_wiki', 'read_file', 'write_file', 'start_daily_notes_session']

EXPOSE_ALL = '''
servers:
  obsidian:
    expose_all: true
'''


def server(name: str, fake: str | None = None, enabled: bool = True) -> config.ServerConfig:
    return config.ServerConfig(name=name, command=sys.executable, args=(fake,) if fake else (), enabled=enabled)


def obsidian_cfg(enabled: bool = True) -> config.GatewayConfig:
    return config.GatewayConfig(servers=(server('obsidian', FAKE_OBSIDIAN, enabled),))


def example_cfg() -> config.GatewayConfig:
    ''' the servers the example toolkit names: obsidian over its fake, the others never started '''
    return config.GatewayConfig(servers=(
        server('obsidian', FAKE_OBSIDIAN), server('pinboard', enabled=False), server('windows', enabled=False),
    ))


def from_text(text: str, cfg: config.GatewayConfig) -> toolkit.Toolkit:
    return toolkit.parse(text, cfg)


def example_toolkit(cfg: config.GatewayConfig) -> toolkit.Toolkit:
    return toolkit.parse(EXAMPLE.read_text(encoding='utf-8'), cfg, EXAMPLE.name)


async def session(cfg, steps, tk):
    gw, _ = gateway.build(cfg, tk)
    async with Client(gw, mode='legacy') as client:
        return await steps(client)


def run(cfg, steps, text=EXPOSE_ALL):
    ''' run steps(client) against the gateway presenting the toolkit written in text '''
    tk = text if isinstance(text, toolkit.Toolkit) else from_text(text, cfg)
    return asyncio.run(session(cfg, steps, tk))


def payload(result) -> dict:
    return json.loads(result.content[0].text)


async def listed(client) -> dict:
    return {t.name: t for t in await client.list_tools()}


def backend_tools(cfg) -> dict:
    ''' what the backends themselves say, through a raw gateway: <server>_<tool> -> tool '''
    async def go():
        gw, _ = gateway.build(cfg, raw=True)
        async with Client(gw, mode='legacy') as client:
            return await listed(client)

    return asyncio.run(go())


# passthrough: the default is exactly what the backend says

def test_expose_all_shows_every_backend_tool_under_its_own_name():
    names = list(run(obsidian_cfg(), listed))
    assert names == OBSIDIAN_TOOLS


def test_unlisted_tools_pass_through_with_the_backends_own_text_and_no_annotations_of_ours():
    tools = run(obsidian_cfg(), listed)
    raw = backend_tools(obsidian_cfg())
    for name in OBSIDIAN_TOOLS:
        assert tools[name].description == raw[f'obsidian_{name}'].description
        assert tools[name].input_schema['properties'] == raw[f'obsidian_{name}'].input_schema['properties']
        assert tools[name].annotations is None
    assert tools['get_todays_date'].description.strip() == "today's date in the user's time zone."


def test_listed_tools_come_first_in_listed_order_and_change_only_what_they_set():
    text = '''
servers:
  obsidian:
    expose_all: true
    tools:
      - {source: read_file, read_only: true}
      - {source: write_file, destructive: true, description_append: 'Never write outside a project.'}
      - source: read_journal_entry
        args: {date: 'the day, as YYYY-MM-DD'}
'''
    tools = run(obsidian_cfg(), listed, text)
    names = list(tools)
    assert names[:3] == ['read_file', 'write_file', 'read_journal_entry']
    assert names[3:] == [n for n in OBSIDIAN_TOOLS if n not in ('read_file', 'write_file', 'read_journal_entry')]
    raw = backend_tools(obsidian_cfg())
    assert tools['read_file'].annotations.read_only_hint is True and tools['read_file'].annotations.destructive_hint is None
    assert tools['read_file'].description == raw['obsidian_read_file'].description
    assert tools['write_file'].annotations.destructive_hint is True
    assert tools['write_file'].description == f"{raw['obsidian_write_file'].description or ''}\n\nNever write outside a project.".strip()
    assert tools['read_journal_entry'].input_schema['properties']['date']['description'] == 'the day, as YYYY-MM-DD'
    assert tools['read_journal_entry'].description == raw['obsidian_read_journal_entry'].description
    assert tools['read_journal_entry'].annotations is None


def test_a_description_replaces_the_backends_and_an_append_follows_it():
    text = 'servers:\n  obsidian:\n    tools:\n      - {source: read_file, description: mine, description_append: more}\n'
    assert run(obsidian_cfg(), listed, text)['read_file'].description == 'mine\n\nmore'


def test_without_expose_all_only_the_listed_tools_exist_and_the_rest_cannot_be_called():
    text = 'servers:\n  obsidian:\n    tools:\n      - {source: read_file, read_only: true}\n'

    async def steps(client):
        names = list(await listed(client))
        for hidden in ('write_file', 'obsidian_write_file', 'obsidian_read_file', 'start_daily_notes_session', 'get_todays_date'):
            with pytest.raises(Exception):
                await client.call_tool(hidden, {})
        return names

    assert run(obsidian_cfg(), steps, text) == ['read_file']


def test_a_listed_tool_can_be_renamed_and_is_then_not_also_exposed_under_its_old_name():
    text = 'servers:\n  obsidian:\n    expose_all: true\n    tools:\n      - {source: read_journal_entry, name: journal_read}\n'

    async def steps(client):
        names = list(await listed(client))
        today = payload(await client.call_tool('journal_read', {'date': '2026-10-01'}))
        with pytest.raises(Exception):
            await client.call_tool('read_journal_entry', {'date': '2026-10-01'})
        return names, today

    names, today = run(obsidian_cfg(), steps, text)
    assert 'journal_read' in names and 'read_journal_entry' not in names
    assert today['content'] == 'went for a run'


def test_a_backends_own_annotations_pass_through_and_a_listing_overrides_them():
    backend = FastMCP('backend')

    @backend.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    def look() -> str:
        return 'seen'

    entries = (toolkit.Entry(name='look', source='look'), toolkit.Entry(name='look2', source='look', open_world=False))
    backend.add_transform(toolkit.Catalog(entries))

    async def steps():
        async with Client(backend) as client:
            return {t.name: t for t in await client.list_tools()}

    tools = asyncio.run(steps())
    assert (tools['look'].annotations.read_only_hint, tools['look'].annotations.open_world_hint) == (True, True)
    assert (tools['look2'].annotations.read_only_hint, tools['look2'].annotations.open_world_hint) == (True, False)


def test_calls_route_to_the_backend_under_its_own_names():
    async def steps(client):
        month = payload(await client.call_tool('list_journal_entries_by_year_and_month', {'year': '2026', 'month': '10'}))
        noted = payload(await client.call_tool('add_note_to_journal_entry', {'text': '### heron\nby the river'}))
        prepended = payload(await client.call_tool('prepend_to_journal_entry', {'text': '# Daily Recap\nquiet\n\n'}))
        appended = payload(await client.call_tool('append_to_journal_entry', {'text': 'ps'}))
        today = payload(await client.call_tool('read_journal_entry', {'date': '2026-10-29'}))
        date = payload(await client.call_tool('get_todays_date', {}))
        return month, noted, prepended, appended, today, date

    month, noted, prepended, appended, today, date = run(obsidian_cfg(), steps)
    assert [e['name'] for e in month] == ['2026-10-01.md']
    assert noted['created'] is True and noted['timestamp'] == '2026-10-29 09:00'
    assert prepended['created'] is False and appended['created'] is False
    assert today['content'] == '# Daily Recap\nquiet\n\n### heron\nby the river\n\n2026-10-29 09:00\n\n\nps'
    assert date == {'date': '2026-10-29'}


def test_the_vaults_own_file_tools_work_with_listed_paths_and_claudeplay_adds_no_path_checks():
    async def steps(client):
        project = payload(await client.call_tool('list_project_content', {'project': 'garage'}))
        wiki = payload(await client.call_tool('list_wiki', {}))
        article = payload(await client.call_tool('read_file', {'file_path': wiki[0]['path']}))
        await client.call_tool('write_file', {'file_path': project[0]['path'], 'content': 'more shelves'})
        return article, payload(await client.call_tool('read_file', {'file_path': project[0]['path']}))

    article, note = run(obsidian_cfg(), steps)
    assert article == {'content': 'bridges'}
    assert note == {'content': 'more shelves'}


def test_server_presents_itself_as_claudeplay():
    async def steps(client):
        return client.initialize_result

    assert run(obsidian_cfg(), steps).server_info.name == 'claudeplay'


def test_a_disabled_backend_simply_removes_its_tools():
    assert list(run(obsidian_cfg(enabled=False), listed)) == []


def test_catalog_rejects_duplicate_names():
    entry = toolkit.Entry(name='x', source='a_x')
    with pytest.raises(ValueError):
        toolkit.Catalog([entry, entry])


def test_a_passthrough_tool_whose_name_is_already_used_is_hidden_with_a_warning(caplog):
    backend = FastMCP('backend')

    @backend.tool
    def a_dup() -> str:
        return 'passthrough'

    @backend.tool
    def b_other() -> str:
        return 'other'

    # b_other is listed under the name dup, so a's own dup would clash with it
    entries = (toolkit.Entry(name='dup', source='b_other'),)
    backend.add_transform(toolkit.Catalog(entries, passthrough=('a',)))

    async def steps():
        async with Client(backend) as client:
            return [t.name for t in await client.list_tools()], (await client.call_tool('dup', {})).content[0].text

    with caplog.at_level(logging.WARNING, logger='claudeplay.toolkit'):
        names, text = asyncio.run(steps())
    assert names == ['dup'] and text == 'other'
    assert 'tool dup of an expose_all server is hidden' in caplog.text


def test_tools_are_grouped_by_server_in_toolkit_order_with_each_servers_listed_tools_first():
    # the backends list c's tools first, but toolkit.yaml names a, then b, then c
    text = '''
servers:
  a:
    expose_all: true
    tools:
      - {source: listed}
  b:
    tools:
      - {source: two}
      - {source: one, name: b_first}
  c:
    expose_all: true
'''
    cfg = config.GatewayConfig(servers=(server('c'), server('b'), server('a')))
    tk = from_text(text, cfg)
    backend = FastMCP('backend')
    for name in ('c_only', 'a_early', 'a_listed', 'a_late', 'b_one', 'b_two'):
        backend.tool(lambda: 'ok', name=name)
    backend.add_transform(toolkit.Catalog(tk.entries(), tk.passthrough(), tuple(tk.servers)))

    async def steps():
        async with Client(backend) as client:
            return [t.name for t in await client.list_tools()]

    assert asyncio.run(steps()) == ['listed', 'early', 'late', 'two', 'b_first', 'only']


# server instructions: the backend's own, loaded when it is probed, plus the toolkit's additions

async def instructions_after_probe(cfg, tk) -> str | None:
    ''' wait for every probe, then read what a session that starts now is sent '''
    board = gateway.StatusBoard(None, cfg.endpoint_url)
    gw, board = gateway.build(cfg, tk, board=board)
    async with Client(gw, mode='legacy') as first:
        await first.list_tools()
        for _ in range(100):
            if not any(s.state == gateway.STARTING for s in board.servers.values()):
                break
            await asyncio.sleep(0.1)
        async with Client(gw, mode='legacy') as later:
            return later.initialize_result.instructions


def instructions_of(cfg, text) -> str | None:
    return asyncio.run(instructions_after_probe(cfg, from_text(text, cfg)))


TOP = 'instructions: top level\n'


def test_the_backends_own_instructions_are_passed_through_after_the_top_level():
    text = TOP + EXPOSE_ALL
    assert instructions_of(obsidian_cfg(), text) == f'top level\n\n## obsidian\n\n{FAKE_INSTRUCTIONS}'


def test_instructions_append_follows_the_backends_and_instructions_replaces_them():
    base = TOP + 'servers:\n  obsidian:\n    expose_all: true\n'
    assert instructions_of(obsidian_cfg(), base + '    instructions_append: also this\n') == f'top level\n\n## obsidian\n\n{FAKE_INSTRUCTIONS}\n\nalso this'
    assert instructions_of(obsidian_cfg(), base + '    instructions: mine\n    instructions_append: also this\n') == 'top level\n\n## obsidian\n\nmine\n\nalso this'
    # an empty replacement sends none of the backend's, and with no text there is no heading either
    assert instructions_of(obsidian_cfg(), base + "    instructions: ''\n") == 'top level'


def test_a_label_says_what_the_server_is_in_its_heading():
    cfg = config.GatewayConfig(servers=(server('a'), server('b')))
    text = ('servers:\n  a:\n    label: the user\'s notes\n    instructions: from a\n    tools:\n      - {source: s}\n'
            '  b:\n    label: "  spread\n      over lines  "\n    instructions: from b\n    tools:\n      - {source: t}\n')
    assert from_text(text, cfg).instructions_for(cfg) == "## a: the user's notes\n\nfrom a\n\n## b: spread over lines\n\nfrom b"


def test_a_labelled_server_with_no_instructions_adds_no_heading():
    cfg = config.GatewayConfig(servers=(server('a'),))
    tk = from_text("servers:\n  a:\n    label: notes\n    expose_all: true\n", cfg)
    assert tk.instructions_for(cfg) == ''
    assert tk.instructions_for(cfg, {'a': 'from the backend'}) == '## a: notes\n\nfrom the backend'


def test_a_server_that_exposes_nothing_or_is_disabled_adds_no_instructions():
    nothing = TOP + 'servers:\n  obsidian: {}\n'
    assert instructions_of(obsidian_cfg(), nothing) == 'top level'
    assert instructions_of(obsidian_cfg(enabled=False), TOP + EXPOSE_ALL) == 'top level'


def test_instructions_follow_config_order_not_file_order():
    text = TOP + 'servers:\n  a:\n    instructions: from a\n    tools:\n      - {source: s}\n  b:\n    instructions: from b\n    tools:\n      - {source: t}\n'
    cfg = config.GatewayConfig(servers=(server('b'), server('a')))
    tk = from_text(text, cfg)
    assert tk.instructions_for(cfg) == 'top level\n\n## b\n\nfrom b\n\n## a\n\nfrom a'
    off = config.GatewayConfig(servers=(server('b', enabled=False), server('a')))
    assert from_text(text, off).instructions_for(off) == 'top level\n\n## a\n\nfrom a'


def test_instructions_for_uses_the_backends_text_only_for_servers_that_have_some():
    cfg = config.GatewayConfig(servers=(server('a'), server('b')))
    tk = from_text('servers:\n  a:\n    expose_all: true\n  b:\n    expose_all: true\n    instructions_append: extra\n', cfg)
    assert tk.instructions_for(cfg, {'a': 'from the backend'}) == '## a\n\nfrom the backend\n\n## b\n\nextra'
    assert tk.instructions_for(cfg) == '## b\n\nextra'


def test_a_session_that_starts_before_the_probes_finish_still_gets_the_toolkits_own_instructions():
    async def steps(client):
        return client.initialize_result.instructions

    assert (run(obsidian_cfg(), steps, TOP + EXPOSE_ALL) or '').startswith('top level')


# the shipped example

def test_the_shipped_example_is_valid_against_the_example_config():
    example = HERE.parent / 'config.example.yaml'
    cfg = config.parse(example.read_text(encoding='utf-8'), example.name)
    tk = toolkit.parse(EXAMPLE.read_text(encoding='utf-8'), cfg, EXAMPLE.name)
    assert tk.counts() == {'obsidian': 9, 'pinboard': 3, 'windows': 2}
    assert tk.passthrough() == ('obsidian',)


def test_example_names_are_valid_for_claude():
    for entry in example_toolkit(example_cfg()).entries():
        assert len(entry.name) <= 64 and entry.name.replace('_', '').isalnum()


def test_example_exposes_no_tool_that_deletes():
    tk = example_toolkit(example_cfg())
    assert all('delete' not in e.source for s in tk.servers.values() for e in s.entries)


def test_example_instructions_are_additions_not_a_rewrite_of_what_backends_say():
    tk = example_toolkit(example_cfg())
    assert tk.servers['obsidian'].instructions is None and tk.servers['pinboard'].instructions is None
    assert 'web_fetch' not in tk.instructions


def test_the_shipped_example_matches_the_fake_obsidian():
    ''' every obsidian entry names real tools and arguments '''
    cfg = example_cfg()

    async def go():
        board = gateway.StatusBoard(None, cfg.endpoint_url)
        gw, board = gateway.build(cfg, example_toolkit(cfg), board=board)
        async with Client(gw, mode='legacy') as client:
            await client.list_tools()
            for _ in range(100):
                if not any(s.state == gateway.STARTING for s in board.servers.values()):
                    break
                await asyncio.sleep(0.1)
            return board

    board = asyncio.run(go())
    # the fake obsidian has every tool the example lists for obsidian, with the arguments it names
    assert board.servers['obsidian'].state == gateway.OK, board.servers['obsidian'].error


# validation: the config is the catalog, so mistakes must fail loudly

CFG_AB = config.GatewayConfig(servers=(server('a'), server('b')))


@pytest.mark.parametrize('text, where', [
    ('servers:\n  a:\n    tools:\n      - description: d\n', 'servers.a.tools.0.source'),
    ('servers:\n  a:\n    tools:\n      - source: s\n        description: ""\n', 'servers.a.tools.0.description'),
    ('servers:\n  a:\n    tools:\n      - source: s\n        raed_only: true\n', 'servers.a.tools.0.raed_only'),
    ('servers:\n  a:\n    tools:\n      - source: s\n        name: has space\n', 'servers.a.tools.0.name'),
    ('servers:\n  a:\n    tools:\n      - source: s\n        read_only: yes please\n', 'servers.a.tools.0.read_only'),
    ('servers:\n  a:\n    instruction: x\n', 'servers.a.instruction'),
    ('servers:\n  a:\n    expose_all: maybe\n', 'servers.a.expose_all'),
    ('servers:\n  a:\n    tools:\n      - source: s\n        args: [date]\n', 'servers.a.tools.0.args'),
    ('instructoins: x\n', 'instructoins'),
])
def test_bad_toolkit_errors_name_the_file_and_key_path(text, where):
    with pytest.raises(config.ConfigError) as e:
        toolkit.parse(text, CFG_AB, 'toolkit.yaml')
    assert f'toolkit.yaml: {where}' in str(e.value)


def test_toolkit_errors_never_quote_values():
    text = 'servers:\n  a:\n    tools:\n      - source: s\n        read_only: hunter2\n        extra_hunter2: hunter2\n'
    with pytest.raises(config.ConfigError) as e:
        toolkit.parse(text, CFG_AB, 'toolkit.yaml')
    assert 'hunter2' not in str(e.value).replace('extra_hunter2', '')
    with pytest.raises(config.ConfigError) as e:
        toolkit.parse('a: hunter2\na: other-hunter2\n', CFG_AB, 'toolkit.yaml')
    assert 'hunter2' not in str(e.value)
    with pytest.raises(config.ConfigError) as e:
        toolkit.parse('servers: [unclosed hunter2\n', CFG_AB, 'toolkit.yaml')
    assert 'hunter2' not in str(e.value) and 'line' in str(e.value)


def test_a_toolkit_server_missing_from_the_config_is_an_error():
    with pytest.raises(config.ConfigError, match='servers.c: not a server in config.yaml'):
        toolkit.parse('servers:\n  c: {}\n', CFG_AB, 'toolkit.yaml')


def test_duplicate_public_names_across_servers_are_an_error():
    text = 'servers:\n  a:\n    tools:\n      - {source: one, name: shared}\n  b:\n    tools:\n      - {source: two, name: shared}\n'
    with pytest.raises(config.ConfigError, match=r'servers\.b\.tools\.0: the name shared is already used by servers\.a'):
        from_text(text, CFG_AB)


def test_the_default_name_is_the_backend_name_so_two_servers_can_clash_on_it():
    text = 'servers:\n  a:\n    tools:\n      - {source: read}\n  b:\n    tools:\n      - {source: read}\n'
    with pytest.raises(config.ConfigError, match='the name read is already used'):
        from_text(text, CFG_AB)


def test_the_name_defaults_to_the_backend_name_and_the_source_is_prefixed_with_the_server():
    tk = from_text('servers:\n  a:\n    tools:\n      - {source: read_file, read_only: true}\n', CFG_AB)
    entry = tk.servers['a'].entries[0]
    assert (entry.name, entry.source, entry.description, entry.read_only, entry.destructive, entry.open_world) == ('read_file', 'a_read_file', None, True, None, None)


def test_a_configured_server_with_nothing_exposed_is_allowed_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger='claudeplay.toolkit'):
        tk = from_text('servers:\n  a:\n    expose_all: true\n', CFG_AB)
    assert tk.counts() == {'a': 0}
    assert 'server b has no tools listed' in caplog.text and 'server a ' not in caplog.text


def test_an_empty_toolkit_is_valid_and_exposes_nothing():
    tk = from_text('', CFG_AB)
    assert tk.servers == {} and tk.entries() == ()


def test_load_reads_toolkit_yaml_next_to_the_config_and_names_a_missing_file(tmp_path):
    cfg_path = tmp_path / 'config.yaml'
    with pytest.raises(config.ConfigError, match='toolkit not found'):
        toolkit.load(cfg_path, CFG_AB)
    (tmp_path / 'toolkit.yaml').write_text('servers:\n  a:\n    tools:\n      - {source: s}\n')
    assert toolkit.load(cfg_path, CFG_AB).counts() == {'a': 1}


# probe-time checks against what the backends really list

def lists(*names_and_params: tuple[str, list[str]]):
    ''' tools as a backend lists them: a name and the arguments it takes '''
    return [SimpleNamespace(name=n, input_schema={'properties': {p: {} for p in params}}) for n, params in names_and_params]


def entry(**kw) -> toolkit.Entry:
    return toolkit.Entry(**({'name': 'x', 'source': 'srv_x'} | kw))


def test_check_backend_accepts_a_matching_toolkit():
    tools = lists(('x', ['date', 'limit', 'secret']))
    assert toolkit.check_backend('srv', tools, [entry(args={'date': 'd'}, hide=('secret',), fixed={'secret': 1}, defaults={'limit': 5})]) == []


def test_check_backend_names_a_missing_tool_and_each_unknown_argument():
    tools = lists(('x', ['date']))
    problems = toolkit.check_backend('srv', tools, [
        entry(name='gone', source='srv_renamed'),
        entry(args={'dat': 'd'}, hide=('h',), fixed={'f': 1}, defaults={'d': 2}),
    ])
    assert problems == [
        'gone: backend tool renamed not found',
        'x: args names dat, which x does not take',
        'x: hide names h, which x does not take',
        'x: fixed names f, which x does not take',
        'x: defaults names d, which x does not take',
    ]


def test_check_backend_never_includes_values():
    problems = toolkit.check_backend('srv', lists(('x', [])), [entry(fixed={'secret_arg': 'hunter2'}, args={'other': 'hunter2'})])
    assert problems and all('hunter2' not in p for p in problems)


def test_check_backend_reports_an_exposed_tool_whose_name_is_taken():
    tools = lists(('x', []), ('read_file', []), ('fresh', []))
    problems = toolkit.check_backend('srv', tools, [entry()], expose_all=True, taken=('read_file', 'x'))
    assert problems == ['read_file: backend tool is exposed under a name already used by another tool']
    assert toolkit.check_backend('srv', tools, [entry()], expose_all=False, taken=('read_file',)) == []


def probed(cfg, text):
    ''' build the gateway from toolkit text, let the probes finish, and return the tools claude sees and the board '''
    async def go():
        board = gateway.StatusBoard(None, cfg.endpoint_url)
        gw, board = gateway.build(cfg, from_text(text, cfg), board=board)
        async with Client(gw, mode='legacy') as client:
            names = [t.name for t in await client.list_tools()]
            for _ in range(100):
                if not any(s.state == gateway.STARTING for s in board.servers.values()):
                    break
                await asyncio.sleep(0.1)
            return names, board, board.overall()

    return asyncio.run(go())


def test_a_renamed_backend_tool_marks_the_server_failed_naming_the_tool():
    text = 'servers:\n  obsidian:\n    tools:\n      - {source: read_journal_entry, name: journal_read}\n      - {source: read_journal_entry_v2, name: journal_read_v2}\n'
    names, board, _ = probed(obsidian_cfg(), text)
    assert board.servers['obsidian'].state == gateway.FAILED
    assert board.servers['obsidian'].error == 'toolkit.yaml: journal_read_v2: backend tool read_journal_entry_v2 not found'
    # the tools that do match are still presented, and the probe saw the backend's tools
    assert names == ['journal_read'] and board.servers['obsidian'].tools > 0


def test_an_unknown_argument_marks_the_server_failed_naming_the_tool_and_argument():
    text = 'servers:\n  obsidian:\n    tools:\n      - {source: read_journal_entry, name: journal_read, args: {dat: when}, fixed: {zzz: 1}}\n'
    names, board, overall = probed(obsidian_cfg(), text)
    status = board.servers['obsidian']
    assert status.state == gateway.FAILED
    assert status.error == 'toolkit.yaml: journal_read: args names dat, which read_journal_entry does not take (and 1 more)'
    assert overall == 'degraded'
    # presentation stays tolerant: the tool is still there, the unknown arguments are ignored
    assert 'journal_read' in names


def test_an_exposed_tool_that_clashes_with_a_listed_name_marks_the_server_failed():
    text = 'servers:\n  obsidian:\n    expose_all: true\n    tools:\n      - {source: read_journal_entry, name: read_file}\n'
    _, board, _ = probed(obsidian_cfg(), text)
    assert board.servers['obsidian'].state == gateway.FAILED
    assert board.servers['obsidian'].error == 'toolkit.yaml: read_file: backend tool is exposed under a name already used by another tool'


def test_a_matching_toolkit_leaves_the_server_ok():
    text = 'servers:\n  obsidian:\n    expose_all: true\n    tools:\n      - {source: read_journal_entry, args: {date: when}}\n'
    _, board, _ = probed(obsidian_cfg(), text)
    assert board.servers['obsidian'].state == gateway.OK and board.servers['obsidian'].error == ''


# the catalog transform on its own

def test_a_changed_default_is_visible_sent_and_can_be_overridden():
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


def test_a_default_without_an_argument_description_still_reaches_the_schema():
    backend = FastMCP('backend')

    @backend.tool
    def search(start: str, list_ids: list[str]) -> list[str]:
        return list_ids

    entry = toolkit.Entry(name='search', source='search', defaults={'list_ids': ['id-1']})
    backend.add_transform(toolkit.Catalog((entry,)))

    async def steps():
        async with Client(backend) as client:
            return (await client.list_tools())[0], await client.call_tool('search', {'start': 'x'})

    tool, called = asyncio.run(steps())
    assert tool.input_schema['properties']['list_ids']['default'] == ['id-1']
    assert tool.input_schema['required'] == ['start']
    assert called.structured_content == {'result': ['id-1']}


def test_fixed_arguments_are_invisible_always_sent_and_cannot_be_overridden():
    backend = FastMCP('backend')

    @backend.tool
    def due(list_ids: list[str]) -> list[str]:
        return list_ids

    entry = toolkit.Entry(name='due', source='due', fixed={'list_ids': ['id-a', 'id-b']})
    backend.add_transform(toolkit.Catalog((entry,)))

    async def steps():
        async with Client(backend) as client:
            tool = (await client.list_tools())[0]
            ok = await client.call_tool('due', {})
            bad = await client.call_tool('due', {'list_ids': ['id-other']}, raise_on_error=False)
            return tool, ok, bad

    tool, ok, bad = asyncio.run(steps())
    assert not tool.input_schema.get('properties')
    assert ok.structured_content == {'result': ['id-a', 'id-b']}
    assert bad.is_error


def test_hidden_arguments_are_invisible_and_cannot_be_overridden():
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


def test_presenting_ignores_arguments_the_backend_does_not_have():
    backend = FastMCP('backend')

    @backend.tool
    def fetch(url: str) -> str:
        return url

    entry = toolkit.Entry(name='web', source='fetch', description='d', args={'url': 'the url', 'gone': 'x'}, hide=('gone2',), fixed={'gone3': 1}, defaults={'gone4': 1})
    backend.add_transform(toolkit.Catalog((entry,)))

    async def steps():
        async with Client(backend) as client:
            return (await client.list_tools())[0], await client.call_tool('web', {'url': 'u'})

    tool, ok = asyncio.run(steps())
    assert list(tool.input_schema['properties']) == ['url'] and ok.content[0].text == 'u'


def test_raw_mode_ignores_the_toolkit_and_shows_every_backend_tool_prefixed():
    names = set(backend_tools(obsidian_cfg()))
    assert {'obsidian_read_file', 'obsidian_start_daily_notes_session'} <= names
