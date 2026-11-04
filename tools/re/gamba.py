#!/usr/bin/env python3
"""Apply a pinned general-MBA attack to the exact expressions of a SiMBA report."""
import argparse
import ast
from collections import Counter
import contextlib
import io
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

import evaluate
import simba

GAMBA_COMMIT = "96691c0f1c7fd1be66bd11a6f2b60ce6865ce68c"
NUMPY_VERSION = "1.26.4"


def validate_input_record(record, profile):
    if record.get("status") not in {"recovered", "not_recovered", "unsupported"}:
        raise ValueError("invalid completed SiMBA function status")
    if "expression" not in record:
        if record["status"] != "unsupported" or not record.get("reason"):
            raise ValueError("non-extracted input cannot claim recovery")
        return
    if type(record.get("width")) is not int or record["width"] not in {32, 64}:
        raise ValueError("invalid SiMBA input width")
    simba.parse_expression(record["expression"], profile)


def normalize_output(expression, width, profile="primary"):
    limits = simba.PROFILES[profile]
    if len(expression.encode()) > limits["expressionBytes"]:
        raise ValueError("GAMBA output bound")
    count = 0

    def emit(node, depth=0):
        nonlocal count
        count += 1
        if count > limits["parserNodes"] or depth > 64:
            raise ValueError("GAMBA output node/depth bound")
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Pow, ast.LShift)):
            if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
                raise ValueError("nonconstant GAMBA exponent/shift")
            number = node.right.value
            base = emit(node.left, depth + 1)
            if isinstance(node.op, ast.LShift):
                if not 0 <= number < width:
                    raise ValueError("GAMBA shift bound")
                return "(" + base + "*" + str(1 << number) + ")"
            if not 0 <= number <= 64:
                raise ValueError("GAMBA exponent bound")
            return "(" + "*".join([base] * number) + ")" if number else "1"
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return str(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.UnaryOp) and type(node.op) in {ast.USub, ast.Invert}:
            return "(" + ("-" if isinstance(node.op, ast.USub) else "~") + emit(node.operand, depth + 1) + ")"
        operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return "(" + emit(node.left, depth + 1) + operators[type(node.op)] + emit(node.right, depth + 1) + ")"
        raise ValueError("unsupported GAMBA output grammar")
    normalized = emit(ast.parse(expression, mode="eval").body)
    simba.parse_expression(normalized, profile)
    return normalized


def simplify_record(record, gamba_root, profile="primary"):
    import z3
    import numpy
    if z3.get_version_string() != simba.Z3_VERSION or numpy.__version__ != NUMPY_VERSION:
        raise ValueError("Expected Z3 4.13.3 and NumPy 1.26.4")
    width, expected = simba.SOURCE_OPERATIONS[record["id"]]
    if width != record["width"]:
        raise ValueError("source/extracted width mismatch")
    expression = record["expression"]
    simba.parse_expression(expression, profile)
    sys.path.insert(0, str(Path(gamba_root) / "src"))
    from simplify_general import GeneralSimplifier
    roots = {}
    with contextlib.redirect_stdout(io.StringIO()):
        # This is the pinned public wrapper's exact core operation. Our worker
        # already provides isolation and limits, without spawning grandchildren.
        GeneralSimplifier(width)._simplify(expression, roots)
    simplified = roots[0].to_string()
    normalized = normalize_output(simplified, width, profile)
    same_input = simba.prove(expression, normalized, width, z3, profile)
    same_source = simba.prove(normalized, expected, width, z3, profile)
    facts = {"simplified": simplified, "normalizedResult": normalized,
             "sourceOperation": expected, "inputEquivalent": same_input, "sourceEquivalent": same_source}
    if "unknown" in (same_input, same_source):
        return {**facts, "status": "timeout", "reason": "bounded Z3 query returned unknown"}
    if same_input != "unsat" or same_source != "unsat":
        return {**facts, "status": "error", "reason": "semantic counterexample"}
    recovered = simba.linear_arithmetic(simba.parse_expression(normalized, profile), width) == simba.linear_arithmetic(simba.parse_expression(expected, profile), width)
    return {**facts, "status": "recovered" if recovered else "not_recovered"}


def worker():
    import resource
    sys.dont_write_bytecode = True
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536,) * 2)
    try:
        request = json.loads(sys.stdin.read(1048576))
        outcome = simplify_record(request["record"], request["gambaRoot"], request.get("profile", "primary"))
    except BaseException as error:
        outcome = {"status": "error", "reason": type(error).__name__ + ": " + str(error)}
    print(json.dumps(outcome))


