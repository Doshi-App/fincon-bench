import unittest

from fincon_runner.providers import default_repeats_for, REPEATED_PROVIDER_KINDS


class DefaultRepeatsTest(unittest.TestCase):
    def test_passes_per_provider_kind(self):
        self.assertEqual(default_repeats_for("bedrock"), 5)
        self.assertEqual(default_repeats_for("ollama"), 5)
        self.assertEqual(default_repeats_for("anthropic"), 3)
        self.assertEqual(default_repeats_for("openai"), 1)
        self.assertEqual(default_repeats_for("http"), 1)

    def test_repeated_kinds_are_those_above_one_pass(self):
        self.assertEqual(REPEATED_PROVIDER_KINDS, frozenset({"bedrock", "ollama", "anthropic"}))
