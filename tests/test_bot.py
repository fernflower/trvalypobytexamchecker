from bot import a2exams_bot
from checker import a2exams_checker

import mock


LAST_FETCHED = 'tests/data/last_fetched.html'


def test__parse_cities_args():
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    # The multi-whitespaces case
    context_args = ['plzEn', ',', 'praha', ',', 'ceske', 'budejovice']
    res, errors = a2exams_bot._parse_cities_args(context_args)
    assert (res, errors) == (['Ceske Budejovice', 'Plzen', 'Praha'], [])
    # Make sure that an empty list results in no errors
    context_args = []
    res, errors = a2exams_bot._parse_cities_args(context_args)
    assert (res, errors) == ([], [])


def test_vet_cities_args():
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    # Request cities with diacrytics should work just like without one
    requested_cities = ['Praha', 'Kolin', 'Plzeň']
    res, errors = a2exams_bot._vet_requested_cities(requested_cities, source_of_truth=schools_data)
    # Output is expected to be stripped-off diacrytics and sorted
    assert (res, errors) == (['Kolin', 'Plzen', 'Praha'], [])
    # CAPS and small letters are fine as well
    requested_cities = ['pRAHA', 'KoLiN', 'plzeň']
    res, errors = a2exams_bot._vet_requested_cities(requested_cities)
    assert (res, errors) == (['Kolin', 'Plzen', 'Praha'], [])
    # Bad cities end up in list of errors
    requested_cities = ['pRAHA', 'nosuchcity', 'cityof42']
    res, errors = a2exams_bot._vet_requested_cities(requested_cities)
    assert (res, errors) == (['Praha'], ['Cityof42', 'Nosuchcity'])
    # If a properly parsed list of cities is passed then 2 words in name are fine
    requested_cities = ['pRAHA', 'Ceske budejovice']
    res, errors = a2exams_bot._vet_requested_cities(requested_cities)
    assert (res, errors) == (['Ceske Budejovice', 'Praha'], [])


def _mock_redis(values=None):
    class RedisMock:
        def __init__(self, values=None):
            self.values = values or {}

        def get(self, chat_id):
            val = self.values.get(chat_id)
            if val is None:
                return
            # REDIS get returns a byte string
            return val.encode('utf-8')

        def exists(self, chat_id):
            return chat_id in self.values

    return RedisMock(values)


def test_get_cities():
    with mock.patch('bot.a2exams_bot.REDIS', new=_mock_redis({'1': 'Praha', '2': 'Brno', '3': ''})):
        # key exists
        assert a2exams_bot._get_tracked_cities_str('2') == 'Brno'
        assert a2exams_bot._get_tracked_cities('2') == ['Brno']
        # key exists, all cities are tracked
        assert a2exams_bot._get_tracked_cities_str('3') == 'all cities'
        assert a2exams_bot._get_tracked_cities('3') == []
        # no such key
        assert a2exams_bot._get_tracked_cities_str('42') == ''
        assert a2exams_bot._get_tracked_cities('42') == []


def test__fetch_from_db():
    with mock.patch('bot.a2exams_bot.REDIS', new=_mock_redis({'1': 'Praha', '2': 'Brno,Kolin', '3': ''})) as m:
        assert a2exams_bot._fetch_from_db('1', as_list=True) == ['Praha']
        assert a2exams_bot._fetch_from_db('1', as_list=False) == 'Praha'
        assert a2exams_bot._fetch_from_db('2', as_list=True) == ['Brno', 'Kolin']
        assert a2exams_bot._fetch_from_db('2', as_list=False) == 'Brno,Kolin'
        assert a2exams_bot._fetch_from_db('3', as_list=True) == []
        assert a2exams_bot._fetch_from_db('3', as_list=False) == ''
        assert a2exams_bot._fetch_from_db('nosuchid', as_list=True) == []
        assert a2exams_bot._fetch_from_db('nosuchid', as_list=False) is None
