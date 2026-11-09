'''web pages read in a headless browser built into the gateway, fresh for every fetch and signed in nowhere'''

from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from . import config

NAME = 'browser'
MAX_CHARS = 100_000
LOAD_TIMEOUT_MS = 30_000
# after the page loads, how long to wait for javascript to stop fetching before reading it anyway
SETTLE_MS = 5_000

# the page's own content: the main region if it marks one, without menus, sidebars, banners and dialogs.
# it edits the live page, which is thrown away after the read. header and footer stay inside an article,
# where they hold its headline and byline.
MAIN_TEXT = '''() => {
    const articles = document.querySelectorAll('article');
    const root = document.querySelector('main, [role=main]') || (articles.length === 1 ? articles[0] : document.body);
    const noise = 'nav, aside, dialog, [role=navigation], [role=complementary], [role=dialog], [role=alertdialog], [aria-modal=true]';
    root.querySelectorAll(noise).forEach(e => e.remove());
    root.querySelectorAll('header, footer, [role=banner], [role=contentinfo]').forEach(e => {
        if (!e.parentElement || !e.parentElement.closest('article')) e.remove();
    });
    return root.innerText;
}'''


def _check_url(url: str) -> str:
    ''' only web addresses: file:// and friends would read the laptop's own files '''
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ToolError(f'not a web address, it must start with http:// or https://: {url}')
    return url


def _reason(e: PlaywrightError) -> str:
    # the first line only: the rest is playwright's call log
    return str(e).strip().splitlines()[0]


def _check_offset(offset: int) -> int:
    if offset < 0:
        raise ToolError(f'offset must be 0 or more, not {offset}')
    return offset


async def _read(context, url: str, offset: int = 0, main_only: bool = False) -> dict:
    page = await context.new_page()
    # some sites refuse a browser that announces itself as headless
    agent = await page.evaluate('navigator.userAgent')
    await context.set_extra_http_headers({'User-Agent': agent.replace('HeadlessChrome', 'Chrome')})
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=LOAD_TIMEOUT_MS)
    except PlaywrightError as e:
        raise ToolError(f'could not load {url}: {_reason(e)}') from None
    try:
        await page.wait_for_load_state('networkidle', timeout=SETTLE_MS)
    except PlaywrightTimeout:
        pass
    title = await page.title()
    text = await page.evaluate(MAIN_TEXT) if main_only else await page.inner_text('body')
    if offset and offset >= len(text):
        raise ToolError(f'offset {offset} is past the end of the page, which has {len(text)} characters')
    end = offset + MAX_CHARS
    result = {
        'url': page.url,
        'status': response.status if response else None,
        'title': title,
        'text': text[offset:end],
        'offset': offset,
        'total_chars': len(text),
        'truncated': len(text) > end,
    }
    if result['truncated']:
        result['next_offset'] = end
    return result


def server(cfg: config.BrowserConfig) -> FastMCP:
    browser = FastMCP(NAME)

    async def fetch_page(url: str, offset: int = 0, main_only: bool = False) -> dict:
        ''' the title and visible text of a web page, after its javascript has run '''
        url = _check_url(url)
        offset = _check_offset(offset)
        try:
            async with async_playwright() as p:
                launched = await p.chromium.launch(channel=cfg.channel, headless=True)
                try:
                    return await _read(await launched.new_context(), url, offset, main_only)
                finally:
                    await launched.close()
        except ToolError:
            raise
        except PlaywrightError as e:
            raise ToolError(f'the browser failed: {_reason(e)}') from None

    browser.tool(fetch_page)
    return browser
