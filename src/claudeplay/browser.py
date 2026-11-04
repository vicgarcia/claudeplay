'''web pages read in a headless browser built into the gateway: a clean one for most sites, and a
signed-in profile, kept in the data dir, for the sites the user allows'''

import asyncio
import shutil
import time
from pathlib import Path
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
# the profile only ever signs in by hand, so it never needs the automation banner or flag
NOT_AUTOMATED = ['--enable-automation']
# how long sign-ins that would end with the browser session are kept instead
SESSION_DAYS = 30


def profile_dir() -> Path:
    return config.data_dir() / 'browser'


def is_signed_in_site(url: str, sites: tuple[str, ...]) -> bool:
    ''' true for a url on one of the sites, or a subdomain of one '''
    host = (urlsplit(url).hostname or '').casefold()
    return any(host == site or host.endswith(f'.{site}') for site in sites)


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


async def _page(context):
    ''' a page that doesn't announce itself as headless, which some sites refuse '''
    page = context.pages[0] if context.pages else await context.new_page()
    agent = await page.evaluate('navigator.userAgent')
    await context.set_extra_http_headers({'User-Agent': agent.replace('HeadlessChrome', 'Chrome')})
    return page


async def _read(context, url: str, signed_in: bool) -> dict:
    page = await _page(context)
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=LOAD_TIMEOUT_MS)
    except PlaywrightError as e:
        raise ToolError(f'could not load {url}: {_reason(e)}') from None
    try:
        await page.wait_for_load_state('networkidle', timeout=SETTLE_MS)
    except PlaywrightTimeout:
        pass
    text = await page.inner_text('body')
    return {
        'url': page.url,
        'status': response.status if response else None,
        'title': await page.title(),
        'signed_in': signed_in,
        'text': text[:MAX_CHARS],
        'truncated': len(text) > MAX_CHARS,
    }


async def _fetch_clean(url: str, channel: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=channel, headless=True)
        try:
            return await _read(await browser.new_context(), url, signed_in=False)
        finally:
            await browser.close()


def _lasting(cookies: list[dict]) -> list[dict]:
    ''' session cookies, which the browser drops when it closes, given an expiry so the profile keeps them '''
    expires = time.time() + SESSION_DAYS * 86400
    return [c | {'expires': expires} for c in cookies if c.get('expires', -1) < 0]


async def _fetch_signed_in(url: str, channel: str) -> dict:
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir(), channel=channel, headless=True, ignore_default_args=NOT_AUTOMATED)
        try:
            page = await _read(context, url, signed_in=True)
            # the site may have refreshed its session cookie while the page loaded
            if lasting := _lasting(await context.cookies()):
                await context.add_cookies(lasting)
            return page
        finally:
            await context.close()


def server(cfg: config.BrowserConfig) -> FastMCP:
    browser = FastMCP(NAME)
    # a profile can only be open once, so signed-in fetches take turns
    profile = asyncio.Lock()

    async def fetch_page(url: str) -> dict:
        ''' the title and visible text of a web page, after its javascript has run '''
        url = _check_url(url)
        try:
            if not is_signed_in_site(url, cfg.signed_in_sites):
                return await _fetch_clean(url, cfg.channel)
            async with profile:
                return await _fetch_signed_in(url, cfg.channel)
        except ToolError:
            raise
        except PlaywrightError as e:
            raise ToolError(f'the browser failed: {_reason(e)}') from None

    browser.tool(fetch_page)
    return browser


def login(cfg: config.BrowserConfig, url: str | None = None) -> None:
    ''' open the signed-in profile in a window and wait for it to be closed, so the user can sign in to sites by hand '''
    from playwright.sync_api import Error, sync_playwright
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir(), channel=cfg.channel, headless=False, no_viewport=True, ignore_default_args=NOT_AUTOMATED)
        page = context.pages[0] if context.pages else context.new_page()
        if url:
            page.goto(_check_url(url))
        # the cookies can't be read once the window is closed, so keep the latest while it is open
        cookies: list[dict] = []
        while True:
            try:
                cookies = context.cookies()
                context.wait_for_event('close', timeout=1000)
                break
            except Error:
                if not context.pages:
                    break
        if lasting := _lasting(cookies):
            context = p.chromium.launch_persistent_context(profile_dir(), channel=cfg.channel, headless=True)
            context.add_cookies(lasting)
            context.close()


def clear() -> bool:
    ''' delete the signed-in profile, signing out of every site; returns False if there was none '''
    if not profile_dir().exists():
        return False
    shutil.rmtree(profile_dir())
    return True
