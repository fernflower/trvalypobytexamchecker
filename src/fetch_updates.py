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

POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))
COOKIE_NAME = os.getenv('COOKIE_NAME', 'PHPSESSID')
COOKIE = os.getenv('COOKIE')


def _parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', help='Interval to poll a website with exams registration',
                        default=POLLING_INTERVAL, type=int)
    parser.add_argument('--attempts', help='Number of subsequent retries of initial fetch before giving up',
                        default=1, type=int)
    parser.add_argument('--cookie', help='Cookie to use with request', default=COOKIE)
    return parser.parse_args(args)


if __name__ == "__main__":
    parsed_args = _parse_args(sys.argv[1:])
    asyncio.run(a2exams_fetcher.fetch_data(interval=parsed_args.interval,
                                           cookie=f'{COOKIE_NAME}={parsed_args.cookie}',
                                           attempts=parsed_args.attempts))
