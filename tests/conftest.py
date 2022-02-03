import pytest

MAIN_PAGE = 'tests/data/last_fetched.html'
CITY_PAGE = 'tests/data/Online přihláška A2 – Jazyková zkouška A2.html'


@pytest.fixture()
def main_page_html():
    with open(MAIN_PAGE) as f:
        return f.read()


@pytest.fixture()
def city_page_html():
    with open(CITY_PAGE) as f:
        return f.read()
