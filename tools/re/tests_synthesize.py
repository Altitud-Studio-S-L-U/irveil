"""Standard-library contract tests; real SMT checks belong to recorded evaluations."""

import json
import signal
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import synthesize


class SynthesisProtocolTests(unittest.TestCase):
    def learn(self, expression, width=32, proof="unsat"):
        fake_z3 = SimpleNamespace(get_version_string=lambda: synthesize.PROTOCOL["z3Version"])
        with mock.patch.dict(sys.modules, {"z3": fake_z3}), \
                mock.patch.object(synthesize.simba, "prove", return_value=proof):
            return synthesize.learn({"expression": expression, "width": width, "profile": "expanded"})

    def test_samples_are_repeatable_and_holdout_is_separate(self):
        for width in (32, 64):
            with self.subTest(width=width):
                training, holdout = synthesize.sample_points(width)
                self.assertEqual((training, holdout), synthesize.sample_points(width))
                self.assertEqual(len(training), 96)
                self.assertEqual(len(holdout), 32)
                self.assertFalse(set(training) & set(holdout))
                mask = (1 << width) - 1
                self.assertIn((0, mask), training)
                self.assertIn((mask, 0), training)
                self.assertTrue(all(0 <= value <= mask for pair in training + holdout for value in pair))
        self.assertNotEqual(synthesize.sample_points(32), synthesize.sample_points(64))

    def test_grammar_recognizes_observed_operations_without_source_identity(self):
        for width in (32, 64):
            for expression in ["p0", "~p0", "-p0", "p0+17", "p0+p0",
                               "p0+p1", "p0-p1", "p0*p1", "p0&p1", "p0|p1", "p0^p1"]:
                with self.subTest(width=width, expression=expression):
                    result = self.learn(expression, width)
                    self.assertEqual(result["status"], "recovered")
                    self.assertTrue(result["holdoutPassed"])
                    self.assertEqual(result["inputEquivalent"], "unsat")
                    self.assertLessEqual(result["candidatesChecked"], 234)
                    self.assertNotIn("sourceOperation", result)
                    tree = synthesize.simba.parse_expression(result["learned"], "expanded")
                    operators = sum(isinstance(node, (synthesize.ast.BinOp, synthesize.ast.UnaryOp))
                                    for node in synthesize.ast.walk(tree))
                    self.assertLessEqual(operators, 1)
        self.assertEqual(self.learn("p0+17")["derivedConstant"], 17)

    def test_sampling_match_requires_smt_proof(self):
        self.assertEqual(self.learn("p0+p1", proof="unknown")["status"], "timeout")
        self.assertEqual(self.learn("p0+p1", proof="sat")["status"], "not_recovered")

    def test_function_outside_small_grammar_is_not_claimed_recovered(self):
        result = self.learn("((p0+p1)^(p0+17))")
        self.assertEqual(result["status"], "not_recovered")
        self.assertEqual(result["candidatesChecked"], 234)
        self.assertNotIn("inputEquivalent", result)

    def test_unsupported_input_is_distinct_from_failed_search(self):
        for expression, width in [("p2+p0", 32), ("p0**2", 32), ("p0+p1", 16)]:
            with self.subTest(expression=expression, width=width):
                self.assertEqual(self.learn(expression, width)["status"], "unsupported")

    def test_extraction_outcomes_are_preserved_without_starting_worker(self):
        for status in ("unsupported", "timeout", "error"):
            with self.subTest(status=status), mock.patch.object(synthesize.subprocess, "run") as run:
                outcome = synthesize.recognize({"id": "re_loop64", "status": status,
                                                "reason": "fixture reason"}, "expanded")
                self.assertEqual(outcome["status"], status)
                self.assertEqual(outcome["stage"], "extraction")
                run.assert_not_called()

    def test_worker_failures_and_timeouts_remain_distinct(self):
        record = {"id": "re_sum32", "width": 32, "expression": "p0+p1", "status": "extracted"}
        responses = [
            (subprocess.TimeoutExpired("worker", 5), "timeout"),
            (SimpleNamespace(returncode=-getattr(signal, "SIGXCPU", 24), stdout="", stderr=""), "timeout"),
            (SimpleNamespace(returncode=1, stdout="", stderr="failure"), "error"),
            (SimpleNamespace(returncode=0, stdout="invalid json", stderr=""), "error"),
            (SimpleNamespace(returncode=0, stdout="[]", stderr=""), "error"),
            (SimpleNamespace(returncode=0, stdout='{"status":"invalid"}', stderr=""), "error"),
        ]
        for response, expected in responses:
            with self.subTest(expected=expected, response=response):
                arguments = {"side_effect": response} if isinstance(response, BaseException) else {"return_value": response}
                with mock.patch.object(synthesize.subprocess, "run", **arguments):
                    outcome = synthesize.recognize(record, "expanded")
                self.assertEqual(outcome["status"], expected)

    def test_worker_request_excludes_source_and_function_identity(self):
        record = {"id": "re_sum32", "width": 32, "expression": "p0+p1",
                  "sourceOperation": "p0+p1", "status": "extracted"}
        response = SimpleNamespace(returncode=0, stdout='{"status":"unsupported","reason":"mock"}', stderr="")
        with mock.patch.object(synthesize.subprocess, "run", return_value=response) as run:
            outcome = synthesize.recognize(record, "expanded")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(set(request), {"expression", "width", "profile"})
        self.assertEqual(outcome["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
