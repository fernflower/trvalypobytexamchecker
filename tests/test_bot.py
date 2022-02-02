from bot import a2exams_bot
from checker import a2exams_checker


LAST_FETCHED = 'tests/data/last_fetched.html'


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
