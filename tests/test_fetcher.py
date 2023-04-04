import requests
import unittest
from unittest import mock

import pytest

from fetcher import a2exams_fetcher


@pytest.mark.asyncio
@mock.patch('requests.get', new_callable=unittest.mock.Mock)
async def test_exception_during_fetch(requests_get_mock):
    # Emulate situation when an exception occurs somewhere in requests (Issue #22)
    for exc in [requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                Exception('Something has gone seveeeeeerely wrong')]:
        requests_get_mock.side_effect = Exception('Something has gone seveeeeerely wrong')
        r = await a2exams_fetcher._do_fetch('No such url')
        assert not r
