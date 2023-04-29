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

import utils


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


def _close_browser():
    global BROWSER
    global DISPLAY
    if BROWSER:
        BROWSER.quit()
        BROWSER = None
    if DISPLAY:
        DISPLAY.stop()
        DISPLAY = None



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
    options.set_preference("http.response.timeout", PAGE_LOAD_LIMIT_SECONDS)
    # set user-agent
    useragent = utils.get_useragent()
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


def get_last_fetch_time(human_readable=False):
    """
    Return timestamp of the last modification to the last_fetched.html file or
    a human-readable date and time if requested.
    """
    last_fetched = os.path.getmtime(LAST_FETCHED)
    if not human_readable:
        return last_fetched
    return utils.timestamp_to_str(last_fetched)


def get_time_since_last_fetched():
    """
    Time in ms since last successful fetch based on file modification time
    """
    last_fetch_time = get_last_fetch_time()
    current = datetime.datetime.now().timestamp()
    return current - last_fetch_time


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
                'date': get_last_fetch_time(human_readable=False),
                'html': html}
        resp = requests.post(url, data=data, proxies=proxies,
                             headers={'Cache-Control': 'no-cache',
                                      'Pragma': 'no-cache',
                                      'User-agent': utils.get_useragent(),
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


def _remove_health_file(a_file):
    if os.path.isfile(a_file):
        os.unlink(a_file)
    else:
        logger.debug('No such file %s', a_file)


def _create_health_file(a_file):
    if not os.path.isfile(HEALTH):
        with open(HEALTH, 'w') as f:
            f.write('alive')
    else:
        logger.debug('File %s already exists', a_file)


async def run_once(retry_interval=POLLING_INTERVAL, fetch_func=_do_fetch_with_browser):
    new_data = await fetch(url=URL, retry_interval=retry_interval, filename=LAST_FETCHED, fetch_func=fetch_func)
    if new_data:
        # push new data to the centralized portal
        logger.info('[%s] New data has been successfully fetched', get_last_fetch_time(human_readable=True))
        res = post(new_data, url=URL_POST, token=TOKEN_POST)
        if not res:
            logger.warning('No data has been pushed!')
    else:
        logger.warning('No new data has been fetched! Will retry later')
    # update health check file
    if get_time_since_last_fetched() < HEALTH_THRESHOLD:
        logger.debug('State: healthy')
        _create_health_file(HEALTH)
    else:
        logger.warning('State: unhealthy, last fetch was > %s seconds ago', HEALTH_THRESHOLD)
        _remove_health_file(HEALTH)


async def main(retry=POLLING_INTERVAL):
    """ The infinite loop of fetch -> push -> wait -> fetch -> push ... """
    parsed_args = _parse_args(sys.argv[1:])
    # clear healthcheck state if it's present from previous runs
    _remove_health_file(HEALTH)
    try:
        while True:
            await run_once()
            # Wait a bit before the next check
            await asyncio.sleep(parsed_args.interval)
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')
        _close_browser()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main())
    # asyncio.run(main())
