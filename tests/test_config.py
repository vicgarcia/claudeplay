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
    '[tunnel]\ncommand = "c"',
    '[tunnel]\nname = "t"\nenabled = 1',
    'not toml [',
])
def test_parse_rejects_bad_config(text):
    with pytest.raises(config.ConfigError):
        config.parse(text)


def test_tunnel_section_and_public_host():
    cfg = config.parse("[gateway]\npublic_base_url = 'https://cp-x.example.net/'\n\n[tunnel]\nname = 'claudeplay'\n")
    assert cfg.tunnel == config.TunnelConfig(name='claudeplay', command=config.DEFAULT_CLOUDFLARED, enabled=True)
    assert cfg.tunnel_enabled and cfg.public_host == 'cp-x.example.net'
    assert cfg.endpoint_url == 'https://cp-x.example.net/mcp'
    off = config.parse("[tunnel]\nname = 't'\nenabled = false\n")
    assert not off.tunnel_enabled and off.public_host == ''
    assert config.parse('').tunnel is None


def test_load_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match='not found'):
        config.load(tmp_path / 'nope.toml')


EDITABLE = """# my config
[gateway]
port = 9000  # keep this comment

[auth]
client_id = 'abc'
client_secret = 'top-secret'
allowed_user_ids = [42]

[servers.todo]
command = 'todo.exe'
enabled = false  # off for now

[servers.todo.env]
TODO_CLIENT_SECRET = 'todo-secret'
"""


def write(tmp_path, text=EDITABLE):
    path = tmp_path / 'config.toml'
    path.write_bytes(text.encode())
    return path


def test_default_path_is_config_toml_in_the_data_dir(isolated_home):
    assert config.default_config_path() == isolated_home / 'config.toml'


def test_set_enabled_flips_only_that_flag_and_keeps_comments(tmp_path):
    path = write(tmp_path)
    config.set_enabled(path, 'todo', True)
    text = path.read_text()
    assert config.load(path).server('todo').enabled is True
    assert text == EDITABLE.replace('enabled = false  # off for now', 'enabled = true  # off for now')


def test_set_enabled_unknown_server(tmp_path):
    with pytest.raises(config.ConfigError, match='nope'):
        config.set_enabled(write(tmp_path), 'nope', True)


def test_set_enabled_keeps_crlf_files_crlf(tmp_path):
    path = write(tmp_path, EDITABLE.replace('\n', '\r\n'))
    config.set_enabled(path, 'todo', True)
    raw = path.read_bytes()
    assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')


def test_ensure_signing_key_writes_once(tmp_path):
    path = write(tmp_path)
    assert config.ensure_signing_key(path) is True
    key = config.load(path).auth.jwt_signing_key
    assert len(key) >= 48
    assert config.ensure_signing_key(path) is False
    assert config.load(path).auth.jwt_signing_key == key
    assert '# keep this comment' in path.read_text()


def test_ensure_signing_key_without_auth_section_does_nothing(tmp_path):
    path = write(tmp_path, '[gateway]\nport = 1\n')
    assert config.ensure_signing_key(path) is False
    assert path.read_text() == '[gateway]\nport = 1\n'


def test_describe_masks_every_secret(tmp_path):
    path = write(tmp_path)
    config.ensure_signing_key(path)
    cfg = config.load(path)
    text = '\n'.join(config.describe(cfg))
    for secret in ('top-secret', 'todo-secret', cfg.auth.jwt_signing_key):
        assert secret not in text
    assert 'abc' in text and '[42]' in text and 'TODO_CLIENT_SECRET=' in text and 'todo: disabled' in text


def test_tasks_section_is_parsed_and_checked():
    tasks = config.parse("[tasks]\ndue_today = ['Chores']\n[tasks.common_lists]\nChores = 'id-1'\nGrocery = 'id-2'\n").tasks
    assert tasks.common_lists == {'Chores': 'id-1', 'Grocery': 'id-2'}
    assert tasks.due_today == ('Chores',)
    assert config.parse('').tasks == config.TasksConfig()
    with pytest.raises(config.ConfigError, match='Health'):
        config.parse("[tasks]\ndue_today = ['Health']\n[tasks.common_lists]\nChores = 'id-1'\n")


def test_browser_section_defaults_to_edge_signed_in_nowhere():
    assert config.parse('').browser == config.BrowserConfig(channel='msedge', signed_in_sites=())
    cfg = config.parse("[browser]\nchannel = 'chrome'\nsigned_in_sites = [' GitHub.com ', 'reddit.com']\n")
    assert cfg.browser == config.BrowserConfig(channel='chrome', signed_in_sites=('github.com', 'reddit.com'))
    assert 'browser:  chrome; signed in on github.com, reddit.com' in config.describe(cfg)


@pytest.mark.parametrize('text', [
    "[browser]\nchannel = 'firefox'",
    "[browser]\nsigned_in_sites = 'github.com'",
    "[browser]\nsigned_in_sites = ['https://github.com']",
    "[browser]\nsigned_in_sites = ['github.com/login']",
    "[browser]\nsigned_in_sites = ['*.github.com']",
    "[browser]\nsigned_in_sites = ['']",
])
def test_browser_section_takes_known_channels_and_bare_hostnames(text):
    with pytest.raises(config.ConfigError, match='browser'):
        config.parse(text)
