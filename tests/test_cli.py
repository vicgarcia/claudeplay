import pytest

from claudeplay import cli

NO_AUTH = '''
servers:
  a:
    command: x
'''


def test_serve_refuses_without_auth_section(tmp_path, capsys):
    path = tmp_path / 'config.yaml'
    path.write_text(NO_AUTH)
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'serve'])
    assert e.value.code == 2
    assert 'insecure_no_auth' in capsys.readouterr().err


def test_check_reports_servers(tmp_path, capsys):
    path = tmp_path / 'config.yaml'
    path.write_text(NO_AUTH + "  b:\n    command: y\n    enabled: false\n")
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'check'])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert 'a: ok' in out and 'b: disabled' in out


def test_genkey_is_long_and_random(capsys):
    keys = []
    for _ in range(2):
        with pytest.raises(SystemExit):
            cli.main(['genkey'])
        keys.append(capsys.readouterr().out.strip())
    assert keys[0] != keys[1] and len(keys[0]) >= 48


def test_config_switch_allows_no_auth_only_on_loopback(tmp_path, capsys, monkeypatch):
    from claudeplay import gateway
    served = []
    monkeypatch.setattr(gateway, 'serve', lambda cfg, **kw: served.append(cfg))
    path = tmp_path / 'config.yaml'

    path.write_text("gateway:\n  insecure_no_auth: true\n" + NO_AUTH)
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'serve'])
    assert e.value.code == 0 and len(served) == 1

    path.write_text("gateway:\n  host: 0.0.0.0\n  insecure_no_auth: true\n" + NO_AUTH)
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'serve'])
    assert e.value.code == 2 and len(served) == 1
    assert 'refusing' in capsys.readouterr().err


def test_no_auth_is_refused_while_a_tunnel_is_enabled(tmp_path, capsys, monkeypatch):
    from claudeplay import gateway
    served = []
    monkeypatch.setattr(gateway, 'serve', lambda cfg, **kw: served.append(cfg))
    path = tmp_path / 'config.yaml'
    path.write_text("gateway:\n  insecure_no_auth: true\n\ntunnel:\n  name: t\n" + NO_AUTH)
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'serve', '--insecure-no-auth'])
    assert e.value.code == 2 and served == []
    assert 'tunnel' in capsys.readouterr().err
