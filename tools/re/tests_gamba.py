from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import gamba
import simba


class GeneralAttackAdapterTests(unittest.TestCase):
    def test_missing_expression_cannot_be_inherited_as_recovery(self):
        with self.assertRaises(ValueError):
            gamba.validate_input_record({"id": "re_sum32", "status": "recovered"}, "primary")
        gamba.validate_input_record({"id": "re_loop64", "status": "unsupported", "reason": "control flow"}, "primary")

    def test_expands_only_bounded_powers_and_shifts(self):
        self.assertEqual(gamba.normalize_output("p0**2", 32), "(p0*p0)")
        self.assertEqual(gamba.normalize_output("p0<<2", 32), "(p0*4)")
        for expression in ("p0**p1", "p0**65", "p0<<32", "p0>>1", "f(p0)"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                gamba.normalize_output(expression, 32)
        self.assertIsNone(simba.linear_arithmetic(simba.parse_expression(gamba.normalize_output("p0**2", 32)), 32))

    def test_retries_extracted_expressions_rejected_by_simba(self):
        record = {"id": "re_sum32", "status": "unsupported", "expression": "p0+p1", "width": 32}
        response = subprocess.CompletedProcess([], 0, '{"status":"recovered","simplified":"p0+p1"}', "")
        with patch.object(subprocess, "run", return_value=response):
            outcome = gamba.run_record(record, Path("unused"))
        self.assertEqual(outcome["status"], "recovered")
        self.assertEqual(outcome["simbaStatus"], "unsupported")
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 5)):
            self.assertEqual(gamba.run_record(record, Path("unused"))["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
