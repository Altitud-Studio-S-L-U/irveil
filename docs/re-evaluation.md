# Reverse-engineering evaluation: v0.1 and v0.2

## Conclusion

The arithmetic expressions remain readable and algebraically recoverable in Ghidra's decompiled C. This experiment does **not** demonstrate greater resistance to Ghidra or a human analyst. The measured scope is arithmetic diversification; it does not establish a protection boundary.

There is a narrower, measured improvement: v0.2 removes an identity that LLVM 18.1.3 InstCombine restores directly to an addition. The new regression fails against the preserved v0.1 plugin and passes against v0.2. Increasing instructions or high P-code operations is not interpreted as a resistance score.

## Environment and artifacts

- Linux x86-64, Ubuntu under WSL2; Clang/LLVM **18.1.3**.
- Ghidra **12.2**, Temurin JDK **25.0.5+8**. Official tool archives were verified by SHA-256.
- JVM maximum heap **1 GiB**, two available processors plus OS CPU affinity; these are not a cap on the process's total RSS.
- Reference source: [`b72eb4a`](https://github.com/Altitud-Studio-S-L-U/irveil/tree/b72eb4a6a962958bb86ffbd88f6e6c310674367d). Reference plugin SHA-256: `d47c4b756a709ce2b57bdaa8a2dc70139211b5f881d31853c9b0672369b03bc7`.
- Candidate plugin SHA-256: `c2c685cd7cbbb4dfb78e1ab488f0f4b98517bfd390d66119377a4bb86c727320`.

The [v0.2.0 release](https://github.com/Altitud-Studio-S-L-U/irveil/releases/tag/v0.2.0) contains structured evaluation data, both canonicalization reports, the owned stripped fixtures, disassembly, decompiled C and P-code, the two measured plugins and a SHA-256 manifest. Plugins are benchmark artifacts for the exact Linux/LLVM installation, not portable native packages. Generated Ghidra projects and full logs are not committed or published. Published JSON substitutes local workspace/tool paths with `${IRVEIL_ROOT}`, `${GHIDRA_HOME}` and `${JAVA_HOME}`; measured facts and artifact hashes are unchanged.

## LLVM canonicalization

The fixed corpus has 16 seeds, four widths (2, 8, 32, 64), and two operand categories (unknown and `noundef`), giving 128 general-input cases per pipeline. Each pipeline also has 128 `a+0` / `a+a` controls. These are related synthetic cases, not independent samples of real-world software.

| Pipeline | v0.1 restored to a single add | v0.2 restored to a single add | Control mismatches, both versions |
| --- | ---: | ---: | ---: |
| InstCombine | 70 / 128 | 0 / 128 | 0 / 128 |
| Canonicalization combination | 70 / 128 | 0 / 128 | 0 / 128 |
| Default O2 | 70 / 128 | 0 / 128 | 0 / 128 |
| Default O3 | 70 / 128 | 0 / 128 | 0 / 128 |

The 70 restored cases are exactly those choosing v0.1's OR/AND identity. The retained XOR/carry identity survives these particular pipelines. v0.2 replaces the weak form with `2*(a OR b) - (a XOR b)`. Both alternatives are still public algebraic identities. Constants, identical operands and other special cases can simplify legitimately; the controls verify that the check is capable of observing simplification.

This stage examines LLVM IR, a distinct exposure model from native-binary RE. It does not establish survival against every LLVM pass, another compiler, a symbolic simplifier or a pattern-aware analyst.

## Native binaries and Ghidra

The same owned [fixture](../tests/fixtures/re-corpus.cpp) was built normally, with v0.1 and with v0.2 at both `-O2` and `-O3`. All six builds use C++17, `-g0`, `-fno-pie -no-pie` and the same annotation header. Each symbol-bearing companion and its `llvm-strip --strip-all` copy produced identical output for 633 deterministic boundary/random rows, each containing eight results. All variants agreed byte-for-byte.

Ghidra analyzed the stripped executables in fresh projects. Each function's location came from that build's own symbol-bearing companion. For a trivial function not discovered automatically, the exporter materialized a function at the known entry without supplying a source name. The experiment therefore grants function locations; it does not measure discovery. No source prototypes were supplied.

Eight Ghidra jobs exported 64 function records: six builds plus a repeated normal analysis at each optimization level. All exports completed without timeouts or cancellation. Both repeated controls had identical selected metrics and normalized C. Normalization changes only address-generated identifiers and whitespace.

The following counts are identical at O2 and O3. Native instruction counts include the return instruction. High P-code counts describe Ghidra's simplified representation.

| Function | Native: normal / v0.1 / v0.2 | High P-code: normal / v0.1 / v0.2 |
| --- | --- | --- |
| General 32-bit sum | 2 / 5 / 6 | 3 / 5 / 6 |
| General 64-bit sum | 2 / 5 / 5 | 3 / 6 / 6 |
| Add a constant | 2 / 5 / 5 | 3 / 5 / 6 |
| Branch-dependent arithmetic | 14 / 19 / 19 | 14 / 20 / 20 |
| Identical operands | 2 / 2 / 2 | 3 / 3 / 3 |
| Add zero | 2 / 2 / 2 | 2 / 2 / 2 |
| Unselected function | 2 / 2 / 2 | 3 / 3 / 3 |

For the general 32-bit sum, Ghidra produces these return expressions (original generated parameter names retained):

```c
// Ordinary build
return param_1 + param_2;

// v0.1
return (param_2 & param_1) + (param_2 | param_1);

// v0.2
return (param_2 | param_1) * 2 - (param_2 ^ param_1);
```

The general 64-bit sum in both plugin versions remains:

```c
return (param_2 ^ param_1) + (param_2 & param_1) * 2;
```

Ghidra did not automatically reduce these particular general-input expressions to plain addition. However, it exposes their operands and operations directly. Applying the documented identities recovers their meaning; changing one public identity for another does not demonstrate a meaningful increase in analyst effort. The constant case is also readable. `a+a` becomes a multiplication by two and `a+0` returns its argument, as expected.

## Cost observation

A separate run of the included `examples/demo.cpp` fixture used 10 million iterations, one omitted warm-up pair and five alternating measured pairs with ordinary and v0.2 builds. Both produced checksum `c968f6319a63b582`. The ordinary selected function had 91 native instructions and the candidate 146. Both stripped executables occupied 14,400 bytes because file layout and alignment can hide a local code-size change.

Median process times were 0.194606 seconds for the ordinary build and 0.218661 seconds for v0.2 in this run. These include process startup, use warm filesystem caches and have uncontrolled host load. They describe one synthetic workload; they do not establish a universal overhead, a speed improvement over a previous run, or a security benefit. The measurement JSON is included with the release evidence.

## Counterevidence and exclusions

For `re_loop64`, Ghidra infers a `void` return in the ordinary build even though the source returns `uint64_t`; the decompiled C omits the return arithmetic. It infers a non-void return for both plugin builds. Native execution agrees across all variants. This is a decompiler inference limitation, not an obfuscation success. Its C, P-code and block deltas are excluded from conclusions about analysis difficulty. A repeatable decompilation is not necessarily a semantically correct one.

No human timing study, function-discovery challenge, binary patching exercise, symbolic synthesis benchmark or representative commercial-application corpus was performed. No percentage of protection is inferred from this study.

## Reproduce

Build IRVeil and run its local suite as documented in the README, using Python 3.8 or later. Obtain Ghidra 12.2 and JDK 25 from their official releases and verify their archive checksums. Use the frozen reference plugin from the v0.2.0 release; the RE harness checks its exact hash and requires LLVM 18.1.3. The recorded candidate hash and Ghidra results above also belong to v0.2.0; evaluating a later build produces new evidence. For general library integration, build from source against the matching installed LLVM package.

```sh
python3 tools/check_canonicalization.py --llvm-bin /usr/lib/llvm-18/bin \
  --plugin /absolute/path/to/reference.so --output work/reference.json
# The reference check must exit 1: it demonstrates the old regression.

python3 tools/check_canonicalization.py --llvm-bin /usr/lib/llvm-18/bin \
  --plugin build/IRVeilPass.so --output work/candidate.json

python3 -m unittest discover -s tools/re -p 'tests_*.py'

python3 tools/re/evaluate.py \
  --baseline-plugin /absolute/path/to/reference.so \
  --candidate-plugin build/IRVeilPass.so \
  --ghidra-home /absolute/path/to/ghidra_12.2_PUBLIC \
  --java-home /absolute/path/to/jdk-25 \
  --llvm-bin /usr/lib/llvm-18/bin --output /absolute/path/to/new-evidence-directory
```

The exporter rejects failed analysis, cancellation, missing functions, changed binary hashes and unverified limits. The runner treats failures as incomplete evidence. Read the [predefined protocol](re-validation.md) and the raw pseudocode alongside counts before drawing a conclusion.
