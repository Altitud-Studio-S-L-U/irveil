#!/usr/bin/env python3
"""Install IRVeil and consume its exported CMake target outside the source tree."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
OPTIONS = None


class InstalledPackageTests(unittest.TestCase):
    def run_command(self, arguments):
        return subprocess.run([str(argument) for argument in arguments],
                              capture_output=True, text=True, timeout=120, check=False)

    def checked(self, arguments):
        result = self.run_command(arguments)
        self.assertEqual(result.returncode, 0,
                         f"Command failed: {arguments}\n{result.stdout}\n{result.stderr}")
        return result

    def test_installed_target_builds_and_runs_the_documented_consumer(self):
        cmake = Path(OPTIONS.cmake).resolve()
        llvm = Path(OPTIONS.llvm_bin).resolve()
        with tempfile.TemporaryDirectory(prefix="irveil-package-") as temporary:
            directory = Path(temporary)
            prefix = directory / "installed package"
            self.checked([cmake, "--install", Path(OPTIONS.build_dir).resolve(),
                          "--prefix", prefix, "--config", OPTIONS.configuration])
            relocated = directory / "relocated package"
            prefix.rename(relocated)
            source = directory / "consumer project"
            shutil.copytree(ROOT / "examples" / "library-consumer", source)
            build = directory / "consumer build"
            llvm_dir = self.checked([llvm / "llvm-config", "--cmakedir"]).stdout.strip()
            self.checked([cmake, "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
                          f"-DCMAKE_PREFIX_PATH={relocated}", f"-DLLVM_DIR={llvm_dir}",
                          f"-DCMAKE_C_COMPILER={llvm / 'clang'}",
                          f"-DCMAKE_CXX_COMPILER={llvm / 'clang++'}",
                          "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE",
                          "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE"])
            self.checked([cmake, "--build", build, "--parallel", "2"])
            consumer = build / "irveil-consumer"
            input_ir = directory / "demo.ll"
            self.checked([llvm / "clang++", "-std=c++17", "-O2", "-S", "-emit-llvm",
                          "-I", relocated / "include", ROOT / "examples" / "demo.cpp", "-o", input_ir])
            transformed = self.checked([consumer, input_ir])
            self.assertRegex(transformed.stderr, r"changed functions: [1-9][0-9]*")
            self.assertRegex(transformed.stderr, r"rewritten additions: [1-9][0-9]*")
            output_ir = directory / "transformed.ll"
            output_ir.write_text(transformed.stdout, encoding="utf-8")
            baseline = directory / "baseline"
            candidate = directory / "candidate"
            self.checked([llvm / "clang++", input_ir, "-o", baseline])
            self.checked([llvm / "clang++", output_ir, "-o", candidate])
            self.assertEqual(self.checked([baseline, "10000"]).stdout,
                             self.checked([candidate, "10000"]).stdout)

            malformed = directory / "malformed.ll"
            malformed.write_text("not an LLVM module\n", encoding="utf-8")
            for arguments in [[], [directory / "missing.ll"], [malformed]]:
                with self.subTest(arguments=arguments):
                    rejected = self.run_command([consumer, *arguments])
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertEqual(rejected.stdout, "")
                    self.assertTrue(rejected.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--cmake", required=True)
    parser.add_argument("--llvm-bin", required=True)
    parser.add_argument("--configuration", default="Release")
    OPTIONS, unittest_arguments = parser.parse_known_args()
    unittest.main(argv=[__file__, *unittest_arguments], verbosity=2)
