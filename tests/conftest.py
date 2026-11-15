import sys
from pathlib import Path

import pytest

from claudeplay import config

FAKE_SERVER = str(Path(__file__).parent / 'fake_server.py')


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    ''' keep tests away from the real config and credentials '''
    monkeypatch.setenv('CLAUDEPLAY_HOME', str(tmp_path / 'home'))
    return tmp_path / 'home'


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    ''' and away from the real logs '''
    monkeypatch.setenv('CLAUDEPLAY_LOGS', str(tmp_path / 'logs'))
    return tmp_path / 'logs'


def fake(name: str, **kwargs) -> config.ServerConfig:
    ''' a server config that launches the fake backend with the current interpreter '''
    return config.ServerConfig(name=name, command=sys.executable, args=(FAKE_SERVER,), **kwargs)
