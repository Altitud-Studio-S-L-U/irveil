#!/usr/bin/env python3
"""Black-box LLVM 18 integration tests; no dependency on the pass implementation."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OPTIONS = None


def execute(arguments, *, input_text=None, environment=None, timeout=90):
    return subprocess.run(
        [str(argument) for argument in arguments], input=input_text,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, timeout=timeout, check=False,
    )


def canonical_ir(text):
    return "\n".join(line for line in text.splitlines()
                     if not line.startswith("; ModuleID ="))


def function_body(text, name):
    match = re.search(r"^define[^\n]*@" + re.escape(name) +
                      r"\([^\n]*\)[^{]*\{(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"Function {name!r} missing from LLVM output")
    return match.group(1)


def instructions(body):
    return [line.strip() for line in body.splitlines()
            if line.strip() and not line.lstrip().startswith(";")
            and not re.match(r"^[\w.$-]+:", line.strip())]


def annotations(names):
    entries = ",\n".join(
        "  { ptr, ptr, ptr, i32, ptr } { ptr @" + name +
        ", ptr @.annotation, ptr @.source, i32 1, ptr null }" for name in names)
    return (
        '@.annotation = private unnamed_addr constant [7 x i8] c"irveil\\00"\n'
        '@.source = private unnamed_addr constant [1 x i8] zeroinitializer\n'
        f'@llvm.global.annotations = appending global [{len(names)} x '
        '{ ptr, ptr, ptr, i32, ptr }] [\n' + entries + '\n], section "llvm.metadata"\n'
    )


def exhaustive_module():
    """Compare every small bit-vector pair to LLVM add, outside selected code."""
    pieces = ['source_filename = "exhaustive.ll"\n',
              'target triple = "x86_64-pc-linux-gnu"\n',
              annotations([f"small{width}" for width in range(2, 9)])]
    for width in range(2, 9):
        limit = 1 << width
        pieces.append(f"""
