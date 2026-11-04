#!/usr/bin/env python3
"""Evaluate pure return expressions extracted from native Ghidra high P-code."""

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


SIMBA_COMMIT = "228179970f5906ed763afb33fc8649de2846696e"
RELEASE_REPORT_SHA256 = "08b7574822fa441ddce6c4a2b50d75b2502123b0511d29dc0fd3bf1f68d9189f"
Z3_VERSION = "4.13.3"
WORKER_SECONDS = 5
MAX_EXPRESSION_BYTES = 16384
PROFILES = {"primary": {"expressionBytes": 16384, "sliceNodes": 512, "parserNodes": 1024},
            "expanded": {"expressionBytes": 131072, "sliceNodes": 4096, "parserNodes": 8192}}
SOURCE_OPERATIONS = {
    "re_sum32": (32, "p0+p1"), "re_sum64": (64, "p0+p1"),
    "re_constant32": (32, "p0+17"), "re_identical64": (64, "2*p0"),
    "re_zero32": (32, "p0"), "re_unselected64": (64, "p0+p1"),
}


def parse_expression(expression, profile="primary"):
    limits = PROFILES[profile]
    if not isinstance(expression, str) or len(expression.encode()) > limits["expressionBytes"]:
        raise ValueError("expression byte bound")
    try:
        tree = ast.parse(expression, mode="eval").body
    except SyntaxError as error:
        raise ValueError("invalid expression syntax") from error
    count = 0

    def check(node, depth=0):
        nonlocal count
        count += 1
        if count > limits["parserNodes"] or depth > 64:
            raise ValueError("expression node/depth bound")
        if isinstance(node, ast.Constant) and type(node.value) is int and 0 <= node.value < 2**128:
            return
        if isinstance(node, ast.Name) and node.id in {"p0", "p1", "p2", "p3"}:
            return
        if isinstance(node, ast.BinOp) and type(node.op) in {ast.Add, ast.Sub, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor}:
            check(node.left, depth + 1); check(node.right, depth + 1)
            return
        if isinstance(node, ast.UnaryOp) and type(node.op) in {ast.Invert, ast.USub}:
            check(node.operand, depth + 1)
            return
        raise ValueError("unsupported expression grammar")
    check(tree)
    return tree


def to_bitvector(node, width, z3):
    if isinstance(node, ast.Constant):
        return z3.BitVecVal(node.value, width)
    if isinstance(node, ast.Name):
        return z3.BitVec(node.id, width)
    if isinstance(node, ast.UnaryOp):
        value = to_bitvector(node.operand, width, z3)
        return ~value if isinstance(node.op, ast.Invert) else -value
    left = to_bitvector(node.left, width, z3)
    right = to_bitvector(node.right, width, z3)
    operations = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                  ast.Mult: lambda: left * right, ast.BitAnd: lambda: left & right,
                  ast.BitOr: lambda: left | right, ast.BitXor: lambda: left ^ right}
    return operations[type(node.op)]()


def linear_arithmetic(node, width):
    """Canonical coefficients only after SiMBA has removed all bitwise operators."""
    modulus = 1 << width
    if isinstance(node, ast.Constant):
        return {"constant": node.value % modulus}
    if isinstance(node, ast.Name):
        return {node.id: 1}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = linear_arithmetic(node.operand, width)
        return None if value is None else {k: -v % modulus for k, v in value.items() if v}
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        return None
    left, right = linear_arithmetic(node.left, width), linear_arithmetic(node.right, width)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Mult):
        if set(right) <= {"constant"}:
            result = {k: v * right.get("constant", 0) % modulus for k, v in left.items()}
        elif set(left) <= {"constant"}:
            result = {k: v * left.get("constant", 0) % modulus for k, v in right.items()}
        else:
            return None
    else:
        result = dict(left)
        sign = -1 if isinstance(node.op, ast.Sub) else 1
        for key, value in right.items():
            result[key] = (result.get(key, 0) + sign * value) % modulus
    return {k: v for k, v in result.items() if v}


def prove(left, right, width, z3, profile="primary"):
    solver = z3.Solver()
    solver.set(timeout=2000)
    solver.add(to_bitvector(parse_expression(left, profile), width, z3) !=
               to_bitvector(parse_expression(right, profile), width, z3))
    result = solver.check()
    return str(result)


