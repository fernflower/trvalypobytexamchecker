import pytest

from checker import a2exams_checker


def test_parse_main_page(main_page_html):
    parsed_cities = a2exams_checker._html_to_list(main_page_html, tag='div', cls='town')
    # TBD


def test_parse_city_page(city_page_html):
    pass
