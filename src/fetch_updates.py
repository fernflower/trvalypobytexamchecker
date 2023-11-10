import argparse
import datetime
import logging
import os
import sys

import asyncio

from checker import a2exams_checker
from fetcher import a2exams_fetcher
import utils

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

URL = os.getenv('URL', 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/')
# interval to wait before repeating the request
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))
# Initial time to wait if the fetch didn't get through
DEFAULT_BACKOFF = int(os.getenv('DEFAULT_BACKOFF', '120'))
CAP_BACKOFF = int(os.getenv('CAP_BACKOFF', '3600'))
EMAIL_ALERT = os.getenv('EMAIL_ALERT', 'cookie refresh')
SEND_MAIL = os.getenv('SEND_MAIL', '0').lower() in ['t', 'true', '1']
COOKIE = os.getenv('COOKIE')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')


def _parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', help='Interval to poll a website with exams registration',
                        default=POLLING_INTERVAL, type=int)
    parser.add_argument('--attempts', help='Number of subsequent retries of initial fetch before giving up',
                        default=1, type=int)
    parser.add_argument('--cookie', help='Cookie to use with request', default=COOKIE)
    parser.add_argument('--save-fetched-file', help='Path to file with saved results', default=LAST_FETCHED)
    return parser.parse_args(args)


async def main():
    """ The infinite loop of fetch -> check -> push -> wait -> fetch -> check -> push ... """
    new_data = None
    fail_notification_sent = False
    backoff = 0
    parsed_args = _parse_args(sys.argv[1:])

    try:
        while True:
            if backoff:
                logger.warning(f'Waiting {backoff} seconds before next attempt')
                await asyncio.sleep(backoff)
            fetch_result = await a2exams_fetcher.fetch(url=URL, retry_interval=parsed_args.interval,
                                                       filename=parsed_args.save_fetched_file,
                                                       fetch_func=utils.do_fetch, attempts=parsed_args.attempts,
                                                       cookie=parsed_args.cookie)
            if fetch_result:
                # fetch is successfull, fetcher is operational again and backoff can be reset
                backoff = 0
                fail_notification_sent = False
                # parse received data
                new_data = await a2exams_checker._html_to_schools(fetch_result)
                if new_data:
                    curr_date = utils.timestamp_to_str(datetime.datetime.now().timestamp())
                    logger.info("[%s] Obtained data, available slots in %s", curr_date,
                                [c for c in new_data if new_data[c]['free_slots']])
            # Parsing has failed. Probably no real data has been fetched because of a bad cookie
            if not new_data:
                logger.warning("Fetching data failed, bad cookie?")
                # Notify about failure
                if SEND_MAIL and not fail_notification_sent:
                    fail_notification_sent = utils.send_mail(EMAIL_ALERT)
                # increase backoff and to wait till retry next time
                backoff = backoff * 2 + DEFAULT_BACKOFF
                if backoff > CAP_BACKOFF:
                    backoff = CAP_BACKOFF
            # Be responsible and wait a bit before the next check
            logger.debug("Waiting %s seconds before next fetch", parsed_args.interval)
            await asyncio.sleep(parsed_args.interval)
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')
        _close_browser()


if __name__ == "__main__":
    asyncio.run(main())