def simplify_record(record, simba_root, profile="primary"):
    import z3
    if z3.get_version_string() != Z3_VERSION:
        raise ValueError("Expected z3-solver 4.13.3.0 (Z3 " + Z3_VERSION + ")")
    width, expected = SOURCE_OPERATIONS[record["id"]]
    expression = record["expression"]
    parse_expression(expression, profile)
    if record["width"] != width:
        raise ValueError("extracted/source width mismatch")
    sys.path.insert(0, str(Path(simba_root) / "src"))
    from check_linear_mba import check_linear_mba
    from simplify import simplify_linear_mba
    if not check_linear_mba(expression):
        return {"status": "unsupported", "reason": "SiMBA linearity checker rejected extracted expression"}
    # SiMBA's own optional verifier has no solver timeout. Run without it and
    # perform the two separately labelled, bounded bitvector proofs below.
    with contextlib.redirect_stdout(io.StringIO()):
        simplified = simplify_linear_mba(expression, width, False, True)
    parse_expression(simplified, profile)
    same_input = prove(expression, simplified, width, z3, profile)
    same_source = prove(simplified, expected, width, z3, profile)
    facts = {"simplified": simplified, "sourceOperation": expected,
             "inputEquivalent": same_input, "sourceEquivalent": same_source}
    if "unknown" in (same_input, same_source):
        return {**facts, "status": "timeout", "reason": "Z3 returned unknown within 2000 ms proof limit"}
    if same_input != "unsat" or same_source != "unsat":
        return {**facts, "status": "error", "reason": "semantic proof found a counterexample"}
    recovered = linear_arithmetic(parse_expression(simplified, profile), width) == linear_arithmetic(parse_expression(expected, profile), width)
    return {**facts, "status": "recovered" if recovered else "not_recovered"}


def worker():
    import resource
    sys.dont_write_bytecode = True
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (WORKER_SECONDS, WORKER_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536,) * 2)
    try:
        request = json.loads(sys.stdin.read(1048576))
        result = simplify_record(request["record"], request["simbaRoot"], request.get("profile", "primary"))
    except BaseException as error:
        result = {"status": "error", "reason": type(error).__name__ + ": " + str(error)}
    print(json.dumps(result))


def run_simba(record, simba_root, profile="primary"):
    if record["status"] != "extracted":
        return dict(record)
    if record["id"] not in SOURCE_OPERATIONS:
        return {**record, "status": "unsupported", "reason": "no predefined straight-line source operation"}
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, __file__, "--worker"],
                                input=json.dumps({"record": record, "simbaRoot": str(simba_root), "profile": profile}),
                                text=True, capture_output=True, timeout=WORKER_SECONDS)
        if len(result.stdout) > 65536 or len(result.stderr) > 65536:
            outcome = {"status": "error", "reason": "worker output bound"}
        elif result.returncode == -getattr(signal, "SIGXCPU", 24):
            outcome = {"status": "timeout", "reason": "SiMBA worker CPU limit (SIGXCPU)"}
        elif result.returncode != 0:
            outcome = {"status": "error", "reason": "worker exit " + str(result.returncode), "stderr": result.stderr[-2000:]}
        else:
            try:
                outcome = json.loads(result.stdout)
                if outcome.get("status") not in {"recovered", "not_recovered", "unsupported", "timeout", "error"}:
                    raise ValueError("unknown worker status")
            except (ValueError, AttributeError):
                outcome = {"status": "error", "reason": "invalid worker response"}
    except subprocess.TimeoutExpired:
        outcome = {"status": "timeout", "reason": "SiMBA worker exceeded 5 seconds"}
    return {**record, **outcome, "workerSeconds": time.monotonic() - started}


def failed_export_records(manifest, error, timed_out):
    return [{"id": function["id"], "status": "timeout" if timed_out else "error",
             "stage": "ghidra_export", "reason": str(error)} for function in manifest["functions"]]


