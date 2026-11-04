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

## SiMBA applied to the v0.2.0 native artifacts

On 2026-11-04, a new run used the exact stripped ordinary and v0.2.0 executables
from the historical release, checked against the published report hashes. This
extends the historical analysis; the original release did not run SiMBA.
Ghidra 12.2 with Temurin 25.0.5+8 exported pure SSA return slices; official SiMBA
commit `228179970f5906ed763afb33fc8649de2846696e` simplified them at their actual
32/64-bit widths, with Z3 4.13.3 checking both input-to-result and result-to-source
equivalence. The fixed [protocol and commands](re-validation.md#simba-recovery-protocol)
define the limits and recovery criterion.

Both optimization levels gave the same outcomes:

| Build (each of O2 and O3) | Recovered | Not recovered | Unsupported | Timeout | Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary control | 6 | 0 | 2 | 0 | 0 |
| Released v0.2.0 | 5 | 0 | 3 | 0 | 0 |

Every expression accepted by SiMBA was recovered. For the general sums, the
expressions were extracted from Ghidra P-code, not copied from the source:

| Function | Extracted v0.2.0 expression | SiMBA result |
| --- | --- | --- |
| `re_sum32` | `((p1\|p0)*2)-(p1^p0)` | `p0+p1` |
| `re_sum64` | `(p1^p0)+((p1&p0)*2)` | `p0+p1` |
| `re_identical64` | `p0*2` | `2*p0` |
| `re_zero32` | `p0` | `p0` |
| `re_unselected64` | `p0+p1` | `p0+p1` |

These six straight-line slices include three controls: `re_identical64` becomes
a shift before the optimizer-last pass, `re_zero32` becomes a direct return, and
`re_unselected64` is not selected. The three transformed straight-line functions
are the general 32/64-bit sums and the constant addition. Thus “six recovered”
does not mean six protected functions survived transformation and were attacked.
Branch and loop functions contain additional transformed arithmetic but are
outside this extractor's scope. An inspected O2 candidate IR confirms that the
identical/zero functions lack `irveil.processed`, while the general/constant sums
carry it.

For `re_constant32`, Ghidra exposed `((p0*2)|34)-(p0^17)`. SiMBA's linearity
checker rejected this form. It is **unsupported**, not a failed recovery on a
supported input and not evidence that the addition is hidden from an analyst.
The ordinary constant case simplified to `17+p0`. `re_branch32` and `re_loop64`
were rejected by the extractor for control flow in every build. The previously
documented missing loop return in the ordinary decompilation is not counted as
an obfuscation success.

All four historical executables again agreed on 633 rows of eight results.
All 22 recovered records across the two optimization levels passed both Z3
queries (`unsat` for a possible difference). Ten unsupported records were retained
with their reasons; there were no timeouts or tool errors. These are related
synthetic functions, not a representative application sample. The experiment
demonstrates recovery of the general additions against this fixed simplifier;
it does not quantify human effort or resistance to other tools.

## Rejected composed-identity candidate

The [composed experiment (#5)](https://github.com/Altitud-Studio-S-L-U/irveil/pull/5)
computes `u=a^b`, `v=2*(a&b)`, then applies one of the two
existing seeded identities to `u+v`. The predefined hypothesis was that this
composition would leave SiMBA's linear domain but GAMBA's substitutions would
still recover the sum. The candidate keeps the original operand freezes, drops
overflow flags and caps emitted instructions independently; its LLVM/semantic
checks are separate from the recovery counts below.

The same native corpus and historical controls were evaluated with the fixed
SiMBA protocol and then the complementary GAMBA protocol. At both O2 and O3:

| Build | SiMBA recovered / unsupported | GAMBA recovered / unsupported |
| --- | --- | --- |
| Ordinary control | 6 / 2 | 6 / 2 |
| Released v0.2.0 | 5 / 3 | 6 / 2 |
| Composed identity | 3 / 5 | 6 / 2 |

No run had a `not_recovered`, timeout or error result. All GAMBA-accepted
expressions passed both bounded Z3 proofs. In particular, the candidate's native
32-bit return slice
`((((p1^p0)|((p1&p0)*2))*2)-(((p1&p0)*2)^(p1^p0)))`
simplified to `p0+p1`. GAMBA also recovered the released constant expression as
`17+p0`, closing the SiMBA domain gap without changing the historical result.
Branch and loop functions remained outside the extractor's domain for every
build. The native executions agreed on all 633 rows.

The composition increased cost without reducing recovery by the general attack:

| Function | Native instructions: normal / v0.2.0 / composed | Native bytes: normal / v0.2.0 / composed |
| --- | --- | --- |
| `re_sum32` | 2 / 6 / 10 | 4 / 11 / 19 |
| `re_sum64` | 2 / 5 / 9 | 5 / 14 / 26 |
| `re_constant32` | 2 / 5 / 10 | 4 / 12 / 21 |
| `re_unselected64` | 2 / 2 / 2 | 5 / 5 / 5 |

In a new 10-million-iteration demo measurement (one omitted warm-up pair and five
alternating pairs), the normal/composed function had 91/221 native instructions.
Median process times were 0.207222/0.275844 seconds, with equal checksum
`c968f6319a63b582`. A separate v0.2.0 comparison on the same day had 91/146
instructions and medians 0.218350/0.241259 seconds. Both comparisons include
startup and uncontrolled host load; they are not a direct paired timing comparison
between the two plugin versions. All stripped demo files were 14,400 bytes.

The composed candidate is rejected as the default transformation. Its lower
SiMBA recovery count is entirely explained by unsupported input; GAMBA recovered
all supported operations while native code grew. This is an observed negative
result, not a claim that all possible compositions or other algorithms must fail.

## Rejected prefix-carry candidate and a semantic recognition control

The [prefix experiment (#6)](https://github.com/Altitud-Studio-S-L-U/irveil/pull/6),
source `52813541196ec63619ed300277dc4aacddea04a0`, replaces addition with a bounded
parallel carry network. It combines generate/propagate bits at distances 1, 2, 4,
8, 16 and 32 as required by the integer width, then XORs the original differing
bits with the carry bits. A seed selects XOR or OR propagation. Identical original
operands use XOR propagation to preserve the existing canonicalization control.
The candidate emits no replacement additions and caps emitted instructions per
function, including freezes; a 64-bit replacement emits at most 35 instructions.

The primary 512-node extractor rejected the three transformed straight-line
functions. A separately predefined expanded profile successfully extracted their
actual P-code: 602 tree nodes for each 32-bit case and 1,381 for the 64-bit sum.
The final comparison used frozen evaluator/exporter sources and the fixed plugin
SHA-256 `4fb2461a44014b957845105d9305eb69d2a37b166f0fa1e7ffeb8adb64cc4068`.
Both O2 and O3 produced these outcomes under the expanded profile:

| Build | SiMBA: recovered / unsupported | GAMBA: recovered / unsupported / timeout | Bounded recognizer: recovered / unsupported |
| --- | --- | --- | --- |
| Ordinary control | 6 / 2 | 6 / 2 / 0 | 6 / 2 |
| Released v0.2.0 | 5 / 3 | 6 / 2 / 0 | 6 / 2 |
| Composed identity | 3 / 5 | 6 / 2 / 0 | 6 / 2 |
| Prefix carry | 3 / 5 | 3 / 2 / 3 | 6 / 2 |

There were no tool errors. SiMBA rejected the three prefix expressions as outside
its linear domain. GAMBA exceeded the five-second worker deadline on those same
expressions, at both widths and optimization levels; those runs are **incomplete**,
not evidence of resistance. The three GAMBA recoveries are the controls, not the
transformed sums. Branch and loop functions remain unsupported by extraction.

The independently bounded recognizer learned simple operations from observations
of the extracted expressions, without receiving a source operation or function
name. For every build at both optimization levels it recovered the six pure
slices, including all three transformed straight-line functions. Each learned
expression passed the unused 32-pair holdout and a Z3 `unsat` proof against the
full extracted expression. Source-operation comparison happened only afterwards.
It learned addition for both general sums, addition of 17 for the constant case,
doubling for identical operands and identity for the zero-addition control.
There were no recognizer timeouts or errors. The final protocol and report retain
the exact grammar, sampling seed, tool/input hashes and per-function proof facts.

Thus prefix carry delayed this bounded GAMBA invocation but did not prevent
recovery by a much smaller operation recognizer. It also increased native cost:

| Function | Native instructions: normal / v0.2.0 / prefix | Native bytes: normal / v0.2.0 / prefix |
| --- | --- | --- |
| `re_sum32` | 2 / 6 / 36 | 4 / 11 / 88 |
| `re_sum64` | 2 / 5 / 41 | 5 / 14 / 140 |
| `re_constant32` | 2 / 5 / 36 | 4 / 12 / 91 |
| `re_unselected64` | 2 / 2 / 2 | 5 / 5 / 5 |

The final prefix demo measurement used 10 million iterations, one omitted
warm-up pair and five alternating pairs: 91/810 native instructions and median
process times 0.196970/0.601279 seconds for normal/prefix, with equal checksum
`c968f6319a63b582`. Both stripped files occupied 14,400 bytes. These timings include
startup and uncontrolled host load and describe one synthetic workload.

Both candidates remain outside the default transformation. Composition was
recovered by GAMBA; prefix carry was recovered by the small semantic recognizer
despite GAMBA timeouts. Each added cost. This evidence supports rejecting these
specific candidates; it does not prove that all arithmetic obfuscation is equally
recoverable or replace an evaluation of a larger real application.
