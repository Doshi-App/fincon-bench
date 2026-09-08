"""The judge's answer is JSON. Judges wrap it, follow it, or mention braces
in prose; the parser must still find the verdict."""
import unittest

from fincon_runner.judge import parse_verdict


class ParseVerdictTest(unittest.TestCase):
    def test_fenced_json_with_trailing_prose(self):
        raw = 'Here is my answer:\n```json\n{"verdict": "pass", "reasoning": "fine", "quoted_text": ""}\n```\nNote: {braces} in prose.'
        self.assertEqual(parse_verdict(raw, "m").verdict, "pass")

    def test_two_objects_first_with_verdict_wins(self):
        raw = '{"note": "x"} then {"verdict": "fail", "reasoning": "r", "quoted_text": "q"}'
        result = parse_verdict(raw, "m")
        self.assertEqual((result.verdict, result.quoted_text), ("fail", "q"))

    def test_braces_inside_strings_do_not_break_balance(self):
        raw = '{"verdict": "pass", "reasoning": "the rule says {x} and }", "quoted_text": ""}'
        self.assertEqual(parse_verdict(raw, "m").verdict, "pass")

    def test_no_json_is_an_error_that_keeps_the_raw_text(self):
        result = parse_verdict("I think this passes.", "m")
        self.assertEqual(result.verdict, "error")
        self.assertEqual(result.raw, "I think this passes.")
