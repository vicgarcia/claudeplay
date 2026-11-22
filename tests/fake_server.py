'''a tiny stdio mcp server used as a backend in tests'''

import os
import time

from fastmcp import FastMCP

mcp = FastMCP('fake')


@mcp.tool()
def echo(text: str) -> str:
    ''' return the text unchanged '''
    return text


@mcp.tool()
def ping() -> str:
    return 'pong'


if __name__ == '__main__':
    # FAKE_STARTUP_DELAY stands in for a backend that is slow to start, like uvx resolving its environment
    time.sleep(float(os.environ.get('FAKE_STARTUP_DELAY', '0')))
    mcp.run(transport='stdio', show_banner=False)
