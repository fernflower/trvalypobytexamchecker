"""
This module is intended to fetch html from the website with exam slots listed.

Before March 27, 2023 the fetcher functionality was a part of the checker module
as nothing but a plain GET request was required. But afterwards the antibot
mechanisms have been implemented, one of those being JS-generated exam slots list.
Now a plain GET request is not enough and the webpage has to be rendered by a
browser. For the purpose of clarity and possibility of horizontal scaling fetcher
functionality has been moved into a separate module.
"""
import asyncio
import datetime
import json
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

from checker import a2exams_checker
import utils


URL = os.getenv('URL', 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/')
# interval to wait before repeating the request
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))
# These will be used to push data to the centralized storage
URL_POST = os.getenv('URL_POST')
URL_POST_JSON = os.getenv('URL_POST_JSON')
TOKEN_POST = os.getenv('TOKEN_POST')
TOKEN_GET = os.getenv('TOKEN_GET')
# Since Apr 1, 2023 connecting via proxy doesn't really work, but let's keep it here just in case
PROXY = os.getenv('PROXY', 'no')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')
HEALTH = os.path.join(OUTPUT_DIR, 'healthy')
HEALTH_THRESHOLD = int(os.getenv('HEALTH_THRESHOLD', '60'))
PAGE_LOAD_LIMIT_SECONDS = 20
# Initial time to wait if the fetch didn't get through
DEFAULT_BACKOFF = int(os.getenv('DEFAULT_BACKOFF', '10'))
CAP_BACKOFF = int(os.getenv('CAP_BACKOFF', '360'))
COOKIE = os.getenv('COOKIE')
COOKIE_NAME = os.getenv('COOKIE_NAME', 'PHPSESSID')
CURL = os.getenv('CURL', True)
EMAIL_ALERT = os.getenv('EMAIL_ALERT', 'cookie refresh')
SEND_MAIL = os.getenv('SEND_MAIL', 'false').lower() in ['t', 'true', '1']
LAY_LOW = int(os.getenv('LAY_LOW', 333))
STATUS_URL = os.getenv('STATUS_URL')
FETCHER_ID = os.getenv('FETCHER_ID')
BACKUP = os.getenv('BACKUP', 'false').lower() in ['t', 'true', '1']
FETCH_DETAILED = os.getenv('FETCH_DETAILED', 'false').lower() in ['t', 'true', 1]

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


async def _do_fetch_with_browser(url, wait_for_javascript=PAGE_LOAD_LIMIT_SECONDS, wait_for_id='select-town',
                                 cookie=None):

    def _has_recaptcha(browser):
        captcha = browser.find_elements(By.CSS_SELECTOR,
                                        "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']")
        return bool(captcha)

    browser = _get_browser()
    try:
        browser.get(url)
        # try to set session cookies
        if cookie:
            session_cookie = {'name': COOKIE_NAME,
                              'value': cookie,
                              'path': '/',
                              'domain': 'cestina-pro-cizince.cz',
                              'secure': False,
                              'httpOnly': False,
                              'sameSite': 'None'}
            browser.add_cookie(session_cookie)
        WebDriverWait(browser, wait_for_javascript).until(
                lambda x: _has_recaptcha(x) or x.find_element(By.ID, wait_for_id))
        # Show current cookie
        logger.debug(f'Current session cookie is %s', (browser.get_cookie(COOKIE_NAME) or {}).get('value'))
        if _has_recaptcha(browser):
            # if recaptcha has been discovered -> give ample time to solve it, let's say 3x the maximum
            logger.warning('Recaptcha has been hit, solve it please to continue')
            # 120 magic constant means 2 mins recaptcha form is valid
            WebDriverWait(browser, 120).until(lambda x: x.find_element(By.ID, wait_for_id))
        page_source = browser.page_source
    except (WebDriverException, urllib3.exceptions.MaxRetryError) as err:
        logger.error('An error has occured during page loading %s', err)
        _close_browser()
        return None, err

    return page_source, None


async def report_fetcher_status(status, token=TOKEN_POST, url=STATUS_URL):
    data = {'token': token, 'status': status, 'id': FETCHER_ID}
    res, _ = await utils.do_post_async(url=url, data=data)
    return res


async def get_fetcher_status(token=TOKEN_GET, url=STATUS_URL):
    status, _ = await utils.do_fetch_async(url=f'{url}?token={token}')
    try:
        return json.loads(status)
    except json.JSONDecodeError:
        return {}


async def fetch(url, filename=None, retry_interval=POLLING_INTERVAL, fetch_func=_do_fetch_with_browser, attempts=3,
                cookie=None):
    """
    Fetches recent version of registration website. If request fails for some reason will retry N times.
    Returns a tuple (html, err). html is saved it in a file if filename parameter is passed.
    If an error/exception is raised in the process, the html is guaranteed to be None.
    """
    res, err = await fetch_func(url=url, cookie=cookie)
    attempts_left = attempts
    while attempts_left and not res:
        attempts_left -= 1
        retry_in = int(retry_interval / 3 + random.randint(1, int(2 * retry_interval / 3)))
        print(f"Looks like connection error, will try {url} again later in {retry_in}")
        await asyncio.sleep(retry_in)
        res, err = await fetch_func(url=url)
    # record new data if there is any
    if filename and res:
        with open(filename, 'w') as f:
            f.write(res)
    return res, err


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


