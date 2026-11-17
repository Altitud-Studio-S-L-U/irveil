#!/usr/bin/env python3
"""Bounded flattening: semantic controls, native survival, cost and Ghidra evidence."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import signal
import statistics
import subprocess
import sys
import time

from evaluate import (Commands, ROOT, build_case, compare_control, export_case,
                      sha256, write_json)

CORPUS = ROOT / "tests/fixtures/flatten-corpus.cpp"
FUNCTIONS = ("re_flat_branch32", "re_flat_loop32", "re_flat_phi64", "re_flat_memory32",
             "re_flat_recursive32", "re_flat_switch32", "re_flat_straight64", "re_flat_unselected32")


def ir_facts(text, names=FUNCTIONS):
    attributes = dict(re.findall(r"^attributes #(\d+) = \{([^\n]*)\}", text, re.MULTILINE))
    result = {}
    for name in names:
        match = re.search(r"^define[^\n]*@" + re.escape(name) +
                          r"\([^\n]*\)([^{]*)\{(.*?)^\}", text, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError("IR function missing: " + name)
        group = re.search(r"#(\d+)", match[1])
        attrs = attributes.get(group[1], "") if group else ""
        body = match[2]
        # Clang normally discards SSA names. An attribute records past work;
        # only the actual body can establish that a dispatcher still exists.
        phis = set(re.findall(r"(%[-.\w]+) = phi i32\b", body))
        switches = re.findall(r"\bswitch i32 (%[-.\w]+),", body)
        result[name] = {"flattenedAttribute": '"irveil.flattened"' in attrs,
                        "i32PhiSwitches": sum(value in phis for value in switches),
                        "switchInstructions": len(re.findall(r"\bswitch i\d+ ", body)),
                        "allocaInstructions": len(re.findall(r" = alloca ", body))}
    return result


def native_facts(disassembly, functions):
    result = {}
    for spec in functions:
        name = spec["id"]
        address, size = int(spec["address"], 16), spec["size"]
        if not 1 <= size <= 65536: raise ValueError("Native symbol size out of bounds")
        match = re.search(r"^([0-9a-f]+) <" + re.escape(name) + r">:\n(.*?)(?=^[0-9a-f]+ <|\Z)",
                          disassembly, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError("Disassembly function missing: " + name)
        if int(match[1], 16) != address: raise ValueError("Disassembly address differs from companion")
        lines = [(int(at, 16), opcode + operands) for at, opcode, operands in re.findall(
            r"^[ \t]*([0-9a-f]+):[ \t]+([a-z][a-z0-9]*)([^\n]*)", match[2], re.MULTILINE)
                 if address <= int(at, 16) < address + size]
        if not lines or lines[0][0] != address: raise ValueError("Native symbol instructions missing")
        backward = 0
        for at, text in lines:
            target = re.search(r"\bj\w*\s+0x([0-9a-f]+)", text)
            if target: backward += int(target[1], 16) < at
        body = "\n".join(text for _, text in lines)
        # Ghidra may miss indirect-jump targets or exclude alignment bytes. Cost
        # uses the entire ELF symbol, including in-symbol padding, independently.
        result[name] = {"symbolBytes": size, "symbolInstructions": len(lines),
                        "indirectJumps": len(re.findall(r"\bjmpq?\s+\*", body)),
                        "backwardBranches": backward}
    return result


def decompiler_limits(text):
    return {"unrecoveredJumpTable": bool(re.search(r"Could not recover jumptable|Treating indirect jump as call", text)),
            "voidReturnInNonVoidCorpus": bool(re.search(r"^void \w+\(", text, re.MULTILINE))}


def precise_run(commands, argv, label):
    """Owned fixed processes; communicate wakes at EOF, without polling quantization."""
    record = {"argv": list(map(str, argv)), "timeoutSeconds": 120, "measurement": True}
    commands.records.append(record)
    def restrict():
        os.sched_setaffinity(0, set(commands.affinity))
    started = time.perf_counter()
    process = subprocess.Popen(record["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, preexec_fn=restrict)
    try:
        stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError(label + ": measurement deadline exceeded")
    elapsed = time.perf_counter() - started
    record.update(exitCode=process.returncode, elapsedSeconds=elapsed)
    if len(stdout) + len(stderr) > 1048576:
        raise RuntimeError(label + ": measurement output exceeds 1 MiB")
    destination = commands.output / "logs" / (label + ".log")
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(stdout + b"\n--- stderr ---\n" + stderr)
    record["log"] = str(destination.relative_to(commands.output))
    if process.returncode:
        raise RuntimeError(label + ": process failed; see " + record["log"])
    return stdout.decode("utf-8"), elapsed


def measure(args, commands, optimization, cases):
    selected = {case["variant"]: case for case in cases}
    compile_samples = {name: [] for name in ["normal", "flatten"]}
    runtime_samples = {name: [] for name in selected}
    directory = args.output / (optimization + "-cost")
    directory.mkdir()
    expected = None
    for sample in range(args.samples + 1):
        order = ["normal", "flatten"] if sample % 2 == 0 else ["flatten", "normal"]
        for name in order:
            destination = directory / (name + ".symbols")
            _, elapsed = precise_run(commands, [args.llvm_bin / "clang++",
                *selected[name]["flags"], CORPUS, "-o", destination], f"{optimization}-{name}-compile-sample-{sample}")
            if sha256(destination) != selected[name]["binarySha256"]:
                raise ValueError("Timed compilation changed native artifact: " + name)
            if sample: compile_samples[name].append(elapsed)
        names = list(selected)
        if sample % 2: names.reverse()
        for name in names:
            output, elapsed = precise_run(commands, [selected[name]["stripped"], "--bench", str(args.iterations)],
                f"{optimization}-{name}-runtime-sample-{sample}")
            if not re.fullmatch(r"[0-9a-f]{16}\n", output):
                raise ValueError("Invalid benchmark checksum")
            if expected is None: expected = output
            elif output != expected: raise ValueError("Benchmark behavior mismatch: " + name)
            if sample: runtime_samples[name].append(elapsed)
    return {"iterations": args.iterations, "samples": args.samples, "warmupRunsPerVariant": 1,
            "checksum": expected.strip(), "compileSeconds": compile_samples,
            "runtimeSeconds": runtime_samples,
            "compileMedianSeconds": {name: statistics.median(values) for name, values in compile_samples.items()},
            "runtimeMedianSeconds": {name: statistics.median(values) for name, values in runtime_samples.items()}}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    paths = ["plugin", "llvm-bin", "ghidra-home", "java-home", "output"]
    for name in paths: parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1000000)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args(argv)
    if platform.system() != "Linux" or platform.machine() != "x86_64": parser.error("Linux x86-64 required")
    if not 1 <= args.iterations <= 100000000 or not 3 <= args.samples <= 15: parser.error("Invalid measurement bounds")
    if not args.output.is_absolute(): parser.error("--output must be absolute")
    for name in paths:
        key = name.replace("-", "_")
        setattr(args, key, getattr(args, key).resolve())
    if (args.output == ROOT or ROOT in args.output.parents) and ROOT / "work" not in args.output.parents:
        parser.error("Generated evidence inside the repository must be under work/")
    args.analysis_timeout = 120
    args.decomp_timeout = 30
    return args


def main(argv=None):
    args = arguments(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    inputs = {"plugin": args.plugin, "fixture": CORPUS, "orchestrator": Path(__file__),
              "sharedHarness": Path(__file__).with_name("evaluate.py"),
              "exporter": Path(__file__).with_name("ExportDecompilation.java")}
    fingerprints = {key: sha256(path) for key, path in inputs.items()}
    result = {"schemaVersion": 1, "status": "incomplete", "hashes": fingerprints, "cases": [],
              "controls": [], "measurements": {}, "commands": commands.records,
              "platform": platform.platform(), "cpuAffinity": commands.affinity}
    try:
        if CORPUS.stat().st_size > 524288: raise ValueError("Corpus exceeds 512 KiB")
        result["llvmVersion"] = commands.run([args.llvm_bin / "llvm-config", "--version"], "llvm-version").strip()
        if result["llvmVersion"] != "18.1.3": raise ValueError("Expected LLVM 18.1.3")
        result["compiler"] = commands.run([args.llvm_bin / "clang++", "--version"], "compiler-version")
        for optimization in ["O2", "O3"]:
            built = []
            ir_directory = args.output / (optimization + "-ir")
            ir_directory.mkdir()
            expected = None
            for variant in ["normal", "flatten", "reoptimized"]:
                flags = []
                plugin = None
                source = CORPUS
                ir = ir_directory / (variant + ".ll")
                if variant == "flatten":
                    plugin = args.plugin
                    flags = ["-Xclang", "-load", "-Xclang", str(args.plugin), "-mllvm", "-irveil-transforms=flatten",
                             "-mllvm", "-irveil-seed=42", "-mllvm", "-irveil-report"]
                if variant == "reoptimized":
                    commands.run([args.llvm_bin / "opt", f"-passes=default<{optimization}>", "-verify-each", "-S",
                        ir_directory / "flatten.ll", "-o", ir], optimization + "-reoptimize")
                    source = ir
                    flags = ["-Xclang", "-disable-llvm-passes"]
                else:
                    commands.run([args.llvm_bin / "clang++", "-std=c++17", "-" + optimization, "-g0", "-fno-pie",
                        "-I", ROOT / "include", *flags, *([f"-fpass-plugin={plugin}"] if plugin else []),
                        "-S", "-emit-llvm", source, "-o", ir], f"{optimization}-{variant}-ir")
                commands.run([args.llvm_bin / "opt", "-passes=verify", "-disable-output", ir], f"{optimization}-{variant}-verify")
                print(f"build/execute {optimization}/{variant}", file=sys.stderr, flush=True)
                case, behavior = build_case(args, commands, optimization, variant, plugin,
                    args.output / f"{optimization}-{variant}", source=source, names=FUNCTIONS, extra_flags=flags)
                if expected is None: expected = behavior
                elif expected != behavior: raise ValueError("Native behavior mismatch: " + variant)
                case["ir"] = {"path": str(ir), "sha256": sha256(ir), "functions": ir_facts(ir.read_text())}
                case["nativeDispatchEvidence"] = native_facts(
                    (Path(case["directory"]) / "disassembly.txt").read_text(), case["manifest"]["functions"])
                if plugin:
                    log = (args.output / "logs" / f"{optimization}-{variant}-compile.log").read_text()
                    case["irCounters"] = {key: int(value) for key, value in re.findall(r"([a-z][a-z-]*)=(\d+)", log)}
                    if not case["irCounters"].get("flattened", 0): raise ValueError("No flattening work in positive corpus")
                built.append(case)
                result["cases"].append(case)
            print("measure " + optimization, file=sys.stderr, flush=True)
            result["measurements"][optimization] = measure(args, commands, optimization, built)
            for case in built:
                name = f"{optimization}-{case['variant']}"
                print("Ghidra " + name, file=sys.stderr, flush=True)
                case["analysis"] = export_case(args, commands, case, name, Path(case["directory"]) / "ghidra")
                case["knownDecompilerLimits"] = {function: decompiler_limits(
                    (Path(case["directory"]) / "ghidra/decompiled" / (function + ".c")).read_text())
                    for function in FUNCTIONS}
            print("Ghidra repeated control " + optimization, file=sys.stderr, flush=True)
            repeated = export_case(args, commands, built[0], optimization + "-repeat", args.output / (optimization + "-repeat"))
            result["controls"].append({"optimization": optimization,
                **compare_control(built[0]["analysis"]["functions"], repeated["functions"], FUNCTIONS),
                "repeatAnalysis": repeated})
        if any(sha256(path) != fingerprints[key] for key, path in inputs.items()):
            raise ValueError("An evaluation input or tool source changed during the run")
        result["status"] = "completed"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    result["methodology"] = {
        "semantics": "633 boundary/random rows, eight function results and four memory cells; all symbol-bearing/stripped outputs agree before evidence is accepted. Benchmark checksums also agree.",
        "pipelines": "Normal and flatten are direct Clang O2/O3 builds. IR observations use separate same-option compilations. Reoptimized is opt default<O2/O3> applied to flattened IR, then Clang with IR passes disabled and the same backend optimization level.",
        "cost": "Fixed owned integer/volatile-cell workload; alternating normal/flatten compile pairs and alternating forward/reverse three-variant runtime orders; one warmup pair/order omitted, all raw measured samples retained. High-resolution process wall time includes startup, warm filesystem caches and uncontrolled host load; CPU affinity limited to two processors. Reoptimized compile cost is not compared to source compilation.",
        "survival": "An attribute is only a work marker. Record actual IR PHI-fed switches, native indirect/backward jumps and decompiled C/P-code; inspect whether a state dispatcher remains. Native cost counts the full companion ELF symbol, including in-symbol padding, independently of Ghidra's possibly partial function body. Explicitly flag unrecovered jump tables and void returns in this non-void corpus; exclude known-invalid C/P-code/block comparisons from difficulty claims. Neither a jump count nor visible switch is a resistance score.",
        "ghidra": "Ghidra 12.2/JDK 25, fresh projects, default analysis, heap 1 GiB, two CPUs with OS affinity, fixed 120s analysis/30s per-function limits. Each own companion grants known entries; no source prototypes. Repeat normal metrics/C must match. Incomplete/unsupported/error outcomes are not improvements.",
    }
    write_json(args.output / "evaluation.json", result)
    print(json.dumps({"status": result["status"], "pluginSha256": fingerprints["plugin"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
