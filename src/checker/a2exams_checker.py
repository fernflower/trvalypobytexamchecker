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


def _extract_data(html, tag, cls, strings_only=True):
    soup = BeautifulSoup(html, features="lxml")
    return [e.text.split() if strings_only else e for e in soup.find_all(tag)
            if getattr(e, tag) and cls in getattr(e, tag)["class"]]


def _reconstruct_city_name(city_strings, no_diacrytics=True):
    """ Returns a city name and positional number of first word after it
    """
    # Town may consist of several words - compensate for that
    not_a_name_num, _ = next(((i, w) for (i, w) in enumerate(city_strings) if w.startswith('(')), (0, None))
    city = ' '.join(city_strings[0: not_a_name_num])
    if no_diacrytics:
        city = unidecode.unidecode(city)
    return city, not_a_name_num


def _html_to_schools_urls(html, tag='div', cls='col-6'):
    res = {}
    tags = _extract_data(html, tag, cls, strings_only=False)
    for tag in tags:
        city_strings = tag.find('div').text.split()
        if not city_strings:
            continue
        city_name, _ = _reconstruct_city_name(city_strings)
        url = tag.find('a').attrs.get('href')
        # This should filter out occasional non-city matches
        if not url or not city_name:
            continue
        res[city_name] = f'{URL}{url}'
    return res


def _html_to_exam_slots(html, tag='div', cls='terminy'):
    res = {'total': 0, 'details': []}
    exams_data_per_school = _extract_data(html, tag, cls)
    for exams_data in exams_data_per_school:
        # Now turn a list of strings into a meaningful dictionary
        date = ''
        skip = 0
        i = 0
        for string in exams_data:
            # the 5th element is either Obsazeno (no slots) or number of free slots
            if skip > 0:
                skip -= 1
                continue
            i += 1
            if i % 6:
                date += f'{"" if string.endswith(".") or string.endswith(",") else " "}{string}'
                continue
            # the critical element
            if string == 'Obsazeno':
                num = 0
            else:
                try:
                    num = int(string)
                except ValueError:
                    num = 0
                # the following 'volnych' 'mist' have to be skipped
                skip = 2
            # Save the data
            res['details'].append((date, num))
            # reset date and critical elem counter for next slot
            date = ''
            i = 0
    # Now calculate total
    res['total'] = sum(e[1] for e in res['details'])
    return res


def _html_to_schools(html, tag='div', cls='town'):
    """
    In case layout changes this function only has to be tuned to extract necessary data.
    Returned value is a dict with no-diacrytics-city-name used as keys
    """
    res = {}
    timestamp = datetime.datetime.now(tz=pytz.timezone(TZ)).timestamp()
    schools_data = _extract_data(html, tag, cls)
    # Sometimes the name of a town consists of several words, account for that
    for city_info in schools_data:
        city_name, not_a_name_num = _reconstruct_city_name(city_info, no_diacrytics=False)
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
    res = _html_to_schools(html, tag, cls)
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
    return _html_to_schools(html, tag=tag, cls=cls)


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
