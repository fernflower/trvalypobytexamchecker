import requests
import unittest
from unittest import mock

import pytest

from fetcher import a2exams_fetcher

URL = 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/'
URL_POST = 'https://ciziproblem.cz/trvaly-pobyt/a2/online-prihlaska'


@pytest.mark.asyncio
@mock.patch('requests.get', new_callable=unittest.mock.Mock)
async def test_exception_during_fetch(requests_get_mock):
    # Emulate situation when an exception occurs somewhere in requests (Issue #22)
    for exc in [requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                Exception('Something has gone seveeeeeerely wrong')]:
        requests_get_mock.side_effect = Exception('Something has gone seveeeeerely wrong')
        r = await a2exams_fetcher._do_fetch('No such url')
        assert not r


@mock.patch('requests.post')
def test_post(mock_post, main_page_html):
    pushed_html = a2exams_fetcher.post(main_page_html, url=URL_POST, old_url=URL,
                                       token="myshinymetaltoken", substitute_baseurl=True)
    assert mock_post.called
    assert URL not in pushed_html
    # let's also check that if substitute_baseurl is not set the substitution doesn't happen
    pushed_html = a2exams_fetcher.post(main_page_html, url=URL_POST, old_url=URL,
                                       token="myshinymetaltoken", substitute_baseurl=False)
    assert mock_post.called
    assert URL in pushed_html
