import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from claudeplay import browser, config

PAGES = {
    '/js': '<html><head><title>rendered</title></head><body><div id="out">loading</div>'
           '<script>document.getElementById("out").textContent = "built by javascript"</script></body></html>',
    '/login': '<html><body>signed in</body></html>',
}


class Site(BaseHTTPRequestHandler):
    ''' /js builds its text in javascript, /login sets a session cookie, /whoami echoes the cookie it was sent '''

    def do_GET(self):
        if self.path == '/whoami':
            body = f'<html><body>cookie: {self.headers.get("Cookie") or "none"}</body></html>'
        else:
            body = PAGES[self.path]
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        if self.path == '/login':
            # no expiry: a browser would drop it on closing, and the profile has to keep it anyway
            self.send_header('Set-Cookie', 'session=abc123; Path=/')
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def port():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def fetch(cfg: config.BrowserConfig, *urls: str) -> list[dict]:
    async def steps():
        async with Client(browser.server(cfg)) as client:
            return [json.loads((await client.call_tool('fetch_page', {'url': u})).content[0].text) for u in urls]
    return asyncio.run(steps())


def edge_or_skip(cfg, url):
    try:
        return fetch(cfg, url)[0]
    except ToolError as e:
        if 'browser failed' in str(e):
            pytest.skip(f'no headless browser here: {e}')
        raise


def test_pages_come_back_after_their_javascript_runs(port):
    page = edge_or_skip(config.BrowserConfig(), f'http://127.0.0.1:{port}/js')
    assert page['title'] == 'rendered'
    assert page['text'] == 'built by javascript'
    assert page['status'] == 200 and page['signed_in'] is False and page['truncated'] is False


def test_only_signed_in_sites_get_the_profile_and_its_cookies(port, isolated_home):
    cfg = config.BrowserConfig(signed_in_sites=('127.0.0.1',))
    edge_or_skip(cfg, f'http://127.0.0.1:{port}/login')
    mine, theirs = fetch(cfg, f'http://127.0.0.1:{port}/whoami', f'http://localhost:{port}/whoami')
    assert mine['signed_in'] is True and mine['text'] == 'cookie: session=abc123'
    assert theirs['signed_in'] is False and theirs['text'] == 'cookie: none'
    assert browser.profile_dir() == isolated_home / 'browser' and browser.profile_dir().exists()
    assert browser.clear() is True and not browser.profile_dir().exists()
    assert browser.clear() is False


@pytest.mark.parametrize('url', ['file:///C:/Windows/win.ini', 'C:/Windows/win.ini', 'javascript:alert(1)', 'about:blank', 'https://', 'example.com'])
def test_only_web_addresses_are_loaded(url):
    with pytest.raises(ToolError, match='not a web address'):
        fetch(config.BrowserConfig(), url)


@pytest.mark.parametrize('url, signed_in', [
    ('https://github.com/notifications', True),
    ('https://gist.GitHub.com/x', True),
    ('https://notgithub.com/', False),
    ('https://github.com.evil.example/', False),
    ('https://example.com/?next=https://github.com', False),
])
def test_signed_in_sites_match_the_host_and_its_subdomains_only(url, signed_in):
    assert browser.is_signed_in_site(url, ('github.com',)) is signed_in
