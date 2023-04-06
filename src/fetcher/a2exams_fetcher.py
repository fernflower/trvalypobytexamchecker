"""
This module is intended to fetch html from the website with exam slots listed.

Before March 27, 2023 the fetcher functionality was a part of the checker module
as nothing but a plain GET request was required. But afterwards the antibot
mechanisms have been implemented, one of those being JS-generated exam slots list.
Now a plain GET request is not enough and the webpage has to be rendered by a
browser. For the purpose of clarity and possibility of horizontal scaling fetcher
functionality has been moved into a separate module.
"""
import argparse
import asyncio
import datetime
import logging
import os
import random
import sys
import urllib
import urllib3

from pyvirtualdisplay import Display
import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait


DATETIME_FORMAT = '%d/%m/%Y %H:%M:%S'
URL = os.getenv('URL', 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/')
# interval to wait before repeating the request
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))
# These will be used to push data to the centralized storage
URL_POST = os.getenv('URL_POST')
TOKEN_POST = os.getenv('TOKEN_POST')
# Since Apr 1, 2023 connecting via proxy doesn't really work, but let's keep it here just in case
PROXY = os.getenv('PROXY', 'no')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')
HEALTH = os.path.join(OUTPUT_DIR, 'healthy')
HEALTH_THRESHOLD = int(os.getenv('HEALTH_THRESHOLD', '60'))
PAGE_LOAD_LIMIT_SECONDS = 20

# globals to reuse for browser page displaying
DISPLAY = None
BROWSER = None

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_time_since_last_fetched():
    """
    Time in ms since last successful fetch based on file modification time
    """
    last_fetch_time = os.path.getmtime(LAST_FETCHED)
    current = datetime.datetime.now().timestamp()
    return current - last_fetch_time


def _close_browser():
    global BROWSER
    global DISPLAY
    if BROWSER:
        BROWSER.quit()
        BROWSER = None
    if DISPLAY:
        DISPLAY.stop()
        DISPLAY = None


def _get_useragent():
    # NOTE(ivasilev) Setting useragent with ua.random is a great idea in theory but in practice it leads to
    # recaptcha warnings as recaptch needs latest version of browsers to run. So let's hardcode it here to
    # something 100% acceptable and configure fake-useragent with custom data file later
    # ua = fake_useragent.UserAgent()
    # useragent = ua.random
    useragents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.2; rv:111.0) Gecko/20100101 Firefox/111.0',
            'Mozilla/5.0 (X11; Linux x86_64; rv:107.0) Gecko/20100101 Firefox/107.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36']
    return useragents[random.randint(0, len(useragents) - 1)]


def _get_browser(force=False):
    global DISPLAY
    global BROWSER
    if not force and BROWSER:
        return BROWSER
    DISPLAY = Display(visible=0, size=(1420, 1080))
    DISPLAY.start()
    logger.info('Initialized virtual display')
    options = webdriver.firefox.options.Options()
    options.set_preference("intl.accept_languages", 'cs-CZ')
    # set user-agent
    useragent = _get_useragent()
    logger.info("User-Agent for this request will be %s", useragent)
    options.set_preference('general.useragent.override', useragent)
    options.set_preference('dom.webdriver.enabled', False)
    options.set_preference('useAutomationExtension', False)
    if PROXY not in ('0', 'None', 'no'):
        logger.info('Setting up browser proxy %s', PROXY)
        ip, port = PROXY.rsplit(':', 1)
        options.set_preference('network.proxy.type', 1)
        options.set_preference('network.proxy.socks', ip)
        options.set_preference('network.proxy.socks_port', int(port))
        options.set_preference('network.proxy.socks_remote_dns', True)
    BROWSER = webdriver.Firefox(options=options)
    BROWSER.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    # emulate some user actions tbd
    # BROWSER.maximize_window()
    return BROWSER


async def _do_fetch_with_browser(url, wait_for_javascript=PAGE_LOAD_LIMIT_SECONDS, wait_for_id='select-town'):
    browser = _get_browser()
    try:
        browser.get(url)
        await asyncio.sleep(random.randint(0, 4))
        scroll_to = random.randint(400, 700)
        browser.execute_script(f'window.scrollTo(0, {scroll_to})')
        WebDriverWait(browser, wait_for_javascript).until(lambda x: x.find_element(By.ID, wait_for_id))
        page_source = browser.page_source
    except (WebDriverException, urllib3.exceptions.MaxRetryError) as err:
        logger.error('An error has occured during page loading %s', err)
        _close_browser()
        return

    return page_source


