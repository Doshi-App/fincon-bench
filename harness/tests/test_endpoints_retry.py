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

    def test_a_plain_429_backs_off_and_outlasts_the_general_budget(self):
        # Eight throttles in a row, more than the general 5 attempts, still
        # succeed: throttles have their own counter and a capped sleep.
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            if calls["n"] <= 8:
                raise _http_error(429, "Too many requests")
            return {"ok": True}

        with mock.patch.object(endpoints.time, "sleep") as sleep:
            self.assertEqual(endpoints._with_retries(call, attempts=5, base=2.0), {"ok": True})
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(len(waits), 8)
        self.assertLess(waits[0], 10)
        self.assertLessEqual(max(waits), endpoints.THROTTLE_MAX_SLEEP + 1.5)

    def test_a_throttle_that_never_clears_is_an_error(self):
        def call():
            raise _http_error(429, "Too many requests")

        with mock.patch.object(endpoints.time, "sleep"), \
                mock.patch.object(endpoints, "THROTTLE_ATTEMPTS", 3):
            with self.assertRaises(endpoints.EndpointError):
                endpoints._with_retries(call, attempts=5)

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


class MonthlyCreditsTest(unittest.TestCase):
    def test_a_spent_monthly_credit_cap_waits_like_a_usage_limit(self):
        calls = {"n": 0}

        def call():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429, '{"error":"usage credits auto reload monthly max reached, add usage credits"}')
            return {"ok": True}

        with mock.patch.object(endpoints.time, "sleep") as sleep, \
                mock.patch.object(endpoints, "USAGE_LIMIT_WAIT", 300):
            self.assertEqual(endpoints._with_retries(call, attempts=2), {"ok": True})
        self.assertGreaterEqual(sleep.call_args_list[0].args[0], 300)
