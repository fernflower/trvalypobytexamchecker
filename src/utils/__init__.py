import datetime
import logging
import os
import random
import requests
import smtplib

import fake_useragent

DATETIME_FORMAT = '%d/%m/%Y %H:%M:%S'
UA = fake_useragent.UserAgent(browsers=['firefox'])

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SMTP = None


def _get_smtp():
    EMAIL_USER = os.environ.get('EMAIL_USER')
    EMAIL_PASS = os.environ.get('EMAIL_PASS')
    MAILHUB = os.environ.get('MAILHUB')
    MAIL_PORT = int(os.environ.get('MAIL_PORT'))

    global SMTP
    if SMTP:
        return SMTP
    try:
        SMTP = smtplib.SMTP(MAILHUB, MAIL_PORT)
        SMTP.starttls()
        SMTP.login(EMAIL_USER, EMAIL_PASS)
        return SMTP
    except smtplib.SMTPAuthenticationError:
        logger.warning('Failed to authenticate to mail server')
    except smtplib.SMTPException as exc:
        logger.warning('Failed to setup smtp connection %s', exc)


def _reset_smtp():
    global SMTP
    SMTP = None


def send_mail(subject, text=''):
    EMAIL_USER = os.environ.get('EMAIL_USER')
    TO_ADDR = os.environ.get('TO_ADDR')

    smtp = _get_smtp()
    if not smtp:
        logger.error("Could not send email")
    body = f"Subject: {subject}\n{text}"
    try:
        smtp.sendmail(EMAIL_USER, TO_ADDR, body)
    except smtplib.SMTPException as exc:
        logger.warning('Failed to send mail %s', exc)
        _reset_smtp()
        return False
    return True


def get_useragent(ua=UA):
    # NOTE(ivasilev) Setting useragent with ua.random is a great idea in theory but in practice it leads to
    # recaptcha warnings as recaptcha needs latest version of browsers to run. So let's hardcode it here to
    # something 100% acceptable and configure fake-useragent with custom data file later
    # useragent = ua.random
    try:
        useragents_firefox = set([UA.getFirefox['useragent']] * 3)
        useragents_safari = set([UA.getSafari['useragent']] * 3)
        useragents = list(useragents_firefox | useragents_safari)
    except fake_useragent.errors.FakeUserAgentError:
        useragents = [
                'Mozilla/5.0 (iPad; CPU iPad OS 10_3_4 like Mac OS X) AppleWebKit/536.1 (KHTML, like Gecko) CriOS/26.0.877.0 Mobile/13Z933 Safari/536.1',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.2; rv:111.0) Gecko/20100101 Firefox/111.0',
                'Mozilla/5.0 (X11; Linux x86_64; rv:107.0) Gecko/20100101 Firefox/107.0',
        ]
    useragent = useragents[random.randint(0, len(useragents) - 1)]
    return useragent


async def do_fetch(url, proxy=None, cookie=None):
    try:
        proxies = {} if not proxy or proxy in ('0', 'None', 'no', None) else {'https': f'socks5h://{proxy}'}
        if proxies:
            logger.info("Using proxy %s for request", proxy)
        headers = {'Cache-Control': 'no-cache',
                   'Pragma': 'no-cache', 'User-agent': get_useragent()}
        if cookie:
            headers['Cookie'] = cookie
        resp = requests.get(url, proxies=proxies, headers=headers)
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
        return None, exc
    except Exception as exc:
        logger.error('Some unexpected exception has occured %s..', exc)
        return None, exc
    if resp.ok:
        return resp.text, None
    return None, None


async def do_post(url, data, proxy=None, cookie=None):
    try:
        proxies = {} if not proxy or proxy in ('0', 'None', 'no', None) else {'https': f'socks5h://{proxy}'}
        if proxies:
            logger.info("Using proxy %s for request", proxy)
        headers = {'Cache-Control': 'no-cache',
                   'Pragma': 'no-cache',
                   'User-agent': get_useragent(),
                   'Content-Type': 'application/octet-stream'}
        if cookie:
            headers['Cookie'] = cookie
        resp = requests.post(url, data=data, headers=headers)
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
        return None, exc
    except Exception as exc:
        logger.error('Some unexpected exception has occurred during post: %s', exc)
        return None, exc
    if resp.ok:
        return resp.text, None
    logger.error('Post was unsuccessful')
    return None, None


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