async def post(html, url=URL_POST, token=TOKEN_POST, substitute_baseurl=True, old_url=URL,
               content_type='application/octet-stream'):
    if not url or not token:
        logger.warning("Both url and token have to be set, no data will be pushed!")
        return
    if substitute_baseurl:
        # change URL's baseurl to URL_POST
        original_baseurl = urllib.parse.urlparse(old_url).hostname
        new_baseurl = urllib.parse.urlparse(url).hostname
        html = html.replace(original_baseurl, new_baseurl)
    data = {'token': token,
            # XXX FIXME If date can be extracted from html this would be much better than setting it explicitly
            'date': get_last_fetch_time(human_readable=False),
            # XXX FIXME Should be renamed to data
            'html': html}
    res, _ = await utils.do_post_async(url=url, data=data, content_type=content_type)
    return res


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


async def fetch_city_details(session, url, tag='div', cls='terminy'):
    html, err = await fetch(url=url)
    if err:
        logger.error('Could not fetch details', err)
    if html:
        return a2exams_checker._html_to_exam_slots(html, tag=tag, cls=cls)
    return {}


async def run_once(retry_interval=POLLING_INTERVAL, attempts=1, cookie=COOKIE, curl=CURL):
    """
    Returns new_data if some has been fetched successfully or None if fetch failed after K attepmts.
    """
    # if curl parameter is set use plain GET, otherwise fetch with browser
    if not curl:
        new_data, err = await fetch(url=URL, retry_interval=retry_interval, filename=LAST_FETCHED,
                                    fetch_func=_do_fetch_with_browser, attempts=attempts, cookie=cookie)
    else:
        new_data, err = await fetch(url=URL, retry_interval=retry_interval, filename=LAST_FETCHED,
                                    fetch_func=utils.do_fetch_async, attempts=attempts, cookie=cookie)
    if new_data:
        # Validate data, make sure cities list is there
        schools_json = await a2exams_checker._html_to_schools(new_data)
        if not schools_json:
            logger.warning('Data validation failed: expired cookie?')
            await report_fetcher_status(status='cookie trouble')
        else:
            # XXX FIXME(ivasilev) Still to be done, let's test async http first
            if FETCH_DETAILED:
                # Perform additional requests to fetch details - number of slots, exam dates etc
                tasks = []
                for city_urls in [c for c in schools_json if schools_data[c]['free_slots']]:
                    tasks.append(asyncio.create_task(fetch_city_details(url, session)))
                results = await asyncio.gather(*tasks)
                # update with city details
                # TBD
            # push new data to the centralized portal
            await report_fetcher_status(status='ok')
            logger.info('[%s] New data has been successfully fetched', get_last_fetch_time(human_readable=True))
            res = await post(new_data, url=URL_POST, token=TOKEN_POST)
            res_json = await post(json.dumps(schools_json, indent=2), url=URL_POST_JSON,
                                  token=TOKEN_POST, substitute_baseurl=False,
                                  content_type='application/json')
            if not res:
                logger.warning('No data has been pushed!')
            return new_data
    if err:
        # An exception has been raised during fetch. If we are blocked -> let's wait out
        await report_fetcher_status(status='blocked')
        logger.error('Looks like we have been blocked. Let us lay low for a while: %s', err)
        await asyncio.sleep(LAY_LOW)
    else:
        logger.warning('No new data has been fetched! Will retry later')
        # update health check file
        if get_time_since_last_fetched() < HEALTH_THRESHOLD:
            logger.debug('State: healthy')
            _create_health_file(HEALTH)
        else:
            logger.warning('State: unhealthy, last fetch was > %s seconds ago', HEALTH_THRESHOLD)
            _remove_health_file(HEALTH)


async def fetch_data(interval=POLLING_INTERVAL, cookie=COOKIE, curl=CURL, attempts=1):
    """ The infinite loop of fetch -> push -> wait -> fetch -> push ... """
    fail_notification_sent = False
    backoff = 0
    try:
        while True:
            if BACKUP:
                # Backup fetchers should run only if all others have issues or are blocked
                status = await get_fetcher_status()
                if any(status[fetcher_id] not in ['down', 'blocked'] for fetcher_id in status if fetcher_id != FETCHER_ID):
                    logger.debug('Not running backup fetcher %s, others are still fine', FETCHER_ID)
                    await asyncio.sleep(POLLING_INTERVAL)
                    continue
            if backoff:
                logger.warning(f'Waiting {backoff} seconds before next attempt')
                await asyncio.sleep(backoff)
            fetch_result = await run_once(retry_interval=interval, cookie=cookie, curl=curl, attempts=attempts)
            if fetch_result:
                # fetch is successfull, fetcher is operational again and backoff can be reset
                backoff = 0
                fail_notification_sent = False
            else:
                if SEND_MAIL and not fail_notification_sent:
                    fail_notification_sent = utils.send_mail(EMAIL_ALERT)
                # increase backoff and to wait till retry next time
                backoff = backoff * 2 + DEFAULT_BACKOFF
                if backoff > CAP_BACKOFF:
                    backoff = CAP_BACKOFF
            # Wait a bit before the next check
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')
    finally:
        _close_browser()
        # clear healthcheck state if it's present from previous runs
        _remove_health_file(HEALTH)
        await report_fetcher_status(status='down')
        await utils.destroy_session()


if __name__ == "__main__":
    asyncio.run(fetch_data())
