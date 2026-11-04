#!/usr/bin/env python3
"""Bounded one-operation semantic recognizer; this is not Xyntia or msynth."""

import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/re"))
import simba

PROTOCOL = {
    "name": "IRVeil bounded one-operation semantic recognizer",
    "grammar": {
        "terminals": ["p0", "p1", "0", "1", "2", "f(0,0) modulo 2^width"],
        "unaryOperatorsInOrder": ["~", "-"],
        "binaryOperatorsInOrder": ["+", "-", "*", "&", "|", "^"],
        "maximumOperators": 1,
        "maximumCandidates": 234,
        "order": "terminals, unary operator/terminal, binary operator/left/right; deduplicate terminals",
    },
    "widths": [32, 64],
    "training": "Cartesian product of eight fixed edge values, then 32 PRNG pairs",
    "holdout": "Next 32 PRNG pairs; never used for candidate selection",
    "prng": "Python random.Random, seed 0x49525645 + width",
    "seed": 0x49525645,
    "samplingArithmetic": "Unsigned bitvectors; every intermediate reduced modulo 2^width",
    "selection": "First candidate matching training outputs; fixed before holdout and SMT verification",
    "equivalence": "Z3 asserts extracted input != learned; only UNSAT establishes exact equivalence",
    "sourceComparison": "Only after a learned expression passes holdout and input equivalence; modular coefficient comparison",
    "workerInput": "expression, width, profile only; no function identity or source operation",
    "limits": {"workerSeconds": 5, "workerAddressSpaceMiB": 512,
               "workerCPUSeconds": 5, "proofMilliseconds": 2000,
               "workerOutputBytes": 65536},
    "z3Version": simba.Z3_VERSION,
    "statuses": ["recovered", "not_recovered", "unsupported", "timeout", "error"],
    "scope": "A small fixed grammar for this corpus, not a general-purpose synthesizer. Sampling alone is not recovery. No universal RE-resistance inference follows.",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def sample_points(width):
    mask = (1 << width) - 1
    sign = 1 << (width - 1)
    edges = [0, 1, 2, sign - 1, sign, mask - 1, mask,
             0xAAAAAAAA55555555 & mask]
    generator = random.Random(PROTOCOL["seed"] + width)
    training = [(a, b) for a in edges for b in edges]
    training += [(generator.getrandbits(width), generator.getrandbits(width))
                 for _ in range(32)]
    holdout = [(generator.getrandbits(width), generator.getrandbits(width))
               for _ in range(32)]
    return training, holdout


OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.BitAnd: lambda a, b: a & b,
    ast.BitOr: lambda a, b: a | b,
    ast.BitXor: lambda a, b: a ^ b,
}


def evaluate(node, a, b, mask):
    if isinstance(node, ast.Constant):
        return node.value & mask
    if isinstance(node, ast.Name):
        return a if node.id == "p0" else b
    if isinstance(node, ast.UnaryOp):
        value = evaluate(node.operand, a, b, mask)
        return (~value if isinstance(node.op, ast.Invert) else -value) & mask
    left = evaluate(node.left, a, b, mask)
    right = evaluate(node.right, a, b, mask)
    return OPERATORS[type(node.op)](left, right) & mask


