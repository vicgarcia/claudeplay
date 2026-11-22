import json
from pathlib import Path

import pytest

from claudeplay import config

SAMPLE = '''
gateway:
  port: 9000
  public_base_url: https://abc.example.net/

auth:
  client_id: ${GH_ID}
  allowed_user_ids: [12345]

servers:
  obsidian:
    command: ${HOME_DIR}/obsidian-mcp.exe
    args: [--vault, '${VAULT}']
    env:
      TZ: America/New_York
  pinboard:
    command: pinboard-mcp.exe
    enabled: false
    env:
      PINBOARD_TOKEN: ${PINBOARD_TOKEN}
'''


def test_parse_basic():
    cfg = config.parse(SAMPLE)
    assert cfg.port == 9000
    assert cfg.host == '127.0.0.1'
    assert [s.name for s in cfg.servers] == ['obsidian', 'pinboard']
    assert cfg.server('obsidian').env == {'TZ': 'America/New_York'}
    assert cfg.server('pinboard').enabled is False
    assert cfg.auth.allowed_user_ids == (12345,)


def test_urls_strip_trailing_slash_and_default_to_localhost():
    assert config.parse(SAMPLE).endpoint_url == 'https://abc.example.net/mcp'
    assert config.parse('').endpoint_url == 'http://localhost:8765/mcp'


def test_expand_replaces_variables():
    assert config.expand('${A}/x/${B}', {'A': '1', 'B': '2'}) == '1/x/2'
    assert config.expand('no refs', {}) == 'no refs'


def test_expand_unset_names_variable_only():
    with pytest.raises(config.ConfigError) as e:
        config.expand('prefix-${MISSING}', {'OTHER': 'secret-value'})
    assert str(e.value) == 'environment variable MISSING is not set'
    assert 'secret-value' not in str(e.value)


def test_resolve_expands_command_args_and_env():
    cfg = config.parse(SAMPLE)
    resolved = config.resolve(cfg.server('obsidian'), {'HOME_DIR': 'C:/bin', 'VAULT': 'V'})
    assert resolved.command == 'C:/bin/obsidian-mcp.exe'
    assert resolved.args == ['--vault', 'V']
    assert resolved.env == {'TZ': 'America/New_York'}


def test_resolve_fails_on_unset_variable_in_env():
    with pytest.raises(config.ConfigError, match='PINBOARD_TOKEN'):
        config.resolve(config.parse(SAMPLE).server('pinboard'), {})


@pytest.mark.parametrize('text', [
    'servers:\n  x:\n    args: []',
    'servers:\n  x:\n    command: c\n    args: nope',
    'servers:\n  x:\n    command: c\n    enabled: "yes"',
    'servers:\n  x:\n    command: c\n    env:\n      A: 1',
    'gateway:\n  port: 0',
    'auth:\n  allowed_user_ids: ["123"]',
    'tunnel:\n  command: c',
    'tunnel:\n  name: t\n  enabled: 1',
    'not yaml: [',
    '- a list\n- not a mapping',
])
def test_parse_rejects_bad_config(text):
    with pytest.raises(config.ConfigError):
        config.parse(text)


def test_unknown_keys_are_errors_that_name_the_file_and_key_but_not_the_value():
    text = 'gateway:\n  prot: hunter2\nservers:\n  x:\n    command: c\n    enviroment: {A: hunter2}\n'
    with pytest.raises(config.ConfigError) as e:
        config.parse(text, 'config.yaml')
    message = str(e.value)
    assert 'config.yaml: gateway.prot' in message
    assert 'config.yaml: servers.x.enviroment' in message
    assert 'hunter2' not in message


def test_a_wrong_type_does_not_echo_the_value():
    with pytest.raises(config.ConfigError) as e:
        config.parse('auth:\n  client_secret: [s3cret]\n')
    assert 'auth.client_secret' in str(e.value) and 's3cret' not in str(e.value)


def test_yaml_syntax_errors_name_the_line_and_never_quote_the_text():
    with pytest.raises(config.ConfigError) as e:
        config.parse('auth:\n  client_secret: s3cret\n  bad: [unclosed\n', 'config.yaml')
    assert 'config.yaml' in str(e.value) and 'line' in str(e.value) and 's3cret' not in str(e.value)


def test_tunnel_section_and_public_host():
    cfg = config.parse('gateway:\n  public_base_url: https://cp-x.example.net/\n\ntunnel:\n  name: claudeplay\n')
    assert cfg.tunnel == config.TunnelConfig(name='claudeplay', command=config.DEFAULT_CLOUDFLARED, enabled=True)
    assert cfg.tunnel_enabled and cfg.public_host == 'cp-x.example.net'
    assert cfg.endpoint_url == 'https://cp-x.example.net/mcp'
    off = config.parse('tunnel:\n  name: t\n  enabled: false\n')
    assert not off.tunnel_enabled and off.public_host == ''
    assert config.parse('').tunnel is None


def test_load_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match='not found'):
        config.load(tmp_path / 'nope.yaml')


EDITABLE = """# my config
gateway:
  port: 9000  # keep this comment

auth:
  client_id: 'abc'
  client_secret: "top-secret"
  allowed_user_ids: [42]
  # jwt_signing_key: generated on first run

servers:
  obsidian:
    command: o.exe
    args: [--vault, 'C:/some path/vault']
    enabled: true
  pinboard:
    command: 'pinboard.exe'
    enabled: false  # off for now
    env:
      PINBOARD_TOKEN: pinboard-secret
      PINBOARD_USER: &id 'x'  # anchored

tunnel:
  name: claudeplay
"""


def write(tmp_path, text=EDITABLE):
    path = tmp_path / 'config.yaml'
    path.write_bytes(text.encode())
    return path


