import pytest

from claudeplay import config

SAMPLE = '''
[gateway]
port = 9000
public_base_url = 'https://abc.example.net/'

[auth]
client_id = '${GH_ID}'
allowed_user_ids = [12345]

[servers.obsidian]
command = '${HOME_DIR}/obsidian-mcp.exe'
args = ['--vault', '${VAULT}']

[servers.obsidian.env]
TZ = 'America/New_York'

[servers.todo]
command = 'todo-mcp.exe'
enabled = false

[servers.todo.env]
TODO_CLIENT_SECRET = '${TODO_CLIENT_SECRET}'
'''


def test_parse_basic():
    cfg = config.parse(SAMPLE)
    assert cfg.port == 9000
    assert cfg.host == '127.0.0.1'
    assert [s.name for s in cfg.servers] == ['obsidian', 'todo']
    assert cfg.server('obsidian').env == {'TZ': 'America/New_York'}
    assert cfg.server('todo').enabled is False
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
    with pytest.raises(config.ConfigError, match='TODO_CLIENT_SECRET'):
        config.resolve(config.parse(SAMPLE).server('todo'), {})


@pytest.mark.parametrize('text', [
    '[servers.x]\nargs = []',
    '[servers.x]\ncommand = "c"\nargs = "nope"',
    '[servers.x]\ncommand = "c"\nenabled = "yes"',
    '[servers.x]\ncommand = "c"\n[servers.x.env]\nA = 1',
    '[gateway]\nport = 0',
    '[auth]\nallowed_user_ids = ["123"]',
    'not toml [',
])
def test_parse_rejects_bad_config(text):
    with pytest.raises(config.ConfigError):
        config.parse(text)


def test_load_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match='not found'):
        config.load(tmp_path / 'nope.toml')


def test_overrides_round_trip_and_precedence():
    cfg = config.parse(SAMPLE)
    assert config.load_overrides() == {}
    config.save_overrides({'todo': True, 'obsidian': False})
    overrides = config.load_overrides()
    assert config.is_enabled(cfg.server('todo'), overrides) is True
    assert config.is_enabled(cfg.server('obsidian'), overrides) is False
    assert config.is_enabled(cfg.server('todo'), {}) is False


def test_overrides_ignore_garbage():
    config.overrides_path().parent.mkdir(parents=True)
    config.overrides_path().write_text('{not json')
    assert config.load_overrides() == {}
