import copy
import tempfile
import unittest
from unittest import mock

import asyncio
import pytest
import requests

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
Olomouc :(
Ostrava :(
Písek :(
Plzeň :(
Praha :(
Přerov :(
Tábor :(
Ústí Nad Labem :(
Volyně :(
Zlín :("""
LAST_FETCHED_JSON = 'tests/data/last_fetched.json'
CITIES = ['Brno', 'Breclav', 'Ceske Budejovice', 'Frydek-Mistek', 'Hodonin', 'Hradec Kralove', 'Jindrichuv Hradec',
          'Karlovy Vary', 'Klatovy', 'Kolin', 'Liberec', 'Olomouc', 'Ostrava', 'Pisek', 'Plzen',
          'Praha', 'Prerov', 'Tabor', 'Usti Nad Labem', 'Volyne', 'Zlin']


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
    assert parsed['total'] == 60
    assert parsed['details'] == [
            ('26.02.2022, od 09:00', 0), ('09.03.2022, od 09:00', 15),
            ('26.03.2022, od 09:00', 0), ('06.04.2022, od 09:00', 15), ('23.04.2022, od 09:00', 0),
            ('11.05.2022, od 09:00', 15), ('28.05.2022, od 09:00', 0), ('08.06.2022, od 09:00', 15)]


def test_get_urls(main_page_html):
    urls = a2exams_checker._html_to_schools_urls(main_page_html)
    assert urls.keys() == set(CITIES)
    assert urls['Praha'] == 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/?progress=2&town=3996'


def test_add_total_slots_column():
    old_data = "1643015225.059401,False,Břeclav\n1643015225.059401,False,Hodonín\n"
    new_data = "2022-01-24 10:07:05,False,Břeclav,0\n2022-01-24 10:07:05,False,Hodonín,0\n"

    old_out = tempfile.NamedTemporaryFile()
    with open(old_out.name, 'w') as f:
        f.write(old_data)
    a2exams_checker._apply_changes_to_csv(old_out.name)
    with open(old_out.name) as f:
        data = f.read()
        assert data == new_data


def test_get_schools():
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON)
    assert schools_data.keys() == set(CITIES)
    # check that filtering works
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON, cities_filter=['Praha'])
    assert len(schools_data) == 1
    assert 'Praha' in schools_data
    # try passing bad city in cities_filter
    schools_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON, cities_filter=['Brno', 'nosuchcity'])
    assert len(schools_data) == 1
    assert 'Brno' in schools_data


def _assert_matches(actual, expected):
    # NOTE(ivasilev) Checking match in this weird way as Update always put timestamp from current run
    actual_to_compare = '\n'.join([s for s in actual.split('\n')[1:] if s.strip()])
    assert expected == actual_to_compare


def test_diff_to_str_no_prev_state():
    # Test scenario 1 - no old_data passed. This should just print current status, nothing to compare to.
    new_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON)
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
    assert msg.startswith(a2exams_checker.BASEURL)
    # If schools has free slots and total_slots information is collected and > 0, then display it as well
    new_data_free_slots = copy.deepcopy(new_data)
    new_data_free_slots['Praha'].update({'free_slots': True, 'total_slots': 42})
    msg = a2exams_checker.diff_to_str(new_data_free_slots, cities=['Praha'])
    expected = 'Praha :) 42 slots'
    _assert_matches(msg, expected)
    # Make sure that no exception is raised when list of exam cities changes
    new_data_free_slots = copy.deepcopy(new_data)
    new_data_free_slots['A new city'] = {'free_slots': True,
                                         'total_slots': 4,
                                         'city_name': 'A new city',
                                         'timestamp': 42424242}
    new_data_free_slots['Praha'].update({'free_slots': True, 'total_slots': 42})
    msg = a2exams_checker.diff_to_str(new_data_free_slots, cities=['A new city', 'Praha'])
    expected = 'A new city :) 4 slots\nPraha :) 42 slots'
    _assert_matches(msg, expected)


def test_diff_to_str_prev_state():
    # Test scenario 2 - old_data is passed. This should print a diff.
    old_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON)
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
    # Make sure that no exception is raised when list of exam cities changes
    old_data = copy.deepcopy(new_data)
    new_data_free_slots = copy.deepcopy(new_data)
    new_data_free_slots['A new city'] = {'free_slots': True,
                                         'total_slots': 4,
                                         'city_name': 'A new city',
                                         'timestamp': 42424242}
    msg = a2exams_checker.diff_to_str(new_data_free_slots, old_data)
    expected = 'A new city :) 4 slots'
    _assert_matches(msg, expected)


def test_diff_to_str_bad_fetch():
    # Cornercase (also investigation of Issue #4) - bad html returned
    old_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON)
    bad_fetched = tempfile.NamedTemporaryFile()
    new_data = a2exams_checker.get_schools_from_file(bad_fetched.name)
    msg = a2exams_checker.diff_to_str(new_data, old_data, cities=['Tabor', 'Praha'])
    assert msg == ''


def test_has_changes():
    # test that new_data with newly added cities doesn't raise exception
    old_data = a2exams_checker.get_schools_from_file(LAST_FETCHED_JSON)
    new_data = dict(old_data)
    new_data.update({'A New City Not Present Before': {'free_slots': True}})
    assert a2exams_checker.has_changes(new_data, old_data)
    new_data.update({'A New City Not Present Before': {'free_slots': False}})
    assert not a2exams_checker.has_changes(new_data, old_data)
    # test that filtering against a non-existing-city-in-the-data doesn't raise an exception
    assert not a2exams_checker.has_changes(new_data, old_data, ['nosuchcity'])
    # test that new_data with a diminished cities list doesn't raise exception
    new_data.pop('Tabor')
    assert not a2exams_checker.has_changes(new_data, old_data)