def test_default_paths_follow_the_home_and_logs_overrides(isolated_home, isolated_logs):
    assert config.default_config_path() == isolated_home / 'config.yaml'
    assert config.toolkit_path() == isolated_home / 'toolkit.yaml'
    assert config.status_path() == isolated_home / 'status.json'
    assert config.logs_dir() == isolated_logs
    # the toolkit comes from the folder of whichever config was given
    assert config.toolkit_path(Path('x') / 'other.yaml') == Path('x') / 'toolkit.yaml'


def test_home_defaults_to_dot_claudeplay_and_logs_to_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv('CLAUDEPLAY_HOME')
    monkeypatch.delenv('CLAUDEPLAY_LOGS')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    assert config.home_dir() == Path.home() / '.claudeplay'
    assert config.logs_dir() == tmp_path / 'local' / 'claudeplay' / 'logs'


def test_set_enabled_changes_only_that_value_byte_for_byte(tmp_path):
    path = write(tmp_path)
    config.set_enabled(path, 'pinboard', True)
    assert config.load(path).server('pinboard').enabled is True
    assert path.read_text() == EDITABLE.replace('enabled: false  # off for now', 'enabled: true  # off for now')
    # and back again
    config.set_enabled(path, 'pinboard', False)
    assert path.read_text() == EDITABLE


def test_set_enabled_unknown_server(tmp_path):
    with pytest.raises(config.ConfigError, match='nope'):
        config.set_enabled(write(tmp_path), 'nope', True)


def test_set_enabled_keeps_crlf_files_crlf(tmp_path):
    path = write(tmp_path, EDITABLE.replace('\n', '\r\n'))
    config.set_enabled(path, 'pinboard', True)
    raw = path.read_bytes()
    assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')


def test_set_enabled_leaves_no_temp_file_behind(tmp_path):
    path = write(tmp_path)
    config.set_enabled(path, 'pinboard', True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['config.yaml']


def test_ensure_signing_key_writes_once_and_keeps_everything_else(tmp_path):
    path = write(tmp_path)
    assert config.ensure_signing_key(path) is True
    key = config.load(path).auth.jwt_signing_key
    assert len(key) >= 48
    assert config.ensure_signing_key(path) is False
    assert config.load(path).auth.jwt_signing_key == key
    text = path.read_text()
    assert '# keep this comment' in text and '# anchored' in text and '# off for now' in text
    # removing the one added line gives the original back
    assert [line for line in text.splitlines(True) if key not in line] == EDITABLE.splitlines(True)


def test_ensure_signing_key_without_auth_section_does_nothing(tmp_path):
    path = write(tmp_path, 'gateway:\n  port: 1\n')
    assert config.ensure_signing_key(path) is False
    assert path.read_text() == 'gateway:\n  port: 1\n'


def test_describe_masks_every_secret(tmp_path):
    path = write(tmp_path)
    config.ensure_signing_key(path)
    cfg = config.load(path)
    text = '\n'.join(config.describe(cfg))
    for secret in ('top-secret', 'pinboard-secret', cfg.auth.jwt_signing_key):
        assert secret not in text
    assert 'abc' in text and '[42]' in text and 'PINBOARD_TOKEN=' in text and 'pinboard: disabled' in text


def test_the_tasks_and_browser_sections_are_gone_so_they_are_errors():
    for text in ('tasks:\n  due_today: [x]\n', 'browser:\n  channel: chrome\n'):
        with pytest.raises(config.ConfigError, match='Extra inputs are not permitted'):
            config.parse(text)


TUNNEL_ID = '123e4567-e89b-12d3-a456-426614174000'


def test_tunnel_credentials_default_to_the_only_json_in_the_cloudflared_folder(isolated_home):
    tunnel = config.TunnelConfig(name='t')
    with pytest.raises(config.ConfigError, match='no credentials'):
        config.tunnel_credentials(tunnel)
    folder = isolated_home / 'cloudflared'
    folder.mkdir(parents=True)
    (folder / 'cert.pem').write_text('not a credential')
    (folder / f'{TUNNEL_ID}.json').write_text('{}')
    found = config.tunnel_credentials(tunnel)
    assert found == folder / f'{TUNNEL_ID}.json'
    assert config.tunnel_id(found) == TUNNEL_ID
    (folder / 'other.json').write_text('{}')
    with pytest.raises(config.ConfigError, match='more than one'):
        config.tunnel_credentials(tunnel)


def test_tunnel_credentials_can_be_set_and_the_id_falls_back_to_the_file_contents(tmp_path):
    creds = tmp_path / 'creds.json'
    creds.write_text(json.dumps({'AccountTag': 'secret-tag', 'TunnelID': TUNNEL_ID, 'TunnelSecret': 'secret'}))
    assert config.tunnel_credentials(config.TunnelConfig(name='t', credentials_file=str(creds))) == creds
    assert config.tunnel_id(creds) == TUNNEL_ID
    with pytest.raises(config.ConfigError, match='does not exist'):
        config.tunnel_credentials(config.TunnelConfig(name='t', credentials_file=str(tmp_path / 'no.json')))
    creds.write_text('{"AccountTag": "secret-tag"}')
    with pytest.raises(config.ConfigError) as e:
        config.tunnel_id(creds)
    assert 'secret-tag' not in str(e.value)


def test_the_shipped_example_config_parses():
    example = Path(__file__).parent.parent / 'config.example.yaml'
    cfg = config.parse(example.read_text(encoding='utf-8'), example.name)
    assert [s.name for s in cfg.servers] == ['obsidian', 'pinboard', 'windows']
    assert cfg.auth is not None and cfg.tunnel is None
