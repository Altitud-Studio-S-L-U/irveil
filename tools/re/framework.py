#!/usr/bin/env python3
"""Evaluate the experimental framework on an owned corpus, separate from v0.2 evidence."""
import argparse
import json
from pathlib import Path
import platform
import re
import sys

from evaluate import (Commands, ROOT, build_case, compare_control, export_case,
                      sha256, write_json)

CORPUS = ROOT / "tests/fixtures/framework-corpus.cpp"
FUNCTIONS = ("re_cfg32", "re_loop32", "re_switch32", "re_constant64", "re_string8",
             "re_shared_string8", "re_unselected32", "re_bool32")
TRANSFORMS = "adds+sub+bitwise+cmp+branches+cfg+loops+switch+constants+strings"


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["plugin", "llvm-bin", "ghidra-home", "java-home", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This protocol targets Linux x86-64")
    if not args.output.is_absolute():
        parser.error("--output must be absolute")
    for name, value in vars(args).items():
        setattr(args, name, value.resolve())
    if (args.output == ROOT or ROOT in args.output.parents) and not ROOT / "work" in args.output.parents:
        parser.error("Generated evidence inside the repository must be under work/")
    args.analysis_timeout = 120
    args.decomp_timeout = 30
    return args


def main(argv=None):
    args = arguments(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    result = {"schemaVersion": 1, "status": "incomplete", "cases": [], "controls": [],
              "pluginSha256": sha256(args.plugin), "fixtureSha256": sha256(CORPUS),
              "orchestratorSha256": sha256(__file__),
              "exporterSha256": sha256(Path(__file__).with_name("ExportDecompilation.java")),
              "commands": commands.records, "cpuAffinity": commands.affinity}
    try:
        result["llvmVersion"] = commands.run([args.llvm_bin / "llvm-config", "--version"], "llvm-version").strip()
        if result["llvmVersion"] != "18.1.3":
            raise ValueError("Expected LLVM 18.1.3")
        result["compiler"] = commands.run([args.llvm_bin / "clang++", "--version"], "compiler-version")
        for optimization in ["O2", "O3"]:
            built = []
            expected = None
            for variant, settings in [("normal", None), ("general", ["-irveil-profile=general"]),
                                      ("framework", ["-irveil-transforms=" + TRANSFORMS])]:
                print(f"build/execute {optimization}/{variant}", file=sys.stderr, flush=True)
                flags = []
                if settings is not None:
                    flags = ["-Xclang", "-load", "-Xclang", str(args.plugin)]
                    for setting in [*settings, "-irveil-seed=42", "-irveil-report"]:
                        flags.extend(["-mllvm", setting])
                case, behavior = build_case(args, commands, optimization, variant,
                    args.plugin if settings else None, args.output / f"{optimization}-{variant}",
                    source=CORPUS, names=FUNCTIONS, extra_flags=flags)
                if expected is None: expected = behavior
                elif expected != behavior: raise ValueError("Native behavior mismatch: " + variant)
                if settings:
                    log = (args.output / "logs" / f"{optimization}-{variant}-compile.log").read_text()
                    case["irCounters"] = {key: int(value) for key, value in
                        re.findall(r"([a-z][a-z-]*)=(\d+)", log)}
                result["cases"].append(case)
                built.append(case)
            for case in built:
                name = f"{optimization}-{case['variant']}"
                print("Ghidra " + name, file=sys.stderr, flush=True)
                case["analysis"] = export_case(args, commands, case, name, Path(case["directory"]) / "ghidra")
            print("Ghidra repeated control " + optimization, file=sys.stderr, flush=True)
            repeated = export_case(args, commands, built[0], optimization + "-repeat", args.output / (optimization + "-repeat"))
            result["controls"].append({"optimization": optimization,
                **compare_control(built[0]["analysis"]["functions"], repeated["functions"], FUNCTIONS),
                "repeatAnalysis": repeated})
        if sha256(args.plugin) != result["pluginSha256"] or sha256(CORPUS) != result["fixtureSha256"]:
            raise ValueError("Inputs changed during evaluation")
        result["status"] = "completed"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    result["methodology"] = {
        "inputs": "Owned synthetic framework corpus, 633 boundary/random rows of eight results; symbol companions and stripped copies must all agree.",
        "analysis": "Ghidra 12.2/JDK 25, default analysis, fresh projects; max heap 1 GiB, two CPUs with OS affinity; known function entries from each companion, no supplied prototypes.",
        "controls": "Normal binary analyzed twice per optimization; normalized C and metrics must match. Shared/escaping string and unselected function are negative controls.",
        "limits": "Optimizer-last placement; operations optimized away before the pass are absent, recorded counters describe IR work only. Counts and decompiler text are not a resistance score. Inspect pseudocode and compiler simplifications; no human analyst timing or whole-program claim.",
    }
    write_json(args.output / "evaluation.json", result)
    print(json.dumps({key: result[key] for key in ["status", "pluginSha256"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
