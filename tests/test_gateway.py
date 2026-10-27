import asyncio
import json
import logging
import sys

from fastmcp import Client

from claudeplay import config, gateway

from conftest import fake


def cfg_of(*servers: config.ServerConfig) -> config.GatewayConfig:
    return config.GatewayConfig(servers=tuple(servers))


async def run_gateway(cfg, overrides=None, environ=None, calls=()):
    ''' build the gateway, wait for probes, return (tool names, board, call results, live overall state) '''
    board = gateway.StatusBoard(config.status_path(), cfg.endpoint_url)
    gw, board = gateway.build(cfg, overrides=overrides or {}, board=board, environ=environ)
    async with Client(gw, mode='legacy') as client:
        names = sorted(t.name for t in await client.list_tools())
        for _ in range(100):
            if not any(s.state == gateway.STARTING for s in board.servers.values()):
                break
            await asyncio.sleep(0.1)
        overall = board.overall()
        results = [(await client.call_tool(n, a)).content[0].text for n, a in calls]
    return names, board, results, overall


def run(*args, **kwargs):
    return asyncio.run(run_gateway(*args, **kwargs))


def test_tools_are_always_prefixed_even_with_one_server():
    names, board, _, overall = run(cfg_of(fake('alpha')))
    assert names == ['alpha_echo', 'alpha_ping']
    assert board.servers['alpha'].state == gateway.OK
    assert board.servers['alpha'].tools == 2
    assert overall == 'running'


def test_two_servers_do_not_collide():
    names, _, results, _ = run(cfg_of(fake('a'), fake('b')), calls=[('b_ping', {})])
    assert names == ['a_echo', 'a_ping', 'b_echo', 'b_ping']
    assert results == ['pong']


def test_disabled_servers_are_skipped_and_not_expanded():
    todo = config.ServerConfig(name='todo', command='${NOT_SET_ANYWHERE}', enabled=False)
    names, board, _, overall = run(cfg_of(fake('a'), todo))
    assert names == ['a_echo', 'a_ping']
    assert board.servers['todo'].state == gateway.DISABLED


def test_override_enables_and_disables():
    cfg = cfg_of(fake('a'), fake('b', enabled=False))
    names, board, _, overall = run(cfg, overrides={'a': False, 'b': True})
    assert names == ['b_echo', 'b_ping']
    assert board.servers['a'].state == gateway.DISABLED


def test_unset_env_var_fails_only_that_server():
    bad = config.ServerConfig(name='bad', command=sys.executable, env={'K': '${NOPE_NOT_SET}'})
    names, board, _, overall = run(cfg_of(fake('good'), bad), environ={})
    assert names == ['good_echo', 'good_ping']
    assert board.servers['bad'].state == gateway.FAILED
    assert board.servers['bad'].error == 'environment variable NOPE_NOT_SET is not set'
    assert board.servers['good'].state == gateway.OK


def test_missing_command_fails_only_that_server():
    bad = config.ServerConfig(name='bad', command='C:/definitely/not/here.exe')
    names, board, _, overall = run(cfg_of(bad, fake('good')))
    assert names == ['good_echo', 'good_ping']
    assert board.servers['bad'].state == gateway.FAILED
    assert board.servers['bad'].error == 'command not found'


def test_server_that_exits_immediately_is_marked_failed_by_probe():
    dies = config.ServerConfig(name='dies', command=sys.executable, args=('-c', 'raise SystemExit(1)'))
    names, board, _, overall = run(cfg_of(fake('good'), dies))
    assert names == ['good_echo', 'good_ping']
    assert board.servers['dies'].state == gateway.FAILED
    assert board.servers['good'].state == gateway.OK
    assert overall == 'degraded'


def test_status_file_written_and_has_no_secrets(isolated_home):
    secret = 'sekrit-value-123'
    server = fake('a', env={'TOKEN': '${TOK}'})
    run(cfg_of(server), environ={'TOK': secret})
    text = config.status_path().read_text()
    data = json.loads(text)
    assert data['servers']['a']['state'] == 'ok'
    assert secret not in text


def test_tool_calls_are_logged_with_name_and_timing_but_not_arguments(caplog):
    caplog.set_level(logging.INFO, logger='claudeplay')
    secret = 'my-private-journal-text'
    _, _, results, _ = run(cfg_of(fake('a')), calls=[('a_echo', {'text': secret})])
    assert results == [secret]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith('tool=')]
    assert len(lines) == 1
    assert lines[0].startswith('tool=a_echo ms=')
    assert 'result=ok' in lines[0]
    assert secret not in caplog.text


def test_status_overall_states():
    board = gateway.StatusBoard(None)
    board.set('a', gateway.STARTING)
    assert board.overall() == 'starting'
    board.set('a', gateway.OK)
    board.set('b', gateway.DISABLED)
    assert board.overall() == 'running'
    board.set('c', gateway.FAILED, 'x')
    assert board.overall() == 'degraded'
    board.stop()
    assert board.overall() == 'stopped'
