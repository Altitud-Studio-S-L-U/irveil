#!/usr/bin/env python3
"""Check one bounded LLVM corpus; survival is not a measure of RE resistance."""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


WIDTHS = (2, 8, 32, 64)
SEEDS = tuple(range(16))
PIPELINES = {
    "instcombine": "function(instcombine)",
    "canonicalize": "function(instcombine,aggressive-instcombine,reassociate,instcombine,simplifycfg,dce)",
    "O2": "default<O2>",
    "O3": "default<O3>",
}


def execute(arguments, source=None):
    result = subprocess.run([str(argument) for argument in arguments], input=source,
                            text=True, capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"LLVM command failed ({result.returncode}): {result.stderr[-2000:]}")
    return result.stdout


def fixture():
    general = []
    controls = []
    functions = []
    for width in WIDTHS:
        for kind in ("unknown", "defined"):
            name = f"add{width}_{kind}"
            attribute = "noundef " if kind == "defined" else ""
            general.append(name)
            functions.append(f"define i{width} @{name}(i{width} {attribute}%a, i{width} {attribute}%b) {{\n"
                             f"  %sum = add i{width} %a, %b\n  ret i{width} %sum\n}}\n")
        for kind, right in (("zero", "0"), ("same", "%a")):
            name = f"control{width}_{kind}"
            controls.append(name)
            functions.append(f"define i{width} @{name}(i{width} noundef %a) {{\n"
                             f"  %sum = add i{width} %a, {right}\n  ret i{width} %sum\n}}\n")
    names = general + controls
    entries = ",\n".join("  { ptr, ptr, ptr, i32, ptr } { ptr @" + name +
                            ", ptr @.annotation, ptr @.source, i32 1, ptr null }" for name in names)
    source = ('source_filename = "irveil-canonicalization.ll"\n'
              'target triple = "x86_64-pc-linux-gnu"\n'
              '@.annotation = private constant [7 x i8] c"irveil\\00"\n'
              '@.source = private constant [1 x i8] zeroinitializer\n' +
              f'@llvm.global.annotations = appending global [{len(names)} x '
              '{ ptr, ptr, ptr, i32, ptr }] [\n' + entries + '\n], section "llvm.metadata"\n' +
              "\n".join(functions))
    return source, general, controls


def instructions(source, name):
    match = re.search(r"^define[^\n]*@" + re.escape(name) +
                      r"\([^\n]*\)[^{]*\{(.*?)^\}", source, re.MULTILINE | re.DOTALL)
    if not match:
        raise RuntimeError(f"Missing corpus function: {name}")
    return [line.split(";", 1)[0].strip() for line in match.group(1).splitlines()
            if line.split(";", 1)[0].strip()
            and not re.match(r"^\s*[\w.$-]+:", line)]


def opcodes(lines):
    return collections.Counter(re.match(r"(?:%[^=]+ = )?([a-z][a-z0-9.]*)\b", line).group(1)
                               for line in lines)


def normalized(lines):
    # The controls have identical operations even if LLVM chooses fresh SSA names.
    names = {"%a": "%arg0", "%b": "%arg1"}

    def rename(match):
        name = match.group(0)
        if name not in names:
            names[name] = f"%value{len(names)}"
        return names[name]

    return [re.sub(r"%[-a-zA-Z$._0-9]+", rename, line) for line in lines]


def inspect(llvm, plugin):
    version = execute([llvm / "llvm-config", "--version"]).strip()
    if not version.startswith("18."):
        raise RuntimeError(f"LLVM 18 required; found {version}")
    source, general, controls = fixture()
    baselines = {label: execute([llvm / "opt", f"-passes={pipeline}", "-verify-each", "-S", "-o", "-", "-"], source)
                 for label, pipeline in PIPELINES.items()}
    for label, baseline in baselines.items():
        for name in controls:
            expected = {"ret": 1} if name.endswith("_zero") else {"shl": 1, "ret": 1}
            if opcodes(instructions(baseline, name)) != expected:
                raise RuntimeError(f"Baseline control did not simplify: pipeline={label}, function={name}")
    summary = {label: {"generalCases": 0, "singleAddRestorations": 0,
                       "controlCases": 0, "controlMismatches": 0}
               for label in PIPELINES}
    restored = []
    mismatched = []
    identities = collections.Counter()
    for seed in SEEDS:
        protected = execute([llvm / "opt", "-load-pass-plugin", plugin,
                             f"-passes=irveil<seed={seed}>", "-verify-each", "-S", "-o", "-", "-"], source)
        for name in general:
            before = opcodes(instructions(protected, name))
            if before["freeze"] != 2 or sum(before[op] for op in ("and", "or", "xor")) < 2:
                raise RuntimeError(f"Corpus function was not transformed: seed={seed}, function={name}")
            identity = ("xor-carry" if before["and"] and before["xor"] else
                        "double-or-minus-xor" if before["sub"] else "or-and")
            identities[identity] += 1
        for label, pipeline in PIPELINES.items():
            transformed = execute([llvm / "opt", f"-passes={pipeline}", "-verify-each", "-S", "-o", "-", "-"], protected)
            for name in general:
                after = opcodes(instructions(transformed, name))
                summary[label]["generalCases"] += 1
                # Freezes are semantically relevant but do not conceal an add.
                if after["add"] == 1 and after["ret"] == 1 and set(after) <= {"freeze", "add", "ret"}:
                    summary[label]["singleAddRestorations"] += 1
                    restored.append({"seed": seed, "pipeline": label, "function": name})
            for name in controls:
                summary[label]["controlCases"] += 1
                if normalized(instructions(transformed, name)) != normalized(instructions(baselines[label], name)):
                    summary[label]["controlMismatches"] += 1
                    mismatched.append({"seed": seed, "pipeline": label, "function": name})
    return {
        "passed": not restored and not mismatched,
        "llvmVersion": version,
        "pluginSha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
        "fixtureSha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "seeds": list(SEEDS), "widths": list(WIDTHS),
        "operandKinds": ["unknown", "noundef"],
        "identities": dict(identities), "pipelines": PIPELINES,
        "results": summary, "restored": restored, "controlMismatches": mismatched,
        "scope": "Fixed synthetic general-input corpus and a+0/a+a controls. No universal optimizer-survival or RE-resistance claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-bin", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect(args.llvm_bin.resolve(), args.plugin.resolve())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Canonicalization check failed: {error}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