def learn(request):
    import z3
    if z3.get_version_string() != PROTOCOL["z3Version"]:
        raise ValueError("Expected Z3 " + PROTOCOL["z3Version"])
    width, expression, profile = request["width"], request["expression"], request["profile"]
    if width not in PROTOCOL["widths"] or profile not in simba.PROFILES:
        return {"status": "unsupported", "reason": "width/profile outside protocol"}
    try:
        tree = simba.parse_expression(expression, profile)
    except ValueError as error:
        return {"status": "unsupported", "reason": str(error)}
    if any(isinstance(node, ast.Name) and node.id not in {"p0", "p1"}
           for node in ast.walk(tree)):
        return {"status": "unsupported", "reason": "recognizer accepts at most p0 and p1"}
    mask = (1 << width) - 1
    training, holdout = sample_points(width)
    observed = [evaluate(tree, a, b, mask) for a, b in training]
    zero = evaluate(tree, 0, 0, mask)
    terminals = list(dict.fromkeys(["p0", "p1", "0", "1", "2", str(zero)]))
    terminal_vectors = {terminal: ([a for a, b in training] if terminal == "p0" else
                                  [b for a, b in training] if terminal == "p1" else
                                  [int(terminal)] * len(training))
                        for terminal in terminals}

    def candidates():
        for terminal in terminals:
            yield terminal, terminal_vectors[terminal]
        for operator in ["~", "-"]:
            for terminal in terminals:
                values = terminal_vectors[terminal]
                yield operator + "(" + terminal + ")", [
                    (~value if operator == "~" else -value) & mask for value in values]
        for operator, operation in zip(["+", "-", "*", "&", "|", "^"], OPERATORS.values()):
            for left in terminals:
                for right in terminals:
                    yield "(" + left + operator + right + ")", [
                        operation(a, b) & mask for a, b in
                        zip(terminal_vectors[left], terminal_vectors[right])]

    facts = {"derivedConstant": zero, "terminals": terminals,
             "trainingCount": len(training), "holdoutCount": len(holdout),
             "trainingInputsSha256": digest(training),
             "holdoutInputsSha256": digest(holdout),
             "trainingOutputsSha256": digest(observed)}
    checked = 0
    learned = None
    for candidate, outputs in candidates():
        checked += 1
        if outputs == observed:
            learned = candidate
            break
    facts["candidatesChecked"] = checked
    if learned is None:
        return {**facts, "status": "not_recovered", "reason": "no candidate matched training"}
    facts["learned"] = learned
    candidate_tree = simba.parse_expression(learned, profile)
    holdout_passed = all(evaluate(tree, a, b, mask) == evaluate(candidate_tree, a, b, mask)
                         for a, b in holdout)
    facts["holdoutPassed"] = holdout_passed
    if not holdout_passed:
        return {**facts, "status": "not_recovered", "reason": "chosen candidate failed holdout"}
    equivalence = simba.prove(expression, learned, width, z3, profile)
    facts["inputEquivalent"] = equivalence
    if equivalence == "unknown":
        return {**facts, "status": "timeout", "reason": "Z3 input equivalence exceeded 2000 ms or returned unknown"}
    if equivalence == "sat":
        return {**facts, "status": "not_recovered", "reason": "SMT refuted learned candidate"}
    return {**facts, "status": "recovered"}


def worker():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536,) * 2)
    try:
        outcome = learn(json.loads(sys.stdin.read(1024 * 1024)))
    except BaseException as error:
        outcome = {"status": "error", "reason": type(error).__name__ + ": " + str(error)}
    print(json.dumps(outcome))


