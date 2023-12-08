import asyncio
import datetime
import json
import logging
import os
import sys

from bs4 import BeautifulSoup
import pytz
import unidecode

import utils


BASEURL = 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/'
# interval to wait before repeating the request
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '25'))
TZ = 'Europe/Prague'
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
URL_GET = os.getenv('URL_GET')
URL_GET_JSON = os.getenv('URL_GET_JSON')
TOKEN_GET = os.getenv('TOKEN_GET')
URL_LAST_FETCHED_TS = os.getenv('URL_GET_TS', 'https://ciziproblem.cz/trvaly-pobyt/a2/lastupdate')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')
LAST_FETCHED_JSON = os.path.join(OUTPUT_DIR, 'last_fetched.json')

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _extract_data(html, tag, cls, strings_only=True):
    soup = BeautifulSoup(html, features="lxml")
    all_tags = soup.find_all(tag, {'class': cls})
    return [t.text.split() if strings_only else t for t in all_tags]


def _reconstruct_city_name(city_strings, no_diacrytics=True):

    """ Returns a city name and positional number of first word after it
    """
    # Town may consist of several words - compensate for that
    not_a_name_num, _ = next(((i, w) for (i, w) in enumerate(city_strings) if w.startswith('(')), (0, None))
    city = ' '.join([s.title() for s in city_strings[0: not_a_name_num]])
    if no_diacrytics:
        city = unidecode.unidecode(city)
    return city, not_a_name_num


def _html_to_schools_urls(html, tag='li', cls='', baseurl=BASEURL):
    res = {}
    tags = _extract_data(html, tag, cls, strings_only=False)
    for tag in tags:
        city_strings = tag.find('div')
        if not city_strings:
            # This can happen if some non-town related fields have been matched
            continue
        city_strings = city_strings.text.split()
        city_name, _ = _reconstruct_city_name(city_strings)
        if not tag.find('a'):
            # invalid data, school block should have link to the schools
            continue
        url = tag.find('a').attrs.get('href')
        # This should filter out occasional non-city matches
        if not url or not city_name:
            continue
        res[city_name] = f'{baseurl}{url}'
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
            # the 5th element is either Obsazeno (no slots), 'Neni' (k dispozice) or number of free slots
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
            elif string == 'Není':
                num = 0
                skip = 2
            else:
                try:
                    num = int(string)
                except ValueError:
                    num = 0
                # the following 'volnych' 'mist' 'Vybrat' have to be skipped
                skip = 3
            # Save the data
            res['details'].append((date, num))
            # reset date and critical elem counter for next slot
            date = ''
            i = 0
    # Now calculate total
    res['total'] = sum(e[1] for e in res['details'])
    return res


async def _html_to_schools(html, tag='li', cls=''):
    """
    In case layout changes this function only has to be tuned to extract necessary data.
    Returned value is a dict with no-diacrytics-city-name used as keys
    """
    res = {}
    timestamp = datetime.datetime.now(tz=pytz.timezone(TZ)).timestamp()
    schools_data = _extract_data(html, tag, cls)
    timestamp = await get_last_fetch_time()
    urls_data = _html_to_schools_urls(html)
    # Sometimes the name of a town consists of several words, account for that
    for city_info in schools_data:
        city_name, not_a_name_num = _reconstruct_city_name(city_info, no_diacrytics=False)
        try:
            total_schools = int(city_info[not_a_name_num].lstrip('('))
        except:
            # Block with schools has ended, that is some irrelevant data already, skip the rest completely
            break
        status = city_info[-1].strip()
        free_slots = 'Vybrat' in status
        city_name_no_diacrytics = unidecode.unidecode(city_name)
        url = urls_data.get(city_name_no_diacrytics)
        if not url:
            logger.warn(f'No url has been found for {city_name} among {urls_data}')
        res[city_name_no_diacrytics] = {'free_slots': free_slots,
                                        # total slots might be updated later after school page is parsed
                                        'total_slots': 0,
                                        'total_schools': total_schools,
                                        'status': status,
                                        'city_name': city_name,
                                        'timestamp': timestamp,
                                        'url': url}
    return res


