import argparse
import asyncio
import csv
import datetime
import logging
import os
import pytz
import random
import sys
import time

from bs4 import BeautifulSoup
import requests
import unidecode


URL = 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/'
# interval to wait before repeating the request
POLLING_INTERVAL = os.getenv('POLLING_INTERVAL', 15)
TZ = 'Europe/Prague'
OUTPUT_DIR = 'output'
CSV_FILENAME = os.path.join(OUTPUT_DIR, 'out.csv')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')
DATETIME_FORMAT = '%d/%m/%Y %H:%M:%S'

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def _do_fetch(url):
    try:
        resp = requests.get(url, headers={'Cache-Control': 'no-cache',
                                          'Pragma': 'no-cache',
                                          'User-agent': 'Mozilla/5.0'})
    except requests.exceptions.ConnectionError:
        return
    if resp.ok:
        return resp.text


def _html_to_list(html, tag, cls):
    """
    In case layout changes this function only has to be tuned to extract necessary data.
    Returned value is a dict with no-diacrytics-city-name used as keys
    """
    res = {}
    timestamp = datetime.datetime.now(tz=pytz.timezone(TZ)).timestamp()
    soup = BeautifulSoup(html, features="lxml")
    schools_data = [e.text.split() for e in soup.find_all(tag) if getattr(e, tag) and cls in getattr(e, tag)["class"]]
    # Sometimes the name of a town consists of several words, account for that
    for city_info in schools_data:
        not_a_name_num, _ = next(((i, w) for (i, w) in enumerate(city_info) if w.startswith('(')), None)
        city_name = ' '.join(city_info[0: not_a_name_num])
        total_schools = int(city_info[not_a_name_num].lstrip('('))
        free_slots = city_info[-1] == 'Vybrat'
        status = city_info[-1]
        city_name_no_diacrytics = unidecode.unidecode(city_name)
        res[city_name_no_diacrytics] = {'free_slots': free_slots,
                                        'total_schools': total_schools,
                                        'status': status,
                                        'city_name': city_name,
                                        'timestamp': timestamp}
    return res


def _parse_args(args, cities_choices):
    parser = argparse.ArgumentParser()
    parser.add_argument('--city', help='City to track exams in', choices=cities_choices, action='append')
    parser.add_argument('--interval', help='Interval to poll a website with exams registration',
                        default=POLLING_INTERVAL)
    return parser.parse_args(args)


async def fetch(url, filename=None):
    """
    Fetches recent version of registration website. If request fails for some reason will retry until success.
    Return html and saves it in a file if filename parameter is passed.
    """
    res = await _do_fetch(url=url)
    while not res:
        print("Looks like connection error, will try again later")
        await asyncio.sleep(random.randint(1, POLLING_INTERVAL))
        res = await _do_fetch(url=url)
    # record new data
    if filename:
        with open(filename, 'w') as f:
            f.write(res)
    return res


def get_schools_from_file(filename=LAST_FETCHED, tag='div', cls='town', cities_filter=None):
    """
    Read last saved html and load exams registration data. No fetching here, just give what was saved last.
    """
    if not os.path.isfile(filename):
        return {}
    with open(filename) as f:
        html = f.read()
    res = _html_to_list(html, tag, cls)
    if not cities_filter:
        return res
    return {k:v for (k, v) in res.items() if k in cities_filter}


async def fetch_schools(url=URL, filename=LAST_FETCHED, tag='div', cls='town'):
    """
    Fetch recent data, update last saved html and return the exams registration data.
    """
    logger.debug(f'Trying to fetch {url}..')
    start = time.time()
    html = await fetch(url, filename=filename)
    end = time.time()
    logger.debug(f'Fetched successfully in {end - start} seconds.')
    return _html_to_list(html, tag=tag, cls=cls)


def timestamp_to_str(timestamp, dt_format=DATETIME_FORMAT):
    """Convert timestamp to a human-readable format"""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime(dt_format)
    except TypeError:
        return ''


def diff_to_str(new_data, old_data=None, cities=None, url_in_header=False):
    """
    Return a human readable state of exams registration in chosen cities (no cities chosen means all cities).
    If previous state is passed then only changes to the state will be accounted for.

    Cities parameter should be actual keys in schools data - no diacrytics
    """
    cities = [c for c in cities if c in new_data] if cities else new_data.keys()
    msg = ''
    for city in cities:
        city_czech_name = new_data[city]['city_name']
        date = timestamp_to_str(new_data[city]['timestamp'])
        if not old_data:
            # Just show current state
            m = (f'{city_czech_name} :(' if not new_data[city]['free_slots'] else
                 f'{city_czech_name} :)')
        elif old_data and old_data[city]['free_slots'] != new_data[city]['free_slots']:
            m = (f'{city_czech_name} :('
                 if not new_data[city]['free_slots'] else
                 f'{city_czech_name} :)')
        else:
            # No change
            m = ''
        if m:
            msg += f'{m}\n'
    if msg:
        # Add date from last city processed
        msg = f'Update from {date}:\n{msg}'
        # If requested - add url
        if url_in_header:
            msg = f'{URL}\n{msg}'
    return msg


def write_csv(schools, tracked_cities, filename=CSV_FILENAME):
    """
    Dump exams registration information into csv.
    """
    with open(filename, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'free_slots', 'city']
        writer = csv.DictWriter(csvfile, fieldnames)
        for city in tracked_cities:
            writer.writerow({'timestamp': schools[city]['timestamp'],
                             'free_slots': schools[city]['free_slots'],
                             'city': schools[city]['city_name']})


def has_changes(new_data, old_data, chosen_cities=None):
    """
    A (hopefully) useful method to quickly check if the state has changed.
    """
    cities = chosen_cities or new_data.keys()
    return any(old_data[c]['free_slots'] != new_data[c]['free_slots'] for c in cities)


async def main():
    # fetch initial data to set everything up (default choices for cities etc)
    schools = await fetch_schools(url=URL)
    all_cities = sorted(schools.keys())
    parsed_args = _parse_args(sys.argv[1:], cities_choices=all_cities)
    cities = [unidecode(c.lower().capitalize()) for c in parsed_args.city or []] or all_cities
    try:
        old_data = {}
        while True:
            await asyncio.sleep(parsed_args.interval)
            new_data = await fetch_schools(url=URL)
            date = timestamp_to_str(datetime.datetime.now().timestamp())
            logger.info(f"{date} Fetched data, available slots in {[c for c in new_data if new_data[c]['free_slots']]}")
            if not old_data or has_changes(new_data, old_data, cities):
                logger.info(diff_to_str(new_data, old_data, cities))
                # update data
                write_csv(new_data, cities, filename=CSV_FILENAME)
                old_data = new_data
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')


if __name__ == "__main__":
    asyncio.run(main())
