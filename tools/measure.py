#!/usr/bin/env python3
"""Measure an owned fixture; results do not quantify RE resistance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time


def run(argv):
    return subprocess.run([str(arg) for arg in argv], check=True, text=True,
                          capture_output=True, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', type=Path, required=True)
    parser.add_argument('--llvm-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=10_000_000)
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1_000_000_000 or not 3 <= args.samples <= 25:
        parser.error('iterations must be 1..1000000000; samples must be 3..25')

    repo = Path(__file__).resolve().parents[1]
    scratch = repo / 'work'
    scratch.mkdir(exist_ok=True)
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    compiler = args.llvm_bin / 'clang++'
    strip = args.llvm_bin / 'llvm-strip'
    objdump = args.llvm_bin / 'llvm-objdump'
    build_seconds = {}
    observations = {}
    plugin = args.plugin.resolve()
    with tempfile.TemporaryDirectory(prefix='measure-', dir=scratch) as directory:
        target = Path(directory)
        executables = {}
        for name, extra in [('baseline', []), ('irveil', [f'-fpass-plugin={plugin}'])]:
            executable = target / name
            command = [compiler, '-std=c++17', '-O2', '-g0', '-I', repo / 'include',
                       *extra, repo / 'examples/demo.cpp', '-o', executable]
            started = time.perf_counter()
            run(command)
            build_seconds[name] = time.perf_counter() - started
            disassembly = run([objdump, '--no-show-raw-insn',
                               '--disassemble-symbols=irveil_demo_step', executable]).stdout
            instructions = len(re.findall(r'^\s*[0-9a-f]+:\s+\S+', disassembly, re.MULTILINE))
            if instructions == 0:
                raise RuntimeError('Selected fixture symbol was not found in disassembly')
            stripped = target / f'{name}-stripped'
            shutil.copyfile(executable, stripped)
            run([strip, '--strip-all', stripped])
            stripped.chmod(0o700)
            observations[name] = {
                'functionInstructions': instructions,
                'unstrippedBytes': executable.stat().st_size,
                'strippedBytes': stripped.stat().st_size,
                'strippedSha256': hashlib.sha256(stripped.read_bytes()).hexdigest(),
                'runtimeSeconds': [],
            }
            executables[name] = stripped

        expected = None
        for sample in range(args.samples + 1):
            order = ['baseline', 'irveil'] if sample % 2 == 0 else ['irveil', 'baseline']
            for name in order:
                started = time.perf_counter()
                output = run([executables[name], str(args.iterations)]).stdout.strip()
                elapsed = time.perf_counter() - started
                if expected is None:
                    expected = output
                if output != expected:
                    raise RuntimeError('Baseline and transformed outputs differ')
                if sample > 0:
                    observations[name]['runtimeSeconds'].append(elapsed)

    for name, observation in observations.items():
        observation['runtimeMedianSeconds'] = statistics.median(observation['runtimeSeconds'])
        observation['oneBuildSeconds'] = build_seconds[name]
    report = {
        'compiler': run([compiler, '--version']).stdout.splitlines()[0],
        'platform': platform.platform(),
        'machine': platform.machine(),
        'cpuCount': os.cpu_count(),
        'flags': ['-std=c++17', '-O2', '-g0'],
        'fixtureSha256': hashlib.sha256((repo / 'examples/demo.cpp').read_bytes()).hexdigest(),
        'pluginSha256': hashlib.sha256(plugin.read_bytes()).hexdigest(),
        'iterations': args.iterations,
        'samples': args.samples,
        'warmupSamples': 1,
        'order': 'Alternating paired runs; first pair omitted from timings.',
        'checksum': expected,
        'observations': observations,
        'scope': 'One synthetic owned fixture on this host. Instruction count is not a measure of RE resistance. Runtime includes process startup; filesystem caches were not cleared; host load is uncontrolled. Disassembly counts the unstripped symbol; execution uses copies stripped identically with llvm-strip --strip-all.',
    }
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
