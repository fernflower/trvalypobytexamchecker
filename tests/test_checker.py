import copy
import tempfile

import pytest

from checker import a2exams_checker

LAST_FETCHED_STATUS = \
"""Brno :(
Břeclav :(
České Budějovice :(
Frýdek-Místek :(
Hodonín :(
Hradec Králové :(
Jindřichův Hradec :(
Karlovy Vary :(
Klatovy :(
Kolín :(
Liberec :(
Mariánské Lázně :(
Olomouc :(
Ostrava :(
Písek :(
Plzeň :(
Praha :(
Přerov :(
Tábor :(
Ústí nad Labem :(
Volyně :(
Zlín :("""
LAST_FETCHED = 'tests/data/last_fetched.html'
CITIES = ['Brno', 'Breclav', 'Ceske Budejovice', 'Frydek-Mistek', 'Hodonin', 'Hradec Kralove', 'Jindrichuv Hradec',
          'Karlovy Vary', 'Klatovy', 'Kolin', 'Liberec', 'Marianske Lazne', 'Olomouc', 'Ostrava', 'Pisek', 'Plzen',
          'Praha', 'Prerov', 'Tabor', 'Usti nad Labem', 'Volyne', 'Zlin']


def test_parse_main_page(main_page_html):
    parsed_cities = a2exams_checker._html_to_schools(main_page_html)
    assert set(CITIES) == parsed_cities.keys()
    # Emulate the situation when something goes wrong and empty\different webpage is returned
    parsed_cities = a2exams_checker._html_to_schools('')
    assert parsed_cities == {}
    parsed_cities = a2exams_checker._html_to_schools('<head><body>Oops</body></head>')
    assert parsed_cities == {}


def test_parse_city_page(city_page_html):
    parsed = a2exams_checker._html_to_exam_slots(city_page_html)
    assert parsed['total'] == 7
    assert parsed['details'] == [
            ('26.02.2022, od 09:00', 0), ('09.03.2022, od 09:00', 2), ('26.03.2022, od 09:00', 5),
            ('06.04.2022, od 09:00', 0), ('23.04.2022, od 09:00', 0), ('11.05.2022, od 09:00', 0),
            ('08.06.2022, od 09:00', 0), ('25.06.2022, od 09:00', 0)]


def test_get_schools():
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    assert schools_data.keys() == set(CITIES)
    # check that filtering works
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED, cities_filter=['Praha'])
    assert len(schools_data) == 1
    assert 'Praha' in schools_data
    # try passing bad city in cities_filter
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED, cities_filter=['Brno', 'nosuchcity'])
    assert len(schools_data) == 1
    assert 'Brno' in schools_data


def _assert_matches(actual, expected):
    # NOTE(ivasilev) Checking match in this weird way as Update always put timestamp from current run
    actual_to_compare = '\n'.join([s for s in actual.split('\n')[1:] if s.strip()])
    assert expected == actual_to_compare


def test_diff_to_str_no_prev_state():
    # Test scenario 1 - no old_data passed. This should just print current status, nothing to compare to.
    new_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    msg = a2exams_checker.diff_to_str(new_data)
    _assert_matches(msg, LAST_FETCHED_STATUS)
    # Check that passing empty old_data doesn't break anything
    msg = a2exams_checker.diff_to_str(new_data, old_data={})
    _assert_matches(msg, LAST_FETCHED_STATUS)
    # And with filtering
    msg = a2exams_checker.diff_to_str(new_data, cities=['Brno', 'Praha', 'Tabor', 'nosuchcity'])
    expected = 'Brno :(\nPraha :(\nTábor :('
    _assert_matches(msg, expected)
    # Make sure URL is shown when requested
    msg = a2exams_checker.diff_to_str(new_data, url_in_header=True)
    assert msg.startswith(a2exams_checker.URL)


def test_diff_to_str_prev_state():
    # Test scenario 2 - old_data is passed. This should print a diff.
    old_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    new_data = copy.deepcopy(old_data)
    # Check that no changes results in empty message
    msg = a2exams_checker.diff_to_str(new_data, new_data)
    _assert_matches(msg, '')
    # Now make some exam slots appear
    for update_city in ['Praha', 'Plzen', 'Tabor']:
        new_data[update_city]['free_slots'] = True
    assert old_data != new_data
    msg = a2exams_checker.diff_to_str(new_data, old_data)
    expected_msg = 'Plzeň :)\nPraha :)\nTábor :)'
    _assert_matches(msg, expected_msg)
    # Check that filtering works
    msg = a2exams_checker.diff_to_str(new_data, old_data, cities=['Tabor', '42'])
    expected_msg = 'Tábor :)'
    _assert_matches(msg, expected_msg)
    # Emulate exam slots disappearance
    old_data = copy.deepcopy(new_data)
    for update_city in ['Praha', 'Plzen']:
        new_data[update_city]['free_slots'] = False
    msg = a2exams_checker.diff_to_str(new_data, old_data)
    expected_msg = 'Plzeň :(\nPraha :('
    _assert_matches(msg, expected_msg)
    # Now with filtering
    msg = a2exams_checker.diff_to_str(new_data, old_data, cities=['Tabor', 'Praha'])
    expected_msg = 'Praha :('
    _assert_matches(msg, expected_msg)


def test_diff_to_str_bad_fetch():
    # Cornercase (also investigation of Issue #4) - bad html returned
    old_data = a2exams_checker.get_schools_from_file(LAST_FETCHED)
    bad_fetched = tempfile.NamedTemporaryFile()
    new_data = a2exams_checker.get_schools_from_file(bad_fetched.name)
    msg = a2exams_checker.diff_to_str(new_data, old_data, cities=['Tabor', 'Praha'])
    assert msg == ''