def get_schools_from_file(filename=LAST_FETCHED_JSON, tag='li', cls='', cities_filter=None):
    """
    Read last saved html and load exams registration data. No fetching here, just give what was saved last.
    """
    if not os.path.isfile(filename):
        return {}
    with open(filename) as f:
        try:
            res = json.loads(f.read())
        except json.decoder.JSONDecodeError:
            return {}
    if not cities_filter:
        return res
    return {k:v for (k, v) in res.items() if k in cities_filter}


def _dump_schools_to_file(filename, schools):
    # Save last fetched to filename_json
    if filename:
        with open(filename, 'w') as f:
            f.write(json.dumps(schools))


async def html_to_schools(html_file=LAST_FETCHED, filename_json=LAST_FETCHED_JSON, tag='li', cls=''):
    """
    Generate last_fetched.json from html data, save it locally and return exams registration data.
    """
    with open(html_file) as f:
        html = f.read()
    res = await _html_to_schools(html, tag=tag, cls=cls)
    _dump_schools_to_file(filename_json, res)
    return res


async def fetch_exam_slots(url, tag='div', cls='terminy'):
    # NOTE(ivasilev) This will need to be split between fetcher and checker.
    # Currently this functionality is not supported
    html = await fetch(url, retry_interval=5)
    return _html_to_exam_slots(html, tag=tag, cls=cls)


async def fetch_schools_with_exam_slots(html, filename=LAST_FETCHED, filename_json=LAST_FETCHED_JSON):
    # NOTE(ivasilev) This will need to be split between fetcher and checker.
    # Currently this functionality is not supported
    schools_data = await _html_to_schools(html)
    # now fetch additional information for schools with open registration and update schools data
    for city in [c for c in schools_data if schools_data[c]['free_slots']]:
        exam_slots = await fetch_exam_slots(schools_data[city]['url'])
        schools_data[city]['total_slots'] = exam_slots['total']
    _dump_schools_to_file(filename_json, schools_data)
    return schools_data


def diff_to_str(new_data, old_data=None, cities=None, url_in_header=False, city_href=False):
    """
    Return a human readable state of exams registration in chosen cities (no cities chosen means all cities).
    If previous state is passed then only changes to the state will be accounted for.

    Cities parameter should be actual keys in schools data - no diacrytics
    """
    cities = [c for c in cities if c in new_data] if cities else new_data.keys()
    msg = ''

    def _happy_message(city):
        city_name = new_data[city]['city_name']
        city_url = f"\U0001F4DD {new_data[city]['url']}" if city_href else ''
        exam_slots_msg = '' if not new_data[city]['total_slots'] else f' {new_data[city]["total_slots"]} slots'
        return f'{city_name} :){exam_slots_msg}\n{city_url}'

    def _sad_message(city):
        city_name = new_data[city]['city_name']
        return f'{city_name} :('

    for city in cities:
        date = utils.timestamp_to_str(new_data[city]['timestamp'])
        # Assume by default there will be nothing to show
        m = ''
        if not old_data:
            # Just show current state
            m = _sad_message(city) if not new_data[city]['free_slots'] else _happy_message(city)
        elif old_data:
            if city not in old_data and new_data[city]['free_slots']:
                # A new city has appeared overnight and there are free exam slots
                m = _happy_message(city)
            elif old_data[city]['free_slots'] != new_data[city]['free_slots']:
                m = _sad_message(city) if not new_data[city]['free_slots'] else _happy_message(city)
        if m:
            msg += f'{m}\n'
    if msg:
        # Add date from last city processed
        msg = f'Update from {date}:\n{msg}'
        # If requested - add url
        if url_in_header:
            msg = f'{BASEURL}\n{msg}'
    return msg


def has_changes(new_data, old_data, chosen_cities=None):
    """
    A (hopefully) useful method to quickly check if the state has changed.
    """
    chosen_cities = chosen_cities or []
    cities = [c for c in chosen_cities if c in new_data.keys()] or new_data.keys()
    # if new cities have appeared -> check if there are any free slots
    new_cities_appeared = set(cities) - set(old_data.keys())
    if any(new_data[c]['free_slots'] for c in new_cities_appeared):
        return True
    # Filter against new cities and check for changes the usual way
    cities_to_check = set(cities) & set(old_data.keys())
    return any(old_data[c]['free_slots'] != new_data[c]['free_slots'] for c in cities_to_check)


