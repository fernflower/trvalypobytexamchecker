import asyncio
import requests
import unittest
from unittest import mock

import pytest

from fetcher import a2exams_fetcher
import utils

URL = 'https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/'
URL_POST = 'https://ciziproblem.cz/trvaly-pobyt/a2/online-prihlaska'


@pytest.mark.asyncio
@mock.patch('requests.get', new_callable=unittest.mock.Mock)
async def test_exception_during_fetch(requests_get_mock):
    # Emulate situation when an exception occurs somewhere in requests (Issue #22)
    for exc in [requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                Exception('Something has gone seveeeeeerely wrong')]:
        requests_get_mock.side_effect = Exception('Something has gone seveeeeerely wrong')
        r = await a2exams_fetcher._do_fetch_with_browser('No such url')
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


@mock.patch('fetcher.a2exams_fetcher._create_health_file')
@mock.patch('fetcher.a2exams_fetcher._remove_health_file')
@pytest.mark.asyncio
async def test_healthy_state(mock_remove_file, mock_create_file, monkeypatch):
    # Make sure healthy file is created\deleted as needed
    # Fetching failed -> health status removed
    fetch_res = asyncio.Future()
    fetch_res.set_result(None)
    monkeypatch.setattr('fetcher.a2exams_fetcher.get_time_since_last_fetched', lambda: 100500)
    monkeypatch.setattr('fetcher.a2exams_fetcher.fetch', lambda url, filename, retry_interval, fetch_func: fetch_res)
    await a2exams_fetcher.run_once()
    assert mock_remove_file.called
    # Fetching ok -> health status set
    fetch_res = asyncio.Future()
    fetch_res.set_result('some data here')
    monkeypatch.setattr('fetcher.a2exams_fetcher.get_time_since_last_fetched', lambda: 42)
    monkeypatch.setattr('fetcher.a2exams_fetcher.fetch', lambda url, filename, retry_interval, fetch_func: fetch_res)
    await a2exams_fetcher.run_once()
    assert mock_create_file.called


@mock.patch('os.path.getmtime', return_value='1614382748.545964')
def test_get_last_fetch_time(mock_getmtime):
    assert a2exams_fetcher.get_last_fetch_time() == '1614382748.545964'
    assert a2exams_fetcher.get_last_fetch_time(human_readable=True) == '27/02/2021 00:39:08'
