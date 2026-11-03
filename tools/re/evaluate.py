#!/usr/bin/env python3
"""Compare owned IRVeil fixtures using a pinned compiler and Ghidra headless."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/fixtures/re-corpus.cpp"
FUNCTIONS = ("re_sum32", "re_sum64", "re_constant32", "re_identical64", "re_zero32",
             "re_branch32", "re_loop64", "re_unselected64")
REFERENCE_COMMIT = "b72eb4a6a962958bb86ffbd88f6e6c310674367d"
REFERENCE_SHA256 = "d47c4b756a709ce2b57bdaa8a2dc70139211b5f881d31853c9b0672369b03bc7"
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 32 * 1024 * 1024
MAX_C_BYTES = 262144
MAX_PCODE_BYTES = 1048576


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_c(text):
    # Remove address-generated labels and whitespace, retaining real literals,
    # warnings, operators and parameter/local names as counterevidence.
    text = re.sub(r"\b(FUN|DAT|LAB)_[0-9a-fA-F]+\b", r"\1_ADDRESS", text)
    return " ".join(text.split())


def mapped_functions(symbols):
    found = {}
    for line in symbols.splitlines():
        match = re.match(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[tT]\s+(\S+)\s*$", line)
        if not match or match[3] not in FUNCTIONS:
            continue
        name = match[3]
        if name in found:
            raise ValueError("Duplicate companion function: " + name)
        address, size = int(match[1], 16), int(match[2], 16)
        if size < 1 or size > 65536:
            raise ValueError("Companion function size out of bounds: " + name)
        found[name] = {"id": name, "address": format(address, "x"), "size": size}
    if set(found) != set(FUNCTIONS):
        raise ValueError("Missing companion functions: " + ", ".join(sorted(set(FUNCTIONS) - set(found))))
    return [found[name] for name in FUNCTIONS]


def validate_export(path, manifest):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Missing or oversized exporter manifest")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schemaVersion") != 1 or report.get("status") != "completed":
        raise ValueError("Ghidra export is incomplete: " + str(report.get("error", report.get("status"))))
    if report.get("analysisTimedOut") is not False:
        raise ValueError("Auto-analysis timeout status is missing or failed")
    if report.get("ghidraVersion") != "12.2":
        raise ValueError("Expected Ghidra 12.2")
    if not str(report.get("javaVersion", "")).startswith("25."):
        raise ValueError("Expected JDK 25")
    heap = report.get("jvmMaxHeapBytes")
    cpus = report.get("availableProcessors")
    if type(heap) is not int or not 0 < heap <= 1073741824 or type(cpus) is not int or not 0 < cpus <= 2:
        raise ValueError("Headless CPU/heap limits were not verified")
    if report.get("binarySha256", "").lower() != manifest["binarySha256"]:
        raise ValueError("Imported binary does not match the requested artifact")
    expected = {item["id"]: item for item in manifest["functions"]}
    functions = report.get("functions", [])
    if len(functions) != len(expected) or {f.get("id") for f in functions} != set(expected):
        raise ValueError("Exported function identities do not match the manifest")
    result = {}
    for function in functions:
        name = function["id"]
        if function.get("status") != "completed" or function.get("timedOut") is not False or function.get("cancelled") is not False:
            raise ValueError("Unsuccessful function decompilation: " + name)
        if int(function.get("entryAddress", "-1"), 16) != int(expected[name]["address"], 16):
            raise ValueError("Function entry differs from its own symbol-bearing companion")
        facts = dict(function)
        for field, suffix, maximum in [("cFile", ".c", MAX_C_BYTES), ("pcodeFile", ".pcode.txt", MAX_PCODE_BYTES)]:
            filename = name + suffix
            if function.get(field) != filename:
                raise ValueError("Unexpected exporter artifact name")
            artifact = path.parent / filename
            if not artifact.is_file() or artifact.stat().st_size > maximum:
                raise ValueError("Missing or oversized exported text: " + filename)
            facts[field + "Sha256"] = sha256(artifact)
        c = (path.parent / function["cFile"]).read_text(encoding="utf-8")
        facts["normalizedC"] = normalize_c(c)
        facts["normalizedCSha256"] = hashlib.sha256(facts["normalizedC"].encode()).hexdigest()
        facts["cLines"] = len(c.splitlines())
        for field in ["nativeInstructions", "nativeInstructionBytes", "rawPcodeOperations", "highPcodeOperations", "highBasicBlocks", "highEdges"]:
            if type(facts.get(field)) is not int or facts[field] < 0:
                raise ValueError("Invalid metric: " + field)
        if facts["nativeInstructions"] == 0 or facts["highPcodeOperations"] == 0:
            raise ValueError("Empty function evidence")
        result[name] = facts
    return report, result


def compare_control(left, right):
    fields = ["nativeInstructions", "nativeInstructionBytes", "nativeCalls", "nativeJumps",
              "rawPcodeOperations", "rawPcodeHistogram", "highPcodeOperations", "highPcodeHistogram",
              "highBasicBlocks", "highEdges", "normalizedC"]
    differences = []
    for name in FUNCTIONS:
        for field in fields:
            if left[name].get(field) != right[name].get(field):
                differences.append({"function": name, "field": field})
    if differences:
        raise ValueError("Repeated ordinary analysis was unstable: " + json.dumps(differences))
    return {"status": "passed", "functions": len(FUNCTIONS), "fieldsCompared": fields}


class Commands:
    """Bounded local subprocess execution; logs and command facts stay in the run."""

    def __init__(self, output):
        self.output = output
        self.records = []
        self.affinity = sorted(os.sched_getaffinity(0))[:2]

    def run(self, argv, label, *, timeout=120, env=None, output_limit=MAX_LOG_BYTES):
        destination = self.output / "logs" / (label + ".log")
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [str(part) for part in argv]
        started = time.monotonic()
        record = {"argv": command, "log": str(destination.relative_to(self.output)), "timeoutSeconds": timeout}
        self.records.append(record)

        def restrict():
            os.sched_setaffinity(0, set(self.affinity))

        with destination.open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True, preexec_fn=restrict)
            reason = None
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    reason = "deadline exceeded"
                elif destination.stat().st_size > output_limit:
                    reason = "subprocess output bound exceeded"
                if reason:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    break
                time.sleep(0.1)
            record.update(elapsedSeconds=time.monotonic() - started, exitCode=process.returncode)
            if reason:
                record["failure"] = reason
        if destination.stat().st_size > output_limit:
            raise RuntimeError(label + ": subprocess output bound exceeded")
        if reason or process.returncode:
            tail = destination.read_bytes()[-2500:].decode("utf-8", errors="replace")
            raise RuntimeError(f"{label}: {reason or 'exit ' + str(process.returncode)}\n{tail}")
        return destination.read_text(encoding="utf-8", errors="replace")


def build_case(args, commands, optimization, variant, plugin, directory):
    directory.mkdir()
    binary = directory / "corpus.symbols"
    stripped = directory / "corpus.stripped"
    flags = ["-std=c++17", "-" + optimization, "-g0", "-fno-pie", "-no-pie", "-I", ROOT / "include"]
    if plugin:
        flags.append("-fpass-plugin=" + str(plugin))
    commands.run([args.llvm_bin / "clang++", *flags, CORPUS, "-o", binary], f"{optimization}-{variant}-compile")
    if binary.stat().st_size > MAX_BINARY_BYTES:
        raise ValueError("Generated binary exceeds 32 MiB")
    symbols = commands.run([args.llvm_bin / "llvm-nm", "--numeric-sort", "--print-size", "--defined-only", binary], f"{optimization}-{variant}-symbols")
    functions = mapped_functions(symbols)
    shutil.copyfile(binary, stripped)
    commands.run([args.llvm_bin / "llvm-strip", "--strip-all", stripped], f"{optimization}-{variant}-strip")
    stripped.chmod(0o700)
    symbol_output = commands.run([args.llvm_bin / "llvm-nm", stripped], f"{optimization}-{variant}-stripped-symbols")
    if any(re.search(r"\b" + name + r"\b", symbol_output) for name in FUNCTIONS):
        raise ValueError("Selected symbols survived --strip-all")
    companions_output = commands.run([binary], f"{optimization}-{variant}-behavior-symbols", output_limit=1048576)
    stripped_output = commands.run([stripped], f"{optimization}-{variant}-behavior-stripped", output_limit=1048576)
    if companions_output != stripped_output:
        raise ValueError("Stripping changed fixture behavior")
    if len(stripped_output.splitlines()) != 633:
        raise ValueError("Behavior corpus was not fully executed")
    disassembly = commands.run([args.llvm_bin / "llvm-objdump", "--no-show-raw-insn", "--disassemble-symbols=" + ",".join(FUNCTIONS), binary], f"{optimization}-{variant}-disassembly")
    (directory / "disassembly.txt").write_text(disassembly, encoding="utf-8")
    commands.run(["readelf", "--wide", "--file-header", "--sections", stripped], f"{optimization}-{variant}-readelf")
    commands.run(["strings", "-a", stripped], f"{optimization}-{variant}-strings")
    manifest = {"schemaVersion": 1, "binary": str(stripped), "binarySha256": sha256(stripped), "functions": functions}
    write_json(directory / "functions.json", manifest)
    return {"optimization": optimization, "variant": variant, "flags": [str(f) for f in flags],
            "binary": str(binary), "binarySha256": sha256(binary), "binaryBytes": binary.stat().st_size,
            "stripped": str(stripped), "strippedSha256": manifest["binarySha256"], "strippedBytes": stripped.stat().st_size,
            "behaviorSha256": hashlib.sha256(stripped_output.encode()).hexdigest(), "behaviorCases": 633,
            "manifest": manifest, "directory": str(directory)}, stripped_output


def export_case(args, commands, case, name, directory):
    directory.mkdir(exist_ok=True)
    project = directory / "projects"
    project.mkdir()
    export = directory / "decompiled"
    export.mkdir()
    home = directory / "runtime-home"
    home.mkdir()
    manifest_path = directory / "requested-functions.json"
    write_json(manifest_path, case["manifest"])
    environment = dict(os.environ)
    for variable in ["JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"]:
        environment.pop(variable, None)
    environment["JAVA_HOME"] = str(args.java_home)
    environment["PATH"] = str(args.java_home / "bin") + os.pathsep + environment.get("PATH", "")
    quoted_home = str(home).replace("\\", "\\\\").replace('"', '\\"')
    environment["_JAVA_OPTIONS"] = f'-Xmx1024m -XX:ActiveProcessorCount=2 -Duser.home="{quoted_home}"'
    command = [args.ghidra_home / "support/analyzeHeadless", project, "owned-corpus", "-import", case["stripped"],
               "-scriptPath", Path(__file__).resolve().parent, "-postScript", "ExportDecompilation.java",
               manifest_path, export, str(args.decomp_timeout), "-analysisTimeoutPerFile", str(args.analysis_timeout),
               "-max-cpu", "2", "-deleteProject"]
    commands.run(command, name + "-ghidra", timeout=args.analysis_timeout + len(FUNCTIONS) * args.decomp_timeout + 45,
                 env=environment)
    report, metrics = validate_export(export / "export.json", case["manifest"])
    return {"directory": str(directory), "export": str(export / "export.json"),
            "runtime": {key: report[key] for key in ["ghidraVersion", "javaVersion", "jvmMaxHeapBytes", "availableProcessors", "language", "compilerSpec", "imageBase"]},
            "functions": metrics}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-plugin", type=Path, required=True)
    parser.add_argument("--candidate-plugin", type=Path)
    parser.add_argument("--ghidra-home", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--llvm-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["smoke", "matrix"], default="matrix")
    parser.add_argument("--analysis-timeout", type=int, default=120)
    parser.add_argument("--decomp-timeout", type=int, default=30)
    result = parser.parse_args(argv)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This protocol targets Linux x86-64")
    if not result.output.is_absolute():
        parser.error("--output must be an absolute directory")
    if not 1 <= result.analysis_timeout <= 120 or not 1 <= result.decomp_timeout <= 30:
        parser.error("Timeout bounds: analysis 1..120, decompilation 1..30 seconds")
    if result.mode == "matrix" and result.candidate_plugin is None:
        parser.error("--candidate-plugin is required for the full matrix")
    for key in ["baseline_plugin", "candidate_plugin", "ghidra_home", "java_home", "llvm_bin", "output"]:
        if getattr(result, key) is not None:
            setattr(result, key, getattr(result, key).resolve())
    inside_repository = result.output == ROOT or ROOT in result.output.parents
    work = ROOT / "work"
    inside_work = result.output == work or work in result.output.parents
    if inside_repository and not inside_work:
        parser.error("Generated evidence inside the repository must be under work/")
    return result


def main(argv=None):
    args = arguments(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    result = {"schemaVersion": 1, "status": "incomplete", "mode": args.mode, "cases": [], "controls": [],
              "referenceCommit": REFERENCE_COMMIT, "referencePluginSha256": None, "candidatePluginSha256": None,
              "commands": commands.records, "cpuAffinity": commands.affinity}
    try:
        if CORPUS.stat().st_size > 524288:
            raise ValueError("Owned source fixture exceeds 512 KiB")
        result["fixtureSha256"] = sha256(CORPUS)
        result["exporterSha256"] = sha256(Path(__file__).with_name("ExportDecompilation.java"))
        result["orchestratorSha256"] = sha256(__file__)
        result["referencePluginSha256"] = sha256(args.baseline_plugin)
        if result["referencePluginSha256"] != REFERENCE_SHA256:
            raise ValueError("Reference plugin differs from the frozen b72eb4a artifact")
        if args.candidate_plugin:
            result["candidatePluginSha256"] = sha256(args.candidate_plugin)
        result["compiler"] = commands.run([args.llvm_bin / "clang++", "--version"], "compiler-version").splitlines()[0]
        result["llvmVersion"] = commands.run([args.llvm_bin / "llvm-config", "--version"], "llvm-version").strip()
        if result["llvmVersion"] != "18.1.3":
            raise ValueError("Expected LLVM 18.1.3")
        result["java"] = commands.run([args.java_home / "bin/java", "--version"], "java-version").strip()
        runtime_metadata = ROOT / "work/re-runtime.json"
        if runtime_metadata.is_file():
            result["toolAcquisition"] = json.loads(runtime_metadata.read_text(encoding="utf-8"))
        for optimization in (["O2"] if args.mode == "smoke" else ["O2", "O3"]):
            variants = [("normal", None), ("reference", args.baseline_plugin)]
            if args.mode == "matrix":
                variants.append(("candidate", args.candidate_plugin))
            built = []
            expected = None
            # Every executable must agree before decompilation evidence is accepted.
            for variant, plugin in variants:
                print(f"build and execute {optimization}/{variant}", file=sys.stderr, flush=True)
                case, behavior = build_case(args, commands, optimization, variant, plugin, args.output / f"{optimization}-{variant}")
                if expected is None:
                    expected = behavior
                elif behavior != expected:
                    raise ValueError(f"Behavior mismatch at {optimization}/{variant}")
                built.append(case)
                result["cases"].append(case)
            for case in built:
                name = f"{optimization}-{case['variant']}"
                print(f"Ghidra {name}", file=sys.stderr, flush=True)
                case["analysis"] = export_case(args, commands, case, name, Path(case["directory"]) / "ghidra")
            print(f"Ghidra {optimization}/normal-repeat", file=sys.stderr, flush=True)
            repeated = export_case(args, commands, built[0], f"{optimization}-normal-repeat", args.output / f"{optimization}-normal-repeat")
            control = compare_control(built[0]["analysis"]["functions"], repeated["functions"])
            result["controls"].append({"optimization": optimization, **control, "repeatAnalysis": repeated})
        comparisons = []
        for case in result["cases"]:
            normal = next(item for item in result["cases"] if item["optimization"] == case["optimization"] and item["variant"] == "normal")
            for name in FUNCTIONS:
                observed = case["analysis"]["functions"][name]
                baseline = normal["analysis"]["functions"][name]
                comparisons.append({"optimization": case["optimization"], "variant": case["variant"], "function": name,
                                    "normalizedCEqualToNormal": observed["normalizedC"] == baseline["normalizedC"],
                                    "nativeInstructionDelta": observed["nativeInstructions"] - baseline["nativeInstructions"],
                                    "highPcodeOperationDelta": observed["highPcodeOperations"] - baseline["highPcodeOperations"],
                                    "highBasicBlockDelta": observed["highBasicBlocks"] - baseline["highBasicBlocks"]})
        result["comparisons"] = comparisons
        if sha256(CORPUS) != result["fixtureSha256"] or sha256(args.baseline_plugin) != result["referencePluginSha256"]:
            raise ValueError("Fixture or reference plugin changed during evaluation")
        if args.candidate_plugin and sha256(args.candidate_plugin) != result["candidatePluginSha256"]:
            raise ValueError("Candidate plugin changed during evaluation")
        result["status"] = "completed"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    result["methodology"] = {
        "inputs": "Only the included owned re-corpus.cpp is compiled; 633 deterministic boundary/random rows, eight values each. Companion and stripped outputs must match exactly across variants.",
        "stripping": "Identical llvm-strip --strip-all treatment. Function locations are supplied from each build's own companion; missing auto-discovered functions are materialized at those entries without supplying names. functionOrigin records this assistance. This experiment grants known locations and does not measure discovery.",
        "analysis": "Fresh Ghidra projects, default auto-analysis, simplification style decompile, max-cpu=2 plus OS affinity to two CPUs; JVM max heap 1 GiB, verified by exporter. No network operations.",
        "controls": "Repeated normal binary must have identical function metrics and normalized C. Normalization changes address-generated FUN/DAT/LAB identifiers and whitespace only; real constants and warnings are retained.",
        "scope": "Counts, text and differences are descriptive evidence. Decompiled C is inspected manually for semantic recovery. Timeouts, incomplete results and missing functions are inconclusive, not improvements. No composite resistance score.",
    }
    write_json(args.output / "evaluation.json", result)
    print(json.dumps({"status": result["status"], "output": str(args.output / "evaluation.json"), "error": result.get("error")}), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