define i{width} @small{width}(i{width} %a, i{width} %b) {{
  %sum = add i{width} %a, %b
  ret i{width} %sum
}}
define i32 @verify{width}() {{
entry:
  br label %outer
outer:
  %a = phi i16 [ 0, %entry ], [ %nexta, %next_outer ]
  br label %inner
inner:
  %b = phi i16 [ 0, %outer ], [ %nextb, %next_inner ]
  %small_a = trunc i16 %a to i{width}
  %small_b = trunc i16 %b to i{width}
  %actual = call i{width} @small{width}(i{width} %small_a, i{width} %small_b)
  %wide_expected = add i16 %a, %b
  %expected = trunc i16 %wide_expected to i{width}
  %equal = icmp eq i{width} %actual, %expected
  br i1 %equal, label %next_inner, label %failed
next_inner:
  %nextb = add i16 %b, 1
  %more_b = icmp ult i16 %nextb, {limit}
  br i1 %more_b, label %inner, label %next_outer
next_outer:
  %nexta = add i16 %a, 1
  %more_a = icmp ult i16 %nexta, {limit}
  br i1 %more_a, label %outer, label %passed
failed:
  ret i32 1
passed:
  ret i32 0
}}
""")
    pieces.append("define i32 @main() {\n")
    for width in range(2, 9):
        pieces.append(f"  %r{width} = call i32 @verify{width}()\n")
    pieces.append("  %combined3 = or i32 %r2, %r3\n")
    for width in range(4, 9):
        pieces.append(f"  %combined{width} = or i32 %combined{width - 1}, %r{width}\n")
    pieces.append("  ret i32 %combined8\n}\n")
    return "".join(pieces)


class IRVeilTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llvm = Path(OPTIONS.llvm_bin).resolve()
        cls.plugin = Path(OPTIONS.plugin).resolve()
        cls.include = Path(OPTIONS.include).resolve()
        cls.temporary = tempfile.TemporaryDirectory(prefix="irveil-tests-")
        cls.work = Path(cls.temporary.name).resolve()
        for tool in ["opt", "clang++", "lli", "llvm-config"]:
            if not (cls.llvm / tool).is_file():
                raise RuntimeError(f"Required LLVM tool missing: {cls.llvm / tool}")
        version = execute([cls.llvm / "llvm-config", "--version"])
        if version.returncode or not version.stdout.strip().startswith("18."):
            raise RuntimeError(f"LLVM 18 required: {version.stdout}{version.stderr}")
        if not cls.plugin.is_file():
            raise RuntimeError(f"Plugin missing: {cls.plugin}")

    @classmethod
    def tearDownClass(cls):
        # Only the directory returned by our own TemporaryDirectory is removable.
        if cls.work.parent != Path(tempfile.gettempdir()).resolve() or not cls.work.name.startswith("irveil-tests-"):
            raise RuntimeError("Refusing temporary cleanup outside the owned test directory")
        cls.temporary.cleanup()

    def checked(self, arguments, **kwargs):
        result = execute(arguments, **kwargs)
        self.assertEqual(result.returncode, 0,
                         f"Command failed: {shlex.join(map(str, arguments))}\n"
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def transform(self, source, pipeline="irveil"):
        return self.checked([
            self.llvm / "opt", "-load-pass-plugin", self.plugin,
            f"-passes={pipeline}", "-verify-each", "-S", "-o", "-", "-",
        ], input_text=source).stdout

    def fixture(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def compile_demo(self, name, optimization, *, plugin=False, extra=()):
        output = self.work / name
        command = [self.llvm / "clang++", "-std=c++17", optimization,
                   "-I", self.include, *extra]
        if plugin:
            command.append(f"-fpass-plugin={self.plugin}")
        self.checked([*command, ROOT / "examples" / "demo.cpp", "-o", output])
        return output

    def test_selection_exclusions_and_no_new_effects(self):
        source = self.fixture("selection.ll")
        transformed = self.transform(source)
        for name in ["unselected", "excluded_widths"]:
            self.assertEqual(function_body(transformed, name).strip(),
                             function_body(self.transform(source, "verify"), name).strip())
        selected = function_body(transformed, "protected")
        self.assertNotRegex(selected, r"add i32 %a, %b")
        self.assertGreaterEqual(len(re.findall(r"\bfreeze i32\b", selected)), 16)
        baseline = function_body(self.transform(source, "verify"), "protected")
        for opcode in ["call", "invoke", "load", "store", "alloca", "fence", "atomicrmw", "cmpxchg", "br", "switch"]:
            pattern = rf"\b{opcode}\b"
            self.assertEqual(len(re.findall(pattern, selected)), len(re.findall(pattern, baseline)), opcode)
        self.assertEqual(len(re.findall(r"^@", transformed, re.MULTILINE)),
                         len(re.findall(r"^@", source, re.MULTILINE)))
        self.assertRegex(transformed, r"declare i32 @external\(")

    def test_per_function_cap_and_bounded_expansion(self):
        source = self.fixture("selection.ll")
        original = function_body(self.transform(source, "verify"), "protected")
        for cap in [1, 3, 8, 4096]:
            with self.subTest(cap=cap):
                transformed = self.transform(source, f"irveil<max-adds={cap};seed=17>")
                body = function_body(transformed, "protected")
                rewritten = min(cap, 8)
                self.assertEqual(len(re.findall(r"add i32 %a, %b", body)), 8 - rewritten)
                self.assertEqual(len(re.findall(r"\bfreeze i32\b", body)), 2 * rewritten)
                self.assertGreater(len(instructions(body)), len(instructions(original)))
                self.assertLessEqual(len(instructions(body)), len(instructions(original)) + 5 * rewritten)
                other = function_body(transformed, "flags")
                other_rewritten = min(cap, 3)
                self.assertEqual(len(re.findall(r"\bfreeze i32\b", other)), 2 * other_rewritten,
                                 "The cap applies independently to each selected function")

    def test_default_cap_and_every_documented_scalar_width(self):
        names = [f"width{width}" for width in range(2, 65)] + ["default_cap"]
        source = ['source_filename = "widths-and-default-cap.ll"\n', annotations(names)]
        for width in range(2, 65):
            source.append(f"define i{width} @width{width}(i{width} %a, i{width} %b) {{\n"
                          f"  %sum = add i{width} %a, %b\n  ret i{width} %sum\n}}\n")
        source.append("define i32 @default_cap(i32 %a, i32 %b) {\n")
        source.extend(f"  %sum{index} = add i32 %a, %b\n" for index in range(300))
        source.append("  ret i32 %sum299\n}\n")
        output = self.transform("".join(source))
        for width in range(2, 65):
            with self.subTest(width=width):
                body = function_body(output, f"width{width}")
                self.assertNotRegex(body, rf"add i{width} %a, %b")
                self.assertEqual(len(re.findall(rf"\bfreeze i{width}\b", body)), 2)
        capped = function_body(output, "default_cap")
        self.assertEqual(len(re.findall(r"add i32 %a, %b", capped)), 44)
        self.assertEqual(len(re.findall(r"\bfreeze i32\b", capped)), 512)

    def test_no_arithmetic_flags_are_copied_to_replacements(self):
        transformed = self.transform(self.fixture("selection.ll"))
        body = function_body(transformed, "flags")
        self.assertNotRegex(body, r"\b(?:nsw|nuw|exact)\b")
        self.assertEqual(len(re.findall(r"\bfreeze i32\b", body)), 6)

    def test_original_undef_operand_is_used_only_through_freeze(self):
        # This follows the LLVM undef counterexample, not the pass's choice formula.
        source = self.fixture("undef.ll")
        choices = set()
        for seed in range(16):
            with self.subTest(seed=seed):
                body = function_body(self.transform(source, f"irveil<seed={seed}>"), "undef_choice")
                uses = [line.strip() for line in body.splitlines()
                        if re.search(r"%a\b", line) and not re.match(r"\s*%a\s*=", line)]
                self.assertEqual(len(uses), 1)
                self.assertRegex(uses[0], r"= freeze i8 %a\b")
                self.assertNotRegex(body, r"add i8 %a, 1")
                choices.update(re.findall(r"\b(add|sub) i8\b", body))
        self.assertEqual(choices, {"add", "sub"}, "The seed corpus must exercise both documented identities")

    def test_repeat_pass_is_idempotent_and_seed_is_reproducible(self):
        source = self.fixture("selection.ll")
        pipeline = "irveil<seed=42;max-adds=8>"
        once = canonical_ir(self.transform(source, pipeline))
        self.assertEqual(once, canonical_ir(self.transform(source, pipeline)))
        self.assertEqual(once, canonical_ir(self.transform(source, f"{pipeline},{pipeline}")))
        self.assertEqual(once, canonical_ir(self.transform(source, f"{pipeline},irveil<seed=999;max-adds=1>")))
        self.assertEqual(once, canonical_ir(self.transform(self.transform(source, pipeline), pipeline)))
        outputs = {canonical_ir(self.transform(source, f"irveil<seed={seed};max-adds=8>"))
                   for seed in range(16)}
        self.assertGreater(len(outputs), 1, "Seed corpus produced no distinct transformed output")

    def test_general_additions_survive_the_documented_canonicalization_corpus(self):
        result = self.checked([sys.executable, ROOT / "tools" / "check_canonicalization.py",
                               "--llvm-bin", self.llvm, "--plugin", self.plugin])
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["seeds"], list(range(16)))
        self.assertEqual(report["widths"], [2, 8, 32, 64])
        self.assertEqual(set(report["results"]), {"instcombine", "canonicalize", "O2", "O3"})
        for pipeline, observation in report["results"].items():
            with self.subTest(pipeline=pipeline):
                self.assertEqual(observation["generalCases"], 128)
                self.assertEqual(observation["singleAddRestorations"], 0)
                self.assertEqual(observation["controlCases"], 128)
                self.assertEqual(observation["controlMismatches"], 0)

    def test_explicit_loading_does_not_run_without_requested_pipeline(self):
        output = self.transform(self.fixture("selection.ll"), "verify")
        self.assertEqual(len(re.findall(r"add i32 %a, %b", function_body(output, "protected"))), 8)
        self.assertNotIn("freeze", function_body(output, "protected"))

    def test_empty_and_unannotated_modules_are_unchanged(self):
        for fixture in ["empty.ll", "unannotated.ll"]:
            with self.subTest(fixture=fixture):
                source = self.fixture(fixture)
                self.assertEqual(canonical_ir(self.transform(source)),
                                 canonical_ir(self.transform(source, "verify")))

    def test_invalid_options_are_rejected(self):
        options = [
            "", "seed", "seed=", "seed=-1", "seed=+1", "seed=1.0", "seed=0x10",
            "seed=18446744073709551616", "max-adds=0", "max-adds=4097",
            "max-adds=-1", "max-adds=1.5", "max-adds=4294967296",
            "unknown=1", "seed=1;seed=2", "max-adds=1;max-adds=2", "seed=1;",
        ]
        for option in options:
            with self.subTest(option=option):
                result = execute([
                    self.llvm / "opt", "-load-pass-plugin", self.plugin,
                    f"-passes=irveil<{option}>", "-disable-output", "-",
                ], input_text=self.fixture("empty.ll"))
                self.assertNotEqual(result.returncode, 0, "Invalid pipeline was accepted")
                self.assertTrue(result.stderr.strip(), "Rejected options need a diagnostic")
        self.transform(self.fixture("selection.ll"),
                       "irveil<seed=18446744073709551615;max-adds=4096>")

    def test_exhaustive_modular_addition_for_widths_two_through_eight(self):
        source = exhaustive_module()
        # A deliberately wrong operation must fail the independent execution oracle.
        mutant = self.work / "exhaustive-wrong-operation.ll"
        mutant.write_text(source.replace("%sum = add i2 %a, %b", "%sum = sub i2 %a, %b", 1), encoding="utf-8")
        self.assertNotEqual(execute([self.llvm / "lli", mutant]).returncode, 0)
        for seed in [0, 1, 42]:
            with self.subTest(seed=seed):
                transformed = self.transform(source, f"irveil<seed={seed}>")
                path = self.work / f"exhaustive-{seed}.ll"
                path.write_text(transformed, encoding="utf-8")
                self.checked([self.llvm / "lli", path])

    def test_32_and_64_bit_boundary_random_and_defined_flagged_inputs(self):
        source = self.fixture("semantics.ll")
        for seed in [0, 1, 42]:
            with self.subTest(seed=seed):
                transformed = self.work / f"semantics-{seed}.ll"
                transformed.write_text(self.transform(source, f"irveil<seed={seed}>"), encoding="utf-8")
                object_path = self.work / f"semantics-{seed}.o"
                self.checked([self.llvm / "clang++", "-O0", "-c", transformed, "-o", object_path])
                executable = self.work / f"native-{seed}"
                self.checked([self.llvm / "clang++", "-std=c++17", "-O2",
                              FIXTURES / "native-check.cpp", object_path, "-o", executable])
                result = self.checked([executable])
                self.assertEqual(result.stdout.strip(), "checked=300146")

    def test_source_annotation_and_clang_optimizer_integration(self):
        for optimization in ["-O0", "-O1", "-O2", "-O3"]:
            with self.subTest(optimization=optimization):
                baseline = self.compile_demo(f"demo-plain-{optimization[1:]}", optimization)
                obfuscated = self.compile_demo(f"demo-obfuscated-{optimization[1:]}", optimization, plugin=True)
                expected = self.checked([baseline, "10000"]).stdout
                actual = self.checked([obfuscated, "10000"]).stdout
                self.assertRegex(expected, r"^[0-9a-f]{16}\n$")
                self.assertEqual(actual, expected)
                ir = self.checked([
                    self.llvm / "clang++", "-std=c++17", optimization, "-I", self.include,
                    f"-fpass-plugin={self.plugin}", "-S", "-emit-llvm", ROOT / "examples" / "demo.cpp", "-o", "-",
                ]).stdout
                body = function_body(ir, "irveil_demo_step")
                self.assertRegex(body, r"\bfreeze i(?:32|64)\b",
                                 "Source annotation did not cause transformation at this optimization mode")
                header = re.search(r"^define[^\n]*@irveil_demo_step\([^\n]*\)[^{]*\{", ir, re.MULTILINE).group(0)
                attribute_group = re.search(r"#(\d+)", header)
                self.assertIsNotNone(attribute_group, "Protected source function needs an attribute group")
                attributes = re.search(r"^attributes #" + attribute_group.group(1) + r" = \{([^}]+)\}", ir, re.MULTILINE)
                self.assertIsNotNone(attributes)
                self.assertRegex(attributes.group(1), r"\bnoinline\b")

    def test_clang_configuration_and_diagnostics(self):
        command = [self.llvm / "clang++", "-O2", "-I", self.include,
                   "-Xclang", "-load", "-Xclang", self.plugin,
                   f"-fpass-plugin={self.plugin}", "-S", "-emit-llvm",
                   ROOT / "examples/demo.cpp", "-o", "-"]
        outputs = []
        for seed in [0, 42, 18446744073709551615]:
            result = self.checked([*command, "-mllvm", f"-irveil-seed={seed}",
                                   "-mllvm", "-irveil-max-adds=1",
                                   "-mllvm", "-irveil-report"])
            self.assertIn(f"seed={seed} max-adds=1 selected=1 changed=1 rewritten-adds=1",
                          result.stderr)
            outputs.append(canonical_ir(result.stdout))
        self.assertGreater(len(set(outputs)), 1)
        for option, diagnostic in [
                ("-irveil-seed=-1", "0..18446744073709551615"),
                ("-irveil-seed=0x10", "unsigned decimal"),
                ("-irveil-seed=18446744073709551616", "unsigned decimal"),
                ("-irveil-max-adds=0", "1..4096"),
                ("-irveil-max-adds=4097", "1..4096")]:
            with self.subTest(option=option):
                result = execute([*command, "-mllvm", option])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("IRVeil:", result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(result.stdout, "")

        # Explicit opt pipelines retain their own configuration, even if the
        # command-line settings used by Clang's extension point are present.
        source = self.fixture("selection.ll")
        expected = self.transform(source, "irveil<seed=42;max-adds=3>")
        actual = self.checked([
            self.llvm / "opt", "-load-pass-plugin", self.plugin,
            "-irveil-seed=9", "-irveil-max-adds=1",
            "-passes=irveil<seed=42;max-adds=3>", "-verify-each", "-S", "-o", "-", "-",
        ], input_text=source).stdout
        self.assertEqual(canonical_ir(actual), canonical_ir(expected))

    def test_asan_and_ubsan_where_the_baseline_runtime_works(self):
        flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=all"]
        probe_source = self.work / "sanitizer-probe.cpp"
        probe_source.write_text("int main() { return 0; }\n", encoding="utf-8")
        probe_binary = self.work / "sanitizer-probe"
        compiled = execute([self.llvm / "clang++", *flags, probe_source, "-o", probe_binary])
        if compiled.returncode:
            self.skipTest("Sanitizer baseline cannot link: " + compiled.stderr[-1500:])
        environment = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                       "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
        probed = execute([probe_binary], environment=environment)
        if probed.returncode:
            self.skipTest("Sanitizer baseline runtime unavailable: " + probed.stderr[-1500:])
        baseline = self.compile_demo("sanitized-plain", "-O1", extra=flags)
        obfuscated = self.compile_demo("sanitized-obfuscated", "-O1", plugin=True, extra=flags)
        expected = self.checked([baseline, "10000"], environment=environment).stdout
        actual = self.checked([obfuscated, "10000"], environment=environment).stdout
        self.assertEqual(actual, expected)

    def test_separate_static_library_consumer_and_configuration_errors(self):
        if not OPTIONS.core:
            self.skipTest("--core was not supplied; the separate static-library consumer was not tested")
        core = Path(OPTIONS.core).resolve()
        self.assertTrue(core.is_file(), f"Static library missing: {core}")
        compiler_flags = shlex.split(self.checked([self.llvm / "llvm-config", "--cxxflags"]).stdout)
        linker_flags = shlex.split(self.checked([
            self.llvm / "llvm-config", "--ldflags", "--libs", "core", "passes", "support", "--system-libs",
        ]).stdout)
        executable = self.work / "separate-core-consumer"
        self.checked([self.llvm / "clang++", *compiler_flags, "-std=c++17", "-I", self.include,
                      FIXTURES / "core-consumer.cpp", core, *linker_flags, "-o", executable])
        result = self.checked([executable])
        self.assertIn("one rewrite; second pass unchanged; invalid caps rejected", result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--llvm-bin", required=True)
    parser.add_argument("--include", required=True)
    parser.add_argument("--core")
    OPTIONS, unittest_arguments = parser.parse_known_args()
    unittest.main(argv=[__file__, *unittest_arguments], verbosity=2)
