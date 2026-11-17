#!/usr/bin/env python3
"""Exercise the installed compiler component as an independent CMake user."""

import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
OPTIONS = None


def execute(arguments, **kwargs):
    return subprocess.run(list(map(str, arguments)), capture_output=True,
                          text=True, timeout=120, check=False, **kwargs)


class CompilerPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="irveil-compiler-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.cmake = Path(OPTIONS.cmake).resolve()
        cls.llvm = Path(OPTIONS.llvm_bin).resolve()
        installed = cls.work / "original prefix"
        result = execute([cls.cmake, "--install", Path(OPTIONS.build_dir).resolve(),
                          "--prefix", installed, "--config", OPTIONS.configuration])
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.prefix = cls.work / "relocated prefix"
        installed.rename(cls.prefix)

    def checked(self, arguments, **kwargs):
        result = execute(arguments, **kwargs)
        self.assertEqual(result.returncode, 0,
                         f"{arguments}\n{result.stdout}\n{result.stderr}")
        return result

    def configure(self, source, build, *extra):
        return execute([
            self.cmake, "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_PREFIX_PATH={self.prefix}",
            f"-DCMAKE_C_COMPILER={self.llvm / 'clang'}",
            f"-DCMAKE_CXX_COMPILER={self.llvm / 'clang++'}",
            "-DCMAKE_DISABLE_FIND_PACKAGE_LLVM=TRUE",
            "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE",
            "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE", *extra])

    def require_configured(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def disassemble(self, binary, function):
        text = self.checked([self.llvm / "llvm-objdump", "-d", "--no-show-raw-insn",
                             f"--disassemble-symbols={function}", binary]).stdout
        instructions = re.findall(r"^\s*[0-9a-f]+:\s+(.+)$", text, re.MULTILINE)
        self.assertTrue(instructions, text)
        return instructions

    def test_two_targets_native_ir_configuration_and_isolation(self):
        source = self.work / "application source"
        shutil.copytree(ROOT / "examples/cmake-consumer", source)
        build = self.work / "application build"
        self.require_configured(self.configure(
            source, build, "-DENABLE_IRVEIL=OFF", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"))
        self.checked([self.cmake, "--build", build, "--parallel", "2"])
        commands_before = json.loads((build / "compile_commands.json").read_text())
        symbols = ["protected_calculation", "ordinary_calculation"]
        before = {symbol: self.disassemble(build / "protected-app", symbol) for symbol in symbols}
        ordinary_before = {symbol: self.disassemble(build / "ordinary-app", symbol) for symbol in symbols}
        inputs = [[], ["0", "0"], ["4294967295", "1"], ["2147483648", "4294967295"]]
        expected = [self.checked([build / "ordinary-app", *args]).stdout for args in inputs]
        for args, output in zip(inputs, expected):
            self.assertEqual(self.checked([build / "protected-app", *args]).stdout, output)

        self.require_configured(self.configure(
            source, build, "-DENABLE_IRVEIL=ON", "-DIRVEIL_SEED=42", "-DIRVEIL_MAX_ADDS=1"))
        built = self.checked([self.cmake, "--build", build, "--parallel", "2"])
        self.assertIn("seed=42 max-adds=1 selected=1 changed=1 rewritten-adds=1",
                      built.stdout + built.stderr)
        commands = json.loads((build / "compile_commands.json").read_text())
        for command, previous in zip(commands, commands_before):
            enabled = "protected-app.dir" in command["command"]
            self.assertEqual("-fpass-plugin=" in command["command"], enabled)
            self.assertEqual("-irveil-seed=42" in command["command"], enabled)
            if not enabled:
                self.assertEqual(command, previous)
        for target in ["ordinary-app", "protected-app"]:
            for args, output in zip(inputs, expected):
                self.assertEqual(self.checked([build / target, *args]).stdout, output)
        self.assertNotEqual(before["protected_calculation"],
                            self.disassemble(build / "protected-app", "protected_calculation"))
        self.assertEqual(before["ordinary_calculation"],
                         self.disassemble(build / "protected-app", "ordinary_calculation"))
        for symbol in symbols:
            self.assertEqual(ordinary_before[symbol], self.disassemble(build / "ordinary-app", symbol))

        # Replay the target's compile flags with IR emission in place of codegen.
        # Clang's -save-temps bitcode precedes this optimizer-last pass.
        command = next(x for x in commands if "protected-app.dir" in x["command"])
        arguments = shlex.split(command["command"])
        output_index = arguments.index("-o")
        del arguments[output_index:output_index + 2]
        arguments.remove("-c")
        ir = self.checked([*arguments, "-S", "-emit-llvm", "-o", "-"],
                          cwd=command["directory"]).stdout
        self.assertIn('"irveil.processed"', ir)
        body = re.search(r"^define[^\n]*@protected_calculation\([^\n]*\)[^{]*\{(.*?)^\}",
                         ir, re.MULTILINE | re.DOTALL).group(1)
        self.assertEqual(len(re.findall(r"\bfreeze i32\b", body)), 2)
        for target in ["ordinary-app", "protected-app"]:
            link = (build / f"CMakeFiles/{target}.dir/link.txt").read_text()
            self.assertNotIn("IRVeilCore", link)
            self.assertNotIn("LLVM", link)

        # The report is also an observable contract of the compile command,
        # independent of CMake's argument construction and native optimizations.
        self.assertIn("-irveil-max-adds=1", arguments)
        self.assertIn("-irveil-seed=42", arguments)

    def test_invalid_cmake_configuration_and_target_contract(self):
        source = self.work / "configuration source"
        source.mkdir()
        (source / "main.cpp").write_text("int main() { return 0; }\n")
        cases = [
            ("SEED -1", "SEED"), ("SEED 18446744073709551616", "18446744073709551615"),
            ("MAX_ADDS 0", "1 and 4096"), ("MAX_ADDS 4097", "4096"),
            ("MAX_ADDS", "requires a value"), ("UNKNOWN 4", "unknown argument"),
            ("SEED 1 SEED 2", "more than once"), ("REPORT REPORT", "more than once"),
            ("SEED 0x10", "decimal"), ("MAX_ADDS 1.5", "decimal"),
            ("PROFILE universal", "PROFILE"), ("PROFILE", "requires a value"),
            ("TRANSFORMS adds+adds", "TRANSFORMS"), ("TRANSFORMS adds+", "TRANSFORMS"),
            ("TRANSFORMS unknown", "TRANSFORMS"), ("MAX_EDGES 257", "256"),
            ("MAX_SWITCH_CASES 0", "between 1"), ("MAX_CONSTANTS 4097", "4096"),
            ("MAX_STRING_BYTES 65537", "65536"),
            ("MAX_STRING_LOADS 0", "between 1"), ("MAX_STRING_LOADS 65537", "65536"),
            ("MAX_FLATTEN_BLOCKS 0", "between 1"), ("MAX_FLATTEN_BLOCKS 65", "64"),
            ("MAX_FLATTEN_INSTRUCTIONS 4097", "4096"),
        ]
        preamble = ("cmake_minimum_required(VERSION 3.20)\nproject(Consumer LANGUAGES CXX)\n"
                    "find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)\n"
                    "add_executable(app main.cpp)\n")
        for index, (arguments, diagnostic) in enumerate(cases):
            with self.subTest(arguments=arguments):
                (source / "CMakeLists.txt").write_text(preamble + f"irveil_protect_target(app {arguments})\n")
                rejected = self.configure(source, self.work / f"invalid-{index}")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("IRVeil", rejected.stderr)
                self.assertIn(diagnostic, rejected.stderr)
        for index, (setup, call, diagnostic) in enumerate([
                ("", "missing", "does not exist"),
                ("add_library(headers INTERFACE)", "headers", "local executable"),
                ("add_executable(alias ALIAS app)", "alias", "local executable"),
                ("set_property(TARGET app PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)", "app", "LTO"),
                ("irveil_protect_target(app)", "app", "already configured")]):
            with self.subTest(setup=setup):
                (source / "CMakeLists.txt").write_text(
                    preamble + setup + "\n" + f"irveil_protect_target({call})\n")
                rejected = self.configure(source, self.work / f"target-{index}")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(diagnostic, rejected.stderr)

    def test_c_only_consumer_and_uint64_seed_boundary(self):
        source = self.work / "C source"
        source.mkdir()
        (source / "main.c").write_text(
            '#include <irveil/Protect.h>\nIRVEIL_PROTECT unsigned sum(unsigned a, unsigned b) { return a+b; }\n'
            'int main(void) { return sum(4294967295u, 1) != 0; }\n')
        (source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(Consumer LANGUAGES C)\n"
            "find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)\nadd_executable(app main.c)\n"
            "irveil_protect_target(app SEED 00018446744073709551615 MAX_ADDS 0004096 REPORT)\n")
        build = self.work / "C build"
        self.require_configured(self.configure(source, build))
        result = self.checked([self.cmake, "--build", build, "--parallel", "2"])
        self.assertIn("seed=18446744073709551615 max-adds=4096", result.stdout + result.stderr)
        self.checked([build / "app"])

    def test_modular_profile_and_family_limits_in_installed_helper(self):
        source = self.work / "modular source"
        source.mkdir()
        (source / "main.cpp").write_text(
            '#include <irveil/Protect.h>\n'
            'IRVEIL_PROTECT unsigned f(unsigned a) { return a - 17; }\n'
            'int main() { return f(20) != 3; }\n')
        (source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(Consumer LANGUAGES CXX)\n"
            "find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)\nadd_executable(app main.cpp)\n"
            "irveil_protect_target(app PROFILE general TRANSFORMS sub+constants "
            "MAX_EDGES 1 MAX_SWITCH_CASES 2 MAX_CONSTANTS 3 MAX_STRING_BYTES 4 MAX_STRING_LOADS 5 REPORT)\n")
        build = self.work / "modular build"
        self.require_configured(self.configure(source, build, "-DCMAKE_BUILD_TYPE=Release"))
        result = self.checked([self.cmake, "--build", build, "--parallel", "2"])
        self.assertIn("transforms=258", result.stdout + result.stderr)
        self.assertRegex(result.stdout + result.stderr, r"constants=[1-9]")
        self.assertIn("max-string-loads=5", result.stdout + result.stderr)
        self.checked([build / "app"])

    def test_helper_isolates_parser_state_and_rejects_cmake_list_separators(self):
        source = self.work / "parser isolation source"
        source.mkdir()
        (source / "main.cpp").write_text("int main() { return 0; }\n")
        preamble = (
            "cmake_minimum_required(VERSION 3.20)\nproject(Consumer LANGUAGES CXX)\n"
            "find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)\n"
            "add_executable(app main.cpp)\n")
        inherited = ("PROFILE", "TRANSFORMS", "MAX_EDGES", "MAX_SWITCH_CASES",
                     "MAX_CONSTANTS", "MAX_STRING_BYTES", "MAX_STRING_LOADS",
                     "MAX_FLATTEN_BLOCKS", "MAX_FLATTEN_INSTRUCTIONS")
        (source / "CMakeLists.txt").write_text(preamble +
            "".join(f"set(seen_{option} TRUE)\n" for option in inherited) +
            "irveil_protect_target(app PROFILE general TRANSFORMS cfg+loops "
            "MAX_EDGES 1 MAX_SWITCH_CASES 1 MAX_CONSTANTS 1 MAX_STRING_BYTES 1 MAX_STRING_LOADS 1 "
            "MAX_FLATTEN_BLOCKS 16 MAX_FLATTEN_INSTRUCTIONS 256)\n")
        with self.subTest(inherited=True):
            self.require_configured(self.configure(source, self.work / "inherited parser build"))
        for index, text in enumerate(["adds;cfg", ";adds", "adds;", "adds+;cfg"]):
            with self.subTest(text=text):
                (source / "CMakeLists.txt").write_text(preamble +
                    f'irveil_protect_target(app TRANSFORMS "{text}")\n')
                rejected = self.configure(source, self.work / f"list separator-{index}")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("TRANSFORMS", rejected.stderr)

    def test_flatten_installed_helper_and_preflight_skip(self):
        source = self.work / "flatten source"
        source.mkdir()
        (source / "main.cpp").write_text('''
#include <irveil/Protect.h>
IRVEIL_PROTECT unsigned f(unsigned x, volatile unsigned *p) {
  if (x & 1) { *p = x; *p += 1; } else *p = x + 2;
  return *p;
}
int main() { unsigned cell = 0; return f(3, &cell) != 4 || f(2, &cell) != 4 || cell != 4; }
''')
        for cap in [1, 256]:
            (source / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(Consumer LANGUAGES CXX)\n"
                "find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)\nadd_executable(app main.cpp)\n"
                f"irveil_protect_target(app TRANSFORMS flatten MAX_FLATTEN_BLOCKS 16 "
                f"MAX_FLATTEN_INSTRUCTIONS {cap} REPORT)\n")
            build = self.work / f"flatten build-{cap}"
            self.require_configured(self.configure(source, build))
            result = self.checked([self.cmake, "--build", build, "--parallel", "2"])
            self.assertIn(f"max-flatten-instructions={cap}", result.stdout + result.stderr)
            self.assertIn(f"flattened={int(cap > 1)}", result.stdout + result.stderr)
            self.checked([build / "app"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--cmake", required=True)
    parser.add_argument("--llvm-bin", required=True)
    parser.add_argument("--configuration", default="Release")
    OPTIONS, arguments = parser.parse_known_args()
    unittest.main(argv=[__file__, *arguments], verbosity=2)
