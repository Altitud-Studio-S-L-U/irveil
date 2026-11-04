from pathlib import Path
import subprocess
import signal
import unittest
from unittest.mock import patch

import simba


class ExpressionContractTests(unittest.TestCase):
    def test_accepts_only_bounded_mba_grammar(self):
        for expression in ("__import__('os')", "p0[0]", "p4+1", "p0**2", "p0>>1", "True", "1.5", "p0+"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                simba.parse_expression(expression)
        with self.assertRaises(ValueError):
            simba.parse_expression("1" * 16385)
        simba.parse_expression("((p0^p1)+2*(p0&p1))")

    def test_recovery_requires_removing_bitwise_operations(self):
        width = 32
        self.assertIsNone(simba.linear_arithmetic(simba.parse_expression("(p0^p1)+2*(p0&p1)"), width))
        self.assertEqual(simba.linear_arithmetic(simba.parse_expression("p1+p0"), width), {"p0": 1, "p1": 1})
        self.assertEqual(simba.linear_arithmetic(simba.parse_expression("4294967295*p0+2*p0"), width), {"p0": 1})
        self.assertIsNone(simba.linear_arithmetic(simba.parse_expression("p0*p1"), width))

    def test_expanded_profile_is_explicit(self):
        expression = "p0" + " " * 17000
        with self.assertRaises(ValueError):
            simba.parse_expression(expression)
        simba.parse_expression(expression, "expanded")

    def test_auto_analysis_timeout_remains_timeout_after_export(self):
        import evaluate
        report = {"schemaVersion": 1, "status": "timeout", "jvmMaxHeapBytes": 1073741824,
                  "availableProcessors": 2, "ghidraVersion": "12.2", "javaVersion": "25.0.5", "profile": "expanded",
                  "binarySha256": "abc", "analysisTimedOut": True,
                  "functions": [{"id": name, "status": "timeout", "stage": "ghidra_auto_analysis", "reason": "analysis deadline"}
                                for name in evaluate.FUNCTIONS]}
        validated = simba.validate_expression_export(report, {"binarySha256": "abc"}, "expanded")
        with patch.object(subprocess, "run") as run:
            self.assertTrue(all(simba.run_simba(record, Path("unused"))["status"] == "timeout"
                                for record in validated["functions"]))
            run.assert_not_called()
        report["functions"][0]["status"] = "unsupported"
        with self.assertRaises(ValueError):
            simba.validate_expression_export(report, {"binarySha256": "abc"}, "expanded")

    def test_export_cannot_claim_recovery_without_running_attack(self):
        import evaluate
        report = {"schemaVersion": 1, "status": "completed", "jvmMaxHeapBytes": 1073741824,
                  "availableProcessors": 2, "ghidraVersion": "12.2", "javaVersion": "25.0.5", "profile": "primary",
                  "binarySha256": "abc", "analysisTimedOut": False,
                  "functions": [{"id": name, "status": "recovered"} for name in evaluate.FUNCTIONS]}
        with self.assertRaises(ValueError):
            simba.validate_expression_export(report, {"binarySha256": "abc"}, "primary")
        for record in report["functions"]:
            record.update(status="extracted", expression="p0+p1", width=32, parameters=[0, 1],
                          sliceNodes=3, nativeInstructions=2, nativeBytes=4)
        simba.validate_expression_export(report, {"binarySha256": "abc"}, "primary")
        report["functions"][0]["width"] = 128
        with self.assertRaises(ValueError):
            simba.validate_expression_export(report, {"binarySha256": "abc"}, "primary")

    def test_timeout_is_distinct_from_error_and_unsupported(self):
        record = {"id": "re_sum32", "status": "extracted", "expression": "p0+p1", "width": 32}
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 5)):
            self.assertEqual(simba.run_simba(record, Path("unused"))["status"], "timeout")
        unsupported = {"id": "re_loop64", "status": "unsupported", "reason": "control flow"}
        with patch.object(subprocess, "run") as run:
            self.assertEqual(simba.run_simba(unsupported, Path("unused")), unsupported)
            run.assert_not_called()
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "failure")):
            self.assertEqual(simba.run_simba(record, Path("unused"))["status"], "error")
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], -getattr(signal, "SIGXCPU", 24), "", "")):
            self.assertEqual(simba.run_simba(record, Path("unused"))["status"], "timeout")
        manifest = {"functions": [{"id": "re_sum32"}]}
        self.assertEqual(simba.failed_export_records(manifest, "Ghidra deadline", True)[0]["status"], "timeout")
        self.assertEqual(simba.failed_export_records(manifest, "invalid manifest", False)[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