def run_record(record, gamba_root, profile="primary"):
    if "expression" not in record or record["id"] not in simba.SOURCE_OPERATIONS:
        return dict(record)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, "-B", __file__, "--worker"], text=True, capture_output=True,
                                input=json.dumps({"record": record, "gambaRoot": str(gamba_root), "profile": profile}),
                                timeout=5, env=environment)
        if len(result.stdout) > 65536 or len(result.stderr) > 65536:
            outcome = {"status": "error", "reason": "worker output bound"}
        elif result.returncode == -getattr(signal, "SIGXCPU", 24):
            outcome = {"status": "timeout", "reason": "GAMBA worker CPU limit (SIGXCPU)"}
        elif result.returncode:
            outcome = {"status": "error", "reason": "worker exit " + str(result.returncode), "stderr": result.stderr[-2000:]}
        else:
            outcome = json.loads(result.stdout)
            if outcome.get("status") not in {"recovered", "not_recovered", "unsupported", "timeout", "error"}:
                raise ValueError("invalid worker status")
    except subprocess.TimeoutExpired:
        outcome = {"status": "timeout", "reason": "GAMBA worker exceeded 5 seconds"}
    except (ValueError, AttributeError):
        outcome = {"status": "error", "reason": "invalid worker response"}
    # Preserve SiMBA's result separately; proofs below belong to this attack.
    extracted = {k: record[k] for k in ("id", "expression", "width", "nativeInstructions", "nativeBytes") if k in record}
    return {**extracted, "simbaStatus": record["status"], **outcome, "workerSeconds": time.monotonic() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="completed simba.json")
    parser.add_argument("--gamba-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.input, args.gamba_root, args.output = args.input.resolve(), args.gamba_root.resolve(), args.output.resolve()
    if args.input.stat().st_size > 8 * 1024 * 1024:
        parser.error("input report bound")
    if evaluate.ROOT in args.output.parents and evaluate.ROOT / "work" not in args.output.parents:
        parser.error("generated evidence inside repository must be under work/")
    if args.output.exists():
        parser.error("output must not exist")
    source = json.loads(args.input.read_text())
    if source.get("status") != "completed" or len(source.get("cases", [])) > 6:
        parser.error("expected a completed, bounded SiMBA evaluation")
    actual = subprocess.run(["git", "-C", str(args.gamba_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    if actual != GAMBA_COMMIT:
        parser.error("GAMBA commit must be " + GAMBA_COMMIT)
    if subprocess.run(["git", "-C", str(args.gamba_root), "status", "--porcelain", "--untracked-files=no"], check=True, capture_output=True, text=True, timeout=5).stdout.strip():
        parser.error("GAMBA tracked files must be clean")
    profile = source.get("profile", "primary")
    if profile not in simba.PROFILES:
        parser.error("unknown source extraction profile")
    result = {"schemaVersion": 1, "profile": profile, "pythonVersion": platform.python_version(),
              "status": "completed", "attack": "GAMBA", "commit": GAMBA_COMMIT,
              "numpyVersion": NUMPY_VERSION, "z3Version": simba.Z3_VERSION,
              "inputSha256": evaluate.sha256(args.input), "evaluatorSha256": evaluate.sha256(__file__),
              "sharedEvaluatorSha256": evaluate.sha256(simba.__file__),
              "limits": source["limits"], "cases": []}
    for case in source["cases"]:
        if len(case["functions"]) != 8 or {f.get("id") for f in case["functions"]} != set(evaluate.FUNCTIONS):
            parser.error("expected eight function records per case")
        for record in case["functions"]:
            validate_input_record(record, profile)
        records = [run_record(record, args.gamba_root, profile) for record in case["functions"]]
        result["cases"].append({"optimization": case["optimization"], "variant": case["variant"],
                                "binarySha256": case["binarySha256"], "functions": records,
                                "counts": dict(Counter(record["status"] for record in records))})
    if any(record["status"] in {"error", "timeout"} for case in result["cases"] for record in case["functions"]):
        result["status"] = "incomplete"
    if (evaluate.sha256(__file__) != result["evaluatorSha256"] or evaluate.sha256(args.input) != result["inputSha256"] or
            evaluate.sha256(simba.__file__) != result["sharedEvaluatorSha256"]):
        result["status"] = "incomplete"
        result["error"] = "evaluator or input report changed during evaluation"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evaluate.write_json(args.output, result)
    print(json.dumps({"status": result["status"], "cases": [{k: c[k] for k in ("optimization", "variant", "counts")} for c in result["cases"]]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        raise SystemExit(main())
