import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from claudeplay import browser, config

PAGE = ('<html><head><title>rendered</title></head><body><div id="out">loading</div>'
        '<script>document.getElementById("out").textContent = "built by javascript"</script></body></html>')


class Site(BaseHTTPRequestHandler):
    ''' a page that builds its text in javascript '''

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def port():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def fetch(url: str) -> dict:
    async def steps():
        async with Client(browser.server(config.BrowserConfig())) as client:
            return json.loads((await client.call_tool('fetch_page', {'url': url})).content[0].text)
    return asyncio.run(steps())


def test_pages_come_back_after_their_javascript_runs(port):
    try:
        page = fetch(f'http://127.0.0.1:{port}/')
    except ToolError as e:
        if 'browser failed' in str(e):
            pytest.skip(f'no headless browser here: {e}')
        raise
    assert page['title'] == 'rendered'
    assert page['text'] == 'built by javascript'
    assert page['status'] == 200 and page['truncated'] is False


@pytest.mark.parametrize('url', ['file:///C:/Windows/win.ini', 'C:/Windows/win.ini', 'javascript:alert(1)', 'about:blank', 'https://', 'example.com'])
def test_only_web_addresses_are_loaded(url):
    with pytest.raises(ToolError, match='not a web address'):
        fetch(url)
