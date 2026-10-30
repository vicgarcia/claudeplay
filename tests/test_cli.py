import pytest

from claudeplay import cli

NO_AUTH = '''
[servers.a]
command = 'x'
'''


def test_serve_refuses_without_auth_section(tmp_path, capsys):
    path = tmp_path / 'config.toml'
    path.write_text(NO_AUTH)
    with pytest.raises(SystemExit) as e:
        cli.main(['--config', str(path), 'serve'])
    assert e.value.code == 2
    assert 'insecure-no-auth' in capsys.readouterr().err


def test_check_reports_servers(tmp_path, capsys):
    path = tmp_path / 'config.toml'
    path.write_text(NO_AUTH + "\n[servers.b]\ncommand = 'y'\nenabled = false\n")
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
