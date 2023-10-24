import datetime
import logging
import os
import random
import requests

import fake_useragent

DATETIME_FORMAT = '%d/%m/%Y %H:%M:%S'
UA = fake_useragent.UserAgent(browsers=['firefox'])
UA.update()

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_useragent(ua=UA):
    # NOTE(ivasilev) Setting useragent with ua.random is a great idea in theory but in practice it leads to
    # recaptcha warnings as recaptcha needs latest version of browsers to run. So let's hardcode it here to
    # something 100% acceptable and configure fake-useragent with custom data file later
    # useragent = ua.random
    useragents_firefox = UA.data_browsers['firefox'][0:5]
    useragents_safari_ipad = [ua for ua in UA.data_browsers['safari'] if 'iPad' in ua][0:5]
    useragents = useragents_firefox + useragents_safari_ipad
    # useragents = [
    #        'Mozilla/5.0 (iPad; CPU iPad OS 10_3_4 like Mac OS X) AppleWebKit/536.1 (KHTML, like Gecko) CriOS/26.0.877.0 Mobile/13Z933 Safari/536.1',
    #        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.2; rv:111.0) Gecko/20100101 Firefox/111.0',
    #        'Mozilla/5.0 (X11; Linux x86_64; rv:107.0) Gecko/20100101 Firefox/107.0',
    #        ]
    useragent = useragents[random.randint(0, len(useragents) - 1)]
    return useragent


async def do_fetch(url, proxy=None, cookie=None):
    try:
        proxies = {} if proxy in ('0', 'None', 'no', None) else {'https': f'socks5h://{proxy}'}
        if proxies:
            logger.info("Using proxy %s for request", proxy)
        headers = {'Cache-Control': 'no-cache',
                   'Pragma': 'no-cache', 'User-agent': get_useragent()}
        if cookie:
            headers['Cookie'] = cookie
        resp = requests.get(url, proxies=proxies, headers=headers)
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
        return
    except Exception as exc:
        logger.error('Some unexpected exception has occured %s..', exc)
        return
    if resp.ok:
        return resp.text


def timestamp_to_str(timestamp, dt_format=DATETIME_FORMAT):
    """Convert timestamp to a human-readable format"""
    try:
        int_timestamp = int(float(timestamp))
        return datetime.datetime.fromtimestamp(int_timestamp).strftime(dt_format)
    except (ValueError, TypeError):
        return ''


def get_modification_time(filename, human_readable=False):
    modified_ts = os.path.getmtime(filename)
    if not human_readable:
        return modified_ts
    return timestamp_to_str(modified_ts)
