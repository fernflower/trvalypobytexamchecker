"""
This module is intended to query whatever external resource used to store current schools information
and write it into a json file locally.
"""
import asyncio
import argparse
import os
import sys

from checker import a2exams_checker


OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')
LAST_FETCHED_JSON = os.path.join(OUTPUT_DIR, 'last_fetched.json')
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))


def _parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--city', help='City to track exams in', action='append')
    parser.add_argument('--interval', help='Interval to poll a website with exams registration',
                        default=POLLING_INTERVAL, type=int)
    return parser.parse_args(args)


if __name__ == "__main__":
    parsed_args = _parse_args(sys.argv[1:])
    asyncio.run(a2exams_checker.check_html(cities_filter=parsed_args.city, interval=POLLING_INTERVAL, 
                                           last_fetched_html_file=LAST_FETCHED))
