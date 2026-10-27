'''a tiny stdio mcp server used as a backend in tests'''

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
    mcp.run(transport='stdio', show_banner=False)
