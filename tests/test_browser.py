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
# a page with the clutter main_only drops, around an article whose own header and footer it keeps
ARTICLE = ('<html><head><title>post</title></head><body>'
           '<header>site banner</header><nav>menu</nav>'
           '<main><article><header>the headline</header><p>the story</p><aside>related links</aside>'
           '<footer>the byline</footer></article></main>'
           '<aside>sidebar</aside><div role="dialog">accept cookies</div><footer>copyright</footer></body></html>')
# no main or article: main_only falls back to the body, still without its clutter
PLAIN = '<html><body><nav>menu</nav><p>just text</p><footer>copyright</footer></body></html>'
PAGES = {'/': PAGE, '/article': ARTICLE, '/plain': PLAIN, '/long': f'<html><body><p>{"abcdefghij" * 3}</p></body></html>'}


class Site(BaseHTTPRequestHandler):
    ''' a page that builds its text in javascript '''

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(PAGES[self.path].encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def port():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def fetch(url: str, **args) -> dict:
    async def steps():
        async with Client(browser.server(config.BrowserConfig())) as client:
            return json.loads((await client.call_tool('fetch_page', {'url': url, **args})).content[0].text)
    return asyncio.run(steps())


def fetch_or_skip(url: str, **args) -> dict:
    try:
        return fetch(url, **args)
    except ToolError as e:
        if 'browser failed' in str(e):
            pytest.skip(f'no headless browser here: {e}')
        raise


def test_pages_come_back_after_their_javascript_runs(port):
    page = fetch_or_skip(f'http://127.0.0.1:{port}/')
    assert page['title'] == 'rendered'
    assert page['text'] == 'built by javascript'
    assert page['status'] == 200 and page['truncated'] is False
    assert page['offset'] == 0 and page['total_chars'] == len('built by javascript')
    assert 'next_offset' not in page


def test_main_only_keeps_the_article_and_drops_the_clutter(port):
    whole = fetch_or_skip(f'http://127.0.0.1:{port}/article')
    assert 'site banner' in whole['text'] and 'accept cookies' in whole['text']
    main = fetch_or_skip(f'http://127.0.0.1:{port}/article', main_only=True)
    assert main['title'] == 'post'
    assert main['text'].split() == ['the', 'headline', 'the', 'story', 'the', 'byline']


def test_main_only_without_a_main_region_uses_the_body(port):
    page = fetch_or_skip(f'http://127.0.0.1:{port}/plain', main_only=True)
    assert page['text'].strip() == 'just text'


def test_long_pages_are_read_in_parts(port, monkeypatch):
    monkeypatch.setattr(browser, 'MAX_CHARS', 12)
    url = f'http://127.0.0.1:{port}/long'
    parts, offset = [], 0
    while True:
        page = fetch_or_skip(url, offset=offset)
        assert page['offset'] == offset and page['total_chars'] == 30
        parts.append(page['text'])
        if not page['truncated']:
            break
        offset = page['next_offset']
    assert [len(p) for p in parts] == [12, 12, 6]
    assert ''.join(parts) == 'abcdefghij' * 3


def test_an_offset_past_the_end_says_how_long_the_page_is(port):
    fetch_or_skip(f'http://127.0.0.1:{port}/long')
    with pytest.raises(ToolError, match='past the end of the page, which has 30 characters'):
        fetch(f'http://127.0.0.1:{port}/long', offset=30)


def test_a_negative_offset_is_refused_before_loading(port):
    with pytest.raises(ToolError, match='offset must be 0 or more'):
        fetch(f'http://127.0.0.1:{port}/long', offset=-1)


@pytest.mark.parametrize('url', ['file:///C:/Windows/win.ini', 'C:/Windows/win.ini', 'javascript:alert(1)', 'about:blank', 'https://', 'example.com'])
def test_only_web_addresses_are_loaded(url):
    with pytest.raises(ToolError, match='not a web address'):
        fetch(url)
