import sys
from pathlib import Path

import pytest

from claudeplay import config

FAKE_SERVER = str(Path(__file__).parent / 'fake_server.py')


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    ''' keep tests away from the real data dir, config and overrides '''
    monkeypatch.setenv('CLAUDEPLAY_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('CLAUDEPLAY_CONFIG', raising=False)
    return tmp_path / 'home'


def fake(name: str, **kwargs) -> config.ServerConfig:
    ''' a server config that launches the fake backend with the current interpreter '''
    return config.ServerConfig(name=name, command=sys.executable, args=(FAKE_SERVER,), **kwargs)
