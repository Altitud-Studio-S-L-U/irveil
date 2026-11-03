#!/usr/bin/env python3
"""Failure controls for the RE evaluator; actual Ghidra is exercised separately."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("irveil_re_evaluate", Path(__file__).with_name("evaluate.py"))
EVALUATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATE)


class EvaluationControls(unittest.TestCase):
    def test_symbol_mapping_uses_each_companion_and_rejects_missing_or_duplicate(self):
        symbols = "\n".join(f"{0x401000 + index * 16:016x} 0000000000000004 T {name}"
                            for index, name in enumerate(EVALUATE.FUNCTIONS))
        mapped = EVALUATE.mapped_functions(symbols)
        self.assertEqual(mapped[1]["address"], "401010")
        relocated = symbols.replace("0000000000401", "0000000000501")
        self.assertNotEqual(mapped[0]["address"], EVALUATE.mapped_functions(relocated)[0]["address"])
        with self.assertRaisesRegex(ValueError, "Missing"):
            EVALUATE.mapped_functions(symbols.splitlines()[0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            EVALUATE.mapped_functions(symbols + "\n" + symbols.splitlines()[0])

    def test_normalization_retains_semantic_constants_operators_and_warnings(self):
        left = "int FUN_00401130(int param_1) { return param_1 + 17; }"
        right = "int FUN_00409999(int param_1) {\n return param_1 + 17; }"
        self.assertEqual(EVALUATE.normalize_c(left), EVALUATE.normalize_c(right))
        self.assertNotEqual(EVALUATE.normalize_c(left), EVALUATE.normalize_c(right.replace("+ 17", "^ 17")))
        self.assertNotEqual(EVALUATE.normalize_c(left), EVALUATE.normalize_c(right.replace("17", "18")))
        self.assertIn("WARNING", EVALUATE.normalize_c("/* WARNING */ " + left))

    def fixture(self, directory):
        manifest = {"binarySha256": "a" * 64, "functions": []}
        report = {"schemaVersion": 1, "status": "completed", "analysisTimedOut": False,
                  "ghidraVersion": "12.2", "javaVersion": "25.0.5", "jvmMaxHeapBytes": 1073741824,
                  "availableProcessors": 2, "binarySha256": "a" * 64, "functions": []}
        for index, name in enumerate(EVALUATE.FUNCTIONS):
            address = format(0x401000 + index * 16, "x")
            manifest["functions"].append({"id": name, "address": address, "size": 4})
            report["functions"].append({
                "id": name, "status": "completed", "timedOut": False, "cancelled": False,
                "entryAddress": address, "cFile": name + ".c", "pcodeFile": name + ".pcode.txt",
                "nativeInstructions": 2, "nativeInstructionBytes": 4, "nativeCalls": 0, "nativeJumps": 0,
                "rawPcodeOperations": 4, "rawPcodeHistogram": {"INT_ADD": 1},
                "highPcodeOperations": 2, "highPcodeHistogram": {"INT_ADD": 1},
                "highBasicBlocks": 1, "highEdges": 0,
            })
            (directory / (name + ".c")).write_text("return param_1 + param_2;\n", encoding="utf-8")
            (directory / (name + ".pcode.txt")).write_text("synthetic control fixture\n", encoding="utf-8")
        return manifest, report

    def test_incomplete_exports_fail_instead_of_becoming_candidate_improvements(self):
        with tempfile.TemporaryDirectory(prefix="irveil-re-controls-") as temporary:
            directory = Path(temporary)
            manifest, valid = self.fixture(directory)
            path = directory / "export.json"
            path.write_text(json.dumps(valid), encoding="utf-8")
            _, facts = EVALUATE.validate_export(path, manifest)
            self.assertEqual(set(facts), set(EVALUATE.FUNCTIONS))
            mutations = [
                lambda report: report.update(status="incomplete"),
                lambda report: report.update(analysisTimedOut=True),
                lambda report: report.update(binarySha256="b" * 64),
                lambda report: report.update(jvmMaxHeapBytes=2 * 1073741824),
                lambda report: report.update(availableProcessors=3),
                lambda report: report["functions"].pop(),
                lambda report: report["functions"][0].update(status="decompile_failed"),
                lambda report: report["functions"][0].update(timedOut=True),
                lambda report: report["functions"][0].update(cancelled=True),
                lambda report: report["functions"][0].update(entryAddress="402000"),
                lambda report: report["functions"][0].update(cFile="../outside.c"),
                lambda report: report["functions"][0].update(highPcodeOperations=0),
            ]
            for index, mutate in enumerate(mutations):
                with self.subTest(failure=index):
                    report = copy.deepcopy(valid)
                    mutate(report)
                    path.write_text(json.dumps(report), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        EVALUATE.validate_export(path, manifest)
            path.write_text(json.dumps(valid), encoding="utf-8")
            (directory / valid["functions"][0]["pcodeFile"]).unlink()
            with self.assertRaisesRegex(ValueError, "Missing"):
                EVALUATE.validate_export(path, manifest)

    def test_repeat_control_rejects_text_change_even_with_equal_instruction_counts(self):
        with tempfile.TemporaryDirectory(prefix="irveil-re-controls-") as temporary:
            directory = Path(temporary)
            manifest, report = self.fixture(directory)
            path = directory / "export.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            _, facts = EVALUATE.validate_export(path, manifest)
            self.assertEqual(EVALUATE.compare_control(facts, facts)["status"], "passed")
            changed = copy.deepcopy(facts)
            changed["re_sum32"]["normalizedC"] = "return param_1 - param_2;"
            with self.assertRaisesRegex(ValueError, "unstable"):
                EVALUATE.compare_control(facts, changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