def validate_expression_export(report, manifest, profile):
    if report.get("schemaVersion") != 1 or report.get("status") not in {"completed", "timeout"}:
        raise ValueError("invalid expression export schema/status")
    if report.get("ghidraVersion") != "12.2" or not report.get("javaVersion", "").startswith("25."):
        raise ValueError("Expected Ghidra 12.2 and JDK 25")
    heap, cpus = report.get("jvmMaxHeapBytes"), report.get("availableProcessors")
    if type(heap) is not int or not 0 < heap <= 1073741824 or type(cpus) is not int or not 1 <= cpus <= 2:
        raise ValueError("unverified Ghidra heap/CPU limits")
    if type(report.get("analysisTimedOut")) is not bool:
        raise ValueError("missing auto-analysis timeout fact")
    if report.get("binarySha256") != manifest["binarySha256"]:
        raise ValueError("export binary hash mismatch")
    if report.get("profile") != profile:
        raise ValueError("export profile mismatch")
    functions = report.get("functions", [])
    if len(functions) != len(evaluate.FUNCTIONS) or {f["id"] for f in functions} != set(evaluate.FUNCTIONS):
        raise ValueError("exported function set mismatch")
    if report.get("analysisTimedOut") is True and any(f.get("status") != "timeout" for f in functions):
        raise ValueError("auto-analysis timeout lacks explicit function timeout records")
    for function in functions:
        status = function.get("status")
        if status not in {"extracted", "unsupported", "timeout", "error"}:
            raise ValueError("invalid extractor function status")
        if status != "extracted":
            if not isinstance(function.get("reason"), str) or not function["reason"]:
                raise ValueError("missing extractor failure reason")
            continue
        if type(function.get("width")) is not int or function["width"] not in {32, 64}:
            raise ValueError("invalid extracted width")
        parse_expression(function.get("expression"), profile)
        if type(function.get("sliceNodes")) is not int or not 1 <= function["sliceNodes"] <= PROFILES[profile]["sliceNodes"]:
            raise ValueError("invalid slice node fact")
        parameters = function.get("parameters")
        if not isinstance(parameters, list) or len(parameters) > 4 or any(type(p) is not int or not 0 <= p <= 3 for p in parameters):
            raise ValueError("invalid extracted parameters")
        for field in ("nativeInstructions", "nativeBytes"):
            if type(function.get(field)) is not int or function[field] < 1:
                raise ValueError("invalid native metric " + field)
    return report


def export(args, commands, binary, manifest, directory):
    directory.mkdir()
    project = directory / "projects"
    project.mkdir()
    home = directory / "runtime-home"
    home.mkdir()
    requested = directory / "functions.json"
    evaluate.write_json(requested, manifest)
    output = directory / "expressions.json"
    environment = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        environment.pop(key, None)
    environment["JAVA_HOME"] = str(args.java_home)
    environment["PATH"] = str(args.java_home / "bin") + os.pathsep + environment.get("PATH", "")
    environment["_JAVA_OPTIONS"] = '-Xmx1024m -XX:ActiveProcessorCount=2 -Duser.home="' + str(home) + '"'
    commands.run([args.ghidra_home / "support/analyzeHeadless", project, "owned-expressions",
                  "-import", binary, "-scriptPath", Path(__file__).parent, "-postScript", "ExportExpressions.java",
                  requested, output, args.profile, "-analysisTimeoutPerFile", "120", "-max-cpu", "2", "-deleteProject"],
                 directory.name + "-ghidra", timeout=405, env=environment)
    if not output.is_file() or output.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("missing/oversized expression export")
    return validate_expression_export(json.loads(output.read_text()), manifest, args.profile)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-dir", type=Path, required=True, help="extracted v0.2.0-re-evidence.zip")
    parser.add_argument("--candidate-plugin", type=Path)
    parser.add_argument("--simba-root", type=Path, required=True)
    parser.add_argument("--ghidra-home", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--llvm-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="primary")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This protocol targets Linux x86-64")
    if not args.output.is_absolute():
        parser.error("--output must be absolute")
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    if evaluate.ROOT in args.output.parents and evaluate.ROOT / "work" not in args.output.parents:
        parser.error("Generated evidence in the repository must be below work/")
    return args


