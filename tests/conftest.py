import pytest

MAIN_PAGE = 'tests/data/last_fetched.html'
CITY_PAGE = 'kolin.html'


@pytest.fixture()
def main_page_html():
    with open(MAIN_PAGE) as f:
        return f.read()


@pytest.fixture()
def city_page_html():
    with open(CITY_PAGE) as f:
        return f.read()
