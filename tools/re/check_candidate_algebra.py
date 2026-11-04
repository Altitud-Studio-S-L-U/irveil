#!/usr/bin/env python3
"""Bitvector obligations for the two experimental candidates, not LLVM proofs."""

import argparse
import json
from pathlib import Path
import sys


def expression(a, b, width, candidate, alternative):
    if candidate == "composed":
        u, v = a ^ b, (a & b) << 1
        return ((u | v) << 1) - (u ^ v) if alternative else (u ^ v) + ((u & v) << 1)
    propagate = (a | b) if alternative else (a ^ b)
    generate = a & b
    shift = 1
    while shift < width:
        generate = generate | (propagate & (generate << shift))
        if shift * 2 < width:
            propagate = propagate & (propagate << shift)
        shift *= 2
    return (a ^ b) ^ (generate << 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("composed", "prefix"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if root in output.parents and root / "work" not in output.parents:
        parser.error("generated evidence inside the repository must be under work/")
    if output.exists():
        parser.error("output must not exist")
    import z3
    if z3.get_version_string() != "4.13.3":
        parser.error("this protocol requires Z3 4.13.3 (z3-solver 4.13.3.0)")
    report = {"candidate": args.candidate, "z3Version": z3.get_version_string(),
              "pythonVersion": sys.version, "timeoutMillisecondsPerQuery": 10000,
              "obligation": "candidate(a,b) != a+b modulo 2^width",
              "scope": "Pure bitvectors; freeze/undef/poison/flags need the separate LLVM argument and tests",
              "cases": []}
    for width in range(2, 65):
        a, b = z3.BitVecs("a b", width)
        for alternative in (False, True):
            solver = z3.Solver()
            solver.set(timeout=10000)
            solver.add(expression(a, b, width, args.candidate, alternative) != a + b)
            status = str(solver.check())
            report["cases"].append({"width": width, "alternative": alternative, "result": status})
    passed = all(case["result"] == "unsat" for case in report["cases"])
    report["status"] = "proved" if passed else "incomplete_or_refuted"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(f"{args.candidate}: {report['status']}; {len(report['cases'])} queries")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
