"""The retry loop: a spent usage window waits, a plain 429 backs off, a 4xx fails fast."""

import http.client
import io
import unittest
import urllib.error
from unittest import mock

from fincon_runner import endpoints


def _http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


class RetryTest(unittest.TestCase):
    def test_a_usage_limit_429_waits_long_and_then_succeeds(self):
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _http_error(429, '{"error":"you have reached your session usage limit"}')
            return {"ok": True}

        with mock.patch.object(endpoints.time, "sleep") as sleep, \
                mock.patch.object(endpoints, "USAGE_LIMIT_WAIT", 300):
            self.assertEqual(endpoints._with_retries(call, attempts=2), {"ok": True})
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(w >= 300 for w in waits))

    def test_a_usage_limit_that_never_clears_is_an_error(self):
        def call():
            raise _http_error(429, '{"error":"usage limit"}')

        with mock.patch.object(endpoints.time, "sleep"), \
                mock.patch.object(endpoints, "USAGE_LIMIT_ATTEMPTS", 3), \
                mock.patch.object(endpoints, "USAGE_LIMIT_WAIT", 300):
            with self.assertRaises(endpoints.EndpointError):
                endpoints._with_retries(call, attempts=2)

    def test_a_plain_429_uses_the_short_backoff(self):
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429, "Too many requests")
            return {"ok": True}

        with mock.patch.object(endpoints.time, "sleep") as sleep:
            endpoints._with_retries(call, attempts=3, base=2.0)
        self.assertEqual(len(sleep.call_args_list), 1)
        self.assertLess(sleep.call_args_list[0].args[0], 10)

    def test_a_404_fails_without_retrying(self):
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            raise _http_error(404, "not found")

        with mock.patch.object(endpoints.time, "sleep"):
            with self.assertRaises(endpoints.EndpointError):
                endpoints._with_retries(call, attempts=5)
        self.assertEqual(calls["n"], 1)


class TruncatedBodyTest(unittest.TestCase):
    def test_a_truncated_response_body_is_retried_not_raised(self):
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.client.IncompleteRead(b"partial")
            if calls["n"] == 2:
                raise ConnectionResetError("reset by peer")
            return {"ok": True}

        with mock.patch.object(endpoints.time, "sleep"):
            self.assertEqual(endpoints._with_retries(call, attempts=4), {"ok": True})
        self.assertEqual(calls["n"], 3)