def recognize(record, profile):
    if "expression" not in record:
        status = record.get("status")
        if status not in {"unsupported", "timeout", "error"}:
            status = "error"
        return {"id": record["id"], "status": status,
                "stage": "extraction", "reason": record.get("reason", "no expression")}
    request = {"expression": record["expression"], "width": record["width"], "profile": profile}
    started = time.monotonic()
    try:
        process = subprocess.run([sys.executable, "-B", __file__, "--worker"],
                                 input=json.dumps(request), capture_output=True, text=True,
                                 timeout=5)
        if len(process.stdout.encode()) > 65536 or len(process.stderr.encode()) > 65536:
            outcome = {"status": "error", "reason": "worker output bound"}
        elif process.returncode == -getattr(signal, "SIGXCPU", 24):
            outcome = {"status": "timeout", "reason": "worker CPU limit"}
        elif process.returncode:
            outcome = {"status": "error", "reason": "worker exit " + str(process.returncode),
                       "stderr": process.stderr[-2000:]}
        else:
            outcome = json.loads(process.stdout)
            if outcome.get("status") not in PROTOCOL["statuses"]:
                raise ValueError("invalid worker status")
    except subprocess.TimeoutExpired:
        outcome = {"status": "timeout", "reason": "worker exceeded 5 seconds"}
    except (ValueError, TypeError, AttributeError):
        outcome = {"status": "error", "reason": "invalid worker response"}
    # The worker never receives this lookup or the function identity.
    if outcome["status"] == "recovered":
        expected_width, expected = simba.SOURCE_OPERATIONS[record["id"]]
        if expected_width != record["width"]:
            outcome = {**outcome, "status": "error", "reason": "source/extracted width mismatch after learning"}
        else:
            learned = simba.linear_arithmetic(simba.parse_expression(outcome["learned"], profile), expected_width)
            source = simba.linear_arithmetic(simba.parse_expression(expected, profile), expected_width)
            outcome.update(sourceOperation=expected, sourceCanonicalMatch=learned == source)
            if learned is None or learned != source:
                outcome.update(status="not_recovered", reason="verified result did not match source canonical operation")
    return {"id": record["id"], "width": record["width"],
            "inputExpressionSha256": hashlib.sha256(record["expression"].encode()).hexdigest(),
            "stage": "recognizer", **outcome, "workerSeconds": time.monotonic() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True,
                        help="label=path to simba.json; labels normal,v0.2.0,composed,prefix")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output must not exist")
    if ROOT in output.parents and ROOT / "work" not in output.parents:
        parser.error("generated evidence inside repository must be under work/")
    sources = []
    for argument in args.input:
        label, filename = argument.split("=", 1)
        if label not in {"normal", "v0.2.0", "composed", "prefix"}:
            parser.error("unknown input label")
        path = Path(filename).resolve()
        if path.stat().st_size > 8 * 1024 * 1024:
            parser.error("input report size bound")
        report = json.loads(path.read_text())
        profile = report.get("profile", "primary")
        if report.get("status") != "completed" or profile not in simba.PROFILES:
            parser.error("expected completed SiMBA report with known profile")
        if report.get("fixtureSha256") != sha256(simba.evaluate.CORPUS):
            parser.error("source fixture hash differs from the evaluated corpus")
        sources.append((label, path, report, profile))
    protocol = {**PROTOCOL, "inputs": [{"label": label, "path": str(path), "sha256": sha256(path),
                                        "profile": profile, "fixtureSha256": report["fixtureSha256"]}
                                       for label, path, report, profile in sources],
                "evaluatorSha256": sha256(__file__), "pythonVersion": sys.version,
                "sampleHashes": {str(width): {"training": digest(sample_points(width)[0]),
                                              "holdout": digest(sample_points(width)[1])}
                                 for width in PROTOCOL["widths"]}}
    output.parent.mkdir(parents=True, exist_ok=True)
    protocol_path = output.with_suffix(".protocol.json")
    with protocol_path.open("x") as stream:
        json.dump(protocol, stream, indent=2)
        stream.write("\n")
    result = {"schemaVersion": 1, "status": "completed", "protocol": protocol,
              "protocolSha256": sha256(protocol_path), "cases": []}
    for label, path, report, profile in sources:
        variant = label if label in {"normal", "v0.2.0"} else "candidate"
        cases = [case for case in report["cases"] if case["variant"] == variant]
        if len(cases) != 2 or {case["optimization"] for case in cases} != {"O2", "O3"}:
            parser.error("expected O2 and O3 cases for " + label)
        for case in cases:
            records = case["functions"]
            if len(records) != 8 or {record["id"] for record in records} != set(simba.evaluate.FUNCTIONS):
                parser.error("expected eight unique corpus functions")
            records = [recognize(record, profile) for record in case["functions"]]
            result["cases"].append({"variant": label, "optimization": case["optimization"],
                                    "profile": profile, "binarySha256": case["binarySha256"],
                                    "functions": records, "counts": dict(Counter(record["status"] for record in records))})
    if any(record["status"] in {"error", "timeout"} for case in result["cases"] for record in case["functions"]):
        result["status"] = "incomplete"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "cases": [
        {key: case[key] for key in ("variant", "optimization", "profile", "counts")}
        for case in result["cases"]]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        raise SystemExit(main())