async def _do_fetch(url):
    try:
        proxies = {} if PROXY in ('0', 'None', 'no') else {'https': f'socks5h://{PROXY}'}
        if proxies:
            logger.info("Using proxy %s for request", PROXY)
        resp = requests.get(url, proxies=proxies, headers={'Cache-Control': 'no-cache',
                                                           'Pragma': 'no-cache',
                                                           'User-agent': _get_useragent()})
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
        return
    except Exception as exc:
        logger.error('Some unexpected exception has occured %s..', exc)
        return
    if resp.ok:
        return resp.text


async def fetch(url, filename=None, retry_interval=POLLING_INTERVAL, fetch_func=_do_fetch_with_browser):
    """
    Fetches recent version of registration website. If request fails for some reason will retry until success.
    Return html and saves it in a file if filename parameter is passed.
    """
    res = await fetch_func(url=url)
    while not res:
        retry_in = int(retry_interval / 3 + random.randint(1, int(2 * retry_interval / 3)))
        print(f"Looks like connection error, will try {url} again later in {retry_in}")
        await asyncio.sleep(retry_in)
        res = await fetch_func(url=url)
    # record new data
    if filename:
        with open(filename, 'w') as f:
            f.write(res)
    return res


def timestamp_to_str(timestamp, dt_format=DATETIME_FORMAT):
    """Convert timestamp to a human-readable format"""
    try:
        int_timestamp = int(float(timestamp))
        return datetime.datetime.fromtimestamp(int_timestamp).strftime(dt_format)
    except (ValueError, TypeError):
        return ''


def post(html, url=URL_POST, token=TOKEN_POST, substitute_baseurl=True, old_url=URL):
    if not url or not token:
        logger.warn("Both url and token have to be set, no data will be pushed!")
        return
    try:
        proxies = {} if PROXY in ('0', 'None', 'no') else {'https': f'socks5h://{PROXY}'}
        if proxies:
            logger.info("Using proxy %s for request", PROXY)
        if substitute_baseurl:
            # change URL's baseurl to URL_POST
            original_baseurl = urllib.parse.urlparse(old_url).hostname
            new_baseurl = urllib.parse.urlparse(url).hostname
            html = html.replace(original_baseurl, new_baseurl)
        data = {'token': token,
                # XXX FIXME If date can be extracted from html this would be much better than setting
                # it explicitly
                'date': timestamp_to_str(datetime.datetime.now().timestamp()),
                'html': html}
        resp = requests.post(url, data=data, proxies=proxies,
                             headers={'Cache-Control': 'no-cache',
                                      'Pragma': 'no-cache',
                                      'User-agent': _get_useragent(),
                                      'Content-Type': 'application/octet-stream'})
        if not resp.ok:
            logger.error('Push was unsuccessful')
        return html
    except Exception as exc:
        logger.error('Some unexpected exception during push has occured %s..', exc)
        return


def _parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', help='Interval to poll a website with exams registration',
                        default=POLLING_INTERVAL, type=int)
    return parser.parse_args(args)


async def main(fetch_func=_do_fetch_with_browser, retry=POLLING_INTERVAL):
    """ The infinite loop of fetch -> push -> wait -> fetch -> push ... """
    parsed_args = _parse_args(sys.argv[1:])
    # clear healthcheck state if it's present from previous runs
    if os.path.isfile(HEALTH):
        os.unlink(HEALTH)
    try:
        while True:
            new_data = await fetch(url=URL, filename=LAST_FETCHED)
            if new_data:
                # push new data to the centralized portal
                logger.info('New data has been successfully fetched')
                post(new_data, url=URL_POST, token=TOKEN_POST)
            else:
                logger.warn('No new data has been fetched! Will retry later')
            # update health check file
            if get_time_since_last_fetched() < HEALTH_THRESHOLD:
                logger.debug('State: healthy')
                if not os.path.isfile(HEALTH):
                    with open(HEALTH, 'w') as f:
                        f.write('alive')
            else:
                logger.warning('State: unhealthy, last fetch was > %s seconds ago', HEALTH_THRESHOLD)
                if os.path.isfile(HEALTH):
                    os.unlink(HEALTH)
            # Wait a bit before the next check
            await asyncio.sleep(parsed_args.interval)
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')
        _close_browser()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main())
    # asyncio.run(main())
