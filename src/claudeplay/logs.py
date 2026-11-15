'''logging setup: rotating file under the logs dir; never arguments, tokens or query strings'''

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

LOG_NAME = 'claudeplay.log'
_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'


def setup(directory: Path | None = None, console: bool = False) -> Path:
    ''' attach a rotating file handler to the claudeplay and fastmcp loggers '''
    directory = directory or config.logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_NAME

    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter(_FORMAT))
    handlers: list[logging.Handler] = [handler]
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_FORMAT))
        handlers.append(stream)

    for name, level in (('claudeplay', logging.INFO), ('fastmcp', logging.WARNING)):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers = list(handlers)
        logger.propagate = False

    # uvicorn's access log would record oauth callback query strings (codes, state)
    logging.getLogger('uvicorn.access').disabled = True
    return path