async def get_last_fetch_time(human_readable=False):
    """
    Return timestamp of the last modification to the last_fetched.html file or
    a human-readable date and time if requested.
    """
    if not URL_LAST_FETCHED_TS:
        # offline mode
        return utils.get_modification_time(LAST_FETCHED, human_readable)
    # Take real timestamp of data from centralized repo
    ts, _ = await utils.do_fetch(URL_LAST_FETCHED_TS)
    if not human_readable:
        return ts
    return utils.timestamp_to_str(ts)


def get_last_fetch_time_from_data(human_readable=False):
    """
    Return timestamp of the data from the latest json file or a human-readable date and time if requested.
    """
    new_data = get_schools_from_file()
    # take timestamp from the first city for now
    # XXX FIXME(ivasilev) One day there'll be a real date field
    random_city_data = new_data[list(new_data.keys())[0]] if new_data.keys() else {}
    ts = random_city_data.get('timestamp', '')
    if not human_readable:
        return ts
    return utils.timestamp_to_str(ts)


async def get_latest_data(filename=LAST_FETCHED, token=TOKEN_GET):
    """
    Obtain latest data with exam slots, save it as filename and return obtained data as text.
    What to fetch - html or json - will be determined by the name of the file where to save the results.

    2 different modes of operation are supported:
      - if token and get url are set, then the data is fetched over network from a centralized registry;
      - otherwise it expects new data to magically appear in the filename file and just displays its contents
    """
    html = None
    mode = 'json' if filename.endswith('.json') else 'html'
    url = URL_GET if mode == 'html' else URL_GET_JSON
    if not url or not token:
        logger.info("Working in offline mode, just displaying contents of the %s file", filename)
        if os.path.isfile(filename):
            with open(filename) as f:
                return f.read()
    # online mode, fetch data from centralized repo as defined by URL_GET
    logger.info("Working in online mode, fetching data from %s", url)
    url = f'{url}?token={token}'
    data, err = await utils.do_fetch(url)
    if data:
        with open(filename, 'w') as f:
            f.write(data)
    if not data:
        logger.warning("No data fetched!")
    return data


async def get_latest_data_as_json(filename, token=TOKEN_GET):
    """
    Basically a wrapper for get_latest_data function that will convert result to json even if source data is html.
    """
    mode = 'json' if filename.endswith('.json') else 'html'
    data = await get_latest_data(filename, token)
    if mode == 'html':
        # Perform conversion and return result. Html data doesn't have information about exam slots.
        return await html_to_schools(filename)
    if mode == 'json':
        # Make sure data is json and return it. In case any error happens return empty dict
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            logger.error('Non-json data was returned\n: %s', data)
            return {}

    new_data = await html_to_schools(last_fetched_file) if mode == 'html' else json.loads(updated_data)


async def check(cities_filter=None, interval=POLLING_INTERVAL, last_fetched_file=LAST_FETCHED):
    """The infinite loop of check html -> process it -> wait -> check html ..."""
    # fetch initial data to set everything up (default choices for cities etc)
    mode = 'json' if last_fetched_file.endswith('json') else 'html'
    logger.debug('Starting checker: %s mode', mode)
    while not os.path.isfile(last_fetched_file):
        await get_latest_data(last_fetched_file)
        # No file with data, let's wait a bit
        logging.debug("No file with data found, let's wait %s seconds", interval)
        await asyncio.sleep(interval)
    chosen_cities = [unidecode.unidecode(c.lower().capitalize()) for c in cities_filter or []]
    try:
        old_data = {}
        while True:
            await asyncio.sleep(interval)
            # See if data has been updated
            new_data = await get_latest_data_as_json(last_fetched_file)
            cities = new_data.keys() if not chosen_cities else chosen_cities
            curr_date = utils.timestamp_to_str(datetime.datetime.now().timestamp())
            # Here date will be taken from data to reflect real state of things
            date = get_last_fetch_time_from_data(human_readable=True)
            logger.info("[%s] Obtained data from %s, available slots in %s",
                        curr_date, date, [c for c in new_data if new_data[c]['free_slots']])
            if not old_data or has_changes(new_data, old_data, cities):
                logger.info(diff_to_str(new_data, old_data, cities))
                old_data = new_data
    except KeyboardInterrupt:
        sys.exit('Interrupted by user.')


if __name__ == "__main__":
    asyncio.run(check(last_fetched_file=LAST_FETCHED_JSON))
