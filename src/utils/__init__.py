import datetime
import random
import requests

DATETIME_FORMAT = '%d/%m/%Y %H:%M:%S'


def get_useragent():
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


async def do_fetch(url, logger, proxy=None):
    try:
        proxies = {} if proxy in ('0', 'None', 'no', None) else {'https': f'socks5h://{proxy}'}
        if proxies:
            logger.info("Using proxy %s for request", proxy)
        resp = requests.get(url, proxies=proxies, headers={'Cache-Control': 'no-cache',
                                                           'Pragma': 'no-cache',
                                                           'User-agent': get_useragent()})
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
