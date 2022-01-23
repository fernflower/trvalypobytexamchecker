import argparse
import asyncio
import csv
import datetime
import os
import pytz
import random
import sys

from bs4 import BeautifulSoup
import requests
import unidecode


URL = 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/'
# interval to wait before repeating the request
POLLING_INTERVAL = 15
TZ = 'Europe/Prague'
OUTPUT_DIR = 'output'
CSV_FILENAME = os.path.join(OUTPUT_DIR, 'out.csv')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')


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
    html = await fetch(url, filename=filename)
    return _html_to_list(html, tag=tag, cls=cls)


def diff_to_str(new_data, old_data=None, cities=None):
    """
    Return a human readable state of exams registration in chosen cities (no cities chosen means all cities).
    If previous state is passed then only changes to the state will be accounted for.
    """
    cities = cities or new_data.keys()
    msg = ''
    for city in cities:
        no_diacrytics_city = unidecode.unidecode(city)
        city_czech_name = new_data[no_diacrytics_city]['city_name']
        date = datetime.datetime.fromtimestamp(
            new_data[no_diacrytics_city]['timestamp']).strftime('%d/%m/%Y %H:%M:%S')
        if not old_data:
            # Just show current state
            m = (f'{city_czech_name} :(' if not new_data[no_diacrytics_city]['free_slots'] else
                 f'{city_czech_name} :)')
        elif old_data and old_data[no_diacrytics_city]['free_slots'] != new_data[no_diacrytics_city]['free_slots']:
            m = (f'{city_czech_name} :('
                 if not new_data[no_diacrytics_city]['free_slots'] else
                 f'{city_czech_name} :)')
        else:
            # No change
            m = ''
        if m:
            msg += f'{m}\n'
    if msg:
        # Add date from last city processed
        msg = f'Update from {date}:\n{msg}'
    return msg


def write_csv(schools, tracked_cities, filename=CSV_FILENAME):
    """
    Dump exams registration information into csv.
    """
    with open(filename, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'free_slots', 'city']
        writer = csv.DictWriter(csvfile, fieldnames)
        for city in tracked_cities:
            no_diacrytics_city = unidecode.unidecode(city)
            writer.writerow({'timestamp': schools[no_diacrytics_city]['timestamp'],
                             'free_slots': schools[no_diacrytics_city]['free_slots'],
                             'city': schools[no_diacrytics_city]['city_name']})


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
    cities = parsed_args.city or all_cities
    try:
        old_data = {}
        while True:
            await asyncio.sleep(parsed_args.interval)
            new_data = await fetch_schools(url=URL)
            print(f"Fetched data, available slots in {[c for c in new_data if new_data[c]['free_slots']]}")
            if not old_data or any(old_data[c]['free_slots'] != new_data[c]['free_slots'] for c in cities):
                print(diff_to_str(new_data, old_data, cities))
                # update data
                write_csv(new_data, cities, filename=CSV_FILENAME)
                old_data = new_data
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')


if __name__ == "__main__":
    asyncio.run(main())