def main():
    args = arguments()
    args.output.mkdir(parents=True, exist_ok=False)
    commands = evaluate.Commands(args.output)
    result = {"schemaVersion": 1, "profile": args.profile, "pythonVersion": platform.python_version(),
              "status": "incomplete", "cases": [], "commands": commands.records,
              "simbaCommit": SIMBA_COMMIT, "z3Version": Z3_VERSION,
              "limits": {"workerSeconds": WORKER_SECONDS, "workerAddressSpaceMiB": 512,
                         "proofMilliseconds": 2000, **PROFILES[args.profile],
                         "sliceDepth": 64, "parameters": 4,
                         "widths": [32, 64], "ghidraHeapMiB": 1024, "ghidraCPUs": 2}}
    try:
        actual = commands.run(["git", "-C", args.simba_root, "rev-parse", "HEAD"], "simba-commit").strip()
        if actual != SIMBA_COMMIT:
            raise ValueError("SiMBA checkout must be " + SIMBA_COMMIT)
        if commands.run(["git", "-C", args.simba_root, "status", "--porcelain", "--untracked-files=no"], "simba-status").strip():
            raise ValueError("SiMBA tracked files must be clean")
        if commands.run([args.llvm_bin / "llvm-config", "--version"], "llvm-version").strip() != "18.1.3":
            raise ValueError("Expected LLVM 18.1.3")
        historical_report = args.historical_dir / "irveil-v0.2.0-re-evaluation.json"
        if evaluate.sha256(historical_report) != RELEASE_REPORT_SHA256:
            raise ValueError("Historical report differs from v0.2.0 release asset")
        published = json.loads(historical_report.read_text())
        result["historicalReportSha256"] = RELEASE_REPORT_SHA256
        result["fixtureSha256"] = evaluate.sha256(evaluate.CORPUS)
        if result["fixtureSha256"] != published["fixtureSha256"]:
            raise ValueError("current fixture differs from historical source")
        result["exporterSha256"] = evaluate.sha256(Path(__file__).with_name("ExportExpressions.java"))
        result["evaluatorSha256"] = evaluate.sha256(__file__)
        result["buildHelperSha256"] = evaluate.sha256(evaluate.__file__)
        result["candidatePluginSha256"] = evaluate.sha256(args.candidate_plugin) if args.candidate_plugin else None
        for optimization in ("O2", "O3"):
            expected_behavior = None
            variants = [("normal", "normal"), ("v0.2.0", "candidate")]
            if args.candidate_plugin:
                variants.append(("candidate", None))
            for variant, published_variant in variants:
                name = optimization + "-" + variant
                print("Ghidra/SiMBA " + name, file=sys.stderr, flush=True)
                if published_variant:
                    source = args.historical_dir / (optimization + "-" + published_variant)
                    binary = source / "corpus.stripped"
                    manifest = json.loads((source / "functions.json").read_text())
                    published_case = next(c for c in published["cases"] if c["optimization"] == optimization and c["variant"] == published_variant)
                    if evaluate.sha256(binary) != published_case["strippedSha256"] or manifest["binarySha256"] != published_case["strippedSha256"]:
                        raise ValueError("historical binary hash differs from release report")
                    if manifest["functions"] != published_case["manifest"]["functions"]:
                        raise ValueError("historical function manifest differs from release report")
                    binary.chmod(0o700)
                    behavior = commands.run([binary], name + "-behavior", output_limit=1048576)
                    if len(behavior.splitlines()) != 633:
                        raise ValueError("historical native behavior corpus incomplete")
                else:
                    built, behavior = evaluate.build_case(args, commands, optimization, variant, args.candidate_plugin, args.output / (name + "-build"))
                    binary = Path(built["stripped"])
                    manifest = built["manifest"]
                if expected_behavior is None:
                    expected_behavior = behavior
                elif expected_behavior != behavior:
                    raise ValueError("native behavior mismatch " + name)
                try:
                    exported = export(args, commands, binary, manifest, args.output / name)
                    records = [run_simba(record, args.simba_root, args.profile) for record in exported["functions"]]
                except (RuntimeError, ValueError) as error:
                    timed_out = bool(commands.records and commands.records[-1].get("failure") == "deadline exceeded")
                    records = failed_export_records(manifest, error, timed_out)
                result["cases"].append({"optimization": optimization, "variant": variant,
                                        "binarySha256": manifest["binarySha256"], "behaviorRows": 633,
                                        "functions": records, "counts": dict(Counter(r["status"] for r in records))})
        if args.candidate_plugin and evaluate.sha256(args.candidate_plugin) != result["candidatePluginSha256"]:
            raise ValueError("candidate plugin changed during evaluation")
        if evaluate.sha256(evaluate.CORPUS) != result["fixtureSha256"]:
            raise ValueError("source fixture changed during evaluation")
        if commands.run(["git", "-C", args.simba_root, "status", "--porcelain", "--untracked-files=no"], "simba-final-status").strip():
            raise ValueError("SiMBA tracked files changed during evaluation")
        if (evaluate.sha256(__file__) != result["evaluatorSha256"] or
                evaluate.sha256(Path(__file__).with_name("ExportExpressions.java")) != result["exporterSha256"] or
                evaluate.sha256(evaluate.__file__) != result["buildHelperSha256"]):
            raise ValueError("evaluator/exporter source changed during evaluation")
        result["status"] = "completed"
        if any(r["status"] in {"error", "timeout"} for case in result["cases"] for r in case["functions"]):
            result["status"] = "incomplete"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    evaluate.write_json(args.output / "simba.json", result)
    print(json.dumps({"status": result["status"], "cases": [{k: c[k] for k in ("optimization", "variant", "counts")} for c in result["cases"]], "error": result.get("error")}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        raise SystemExit(main())
