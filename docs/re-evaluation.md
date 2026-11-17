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

## Experimental framework evaluation

On 2026-11-17, source `d1a3d17` was evaluated separately from the historical
arithmetic experiments. LLVM/Clang 18.1.3 on Linux x86-64 under WSL2 built the
owned `framework-corpus.cpp` normally, with the existing `general` profile, and
with all ten explicit transform families at seed 42. Both O2 and O3 were tested.
Ghidra 12.2 / Temurin 25.0.5+8 used fresh projects, the same 1 GiB heap/two-CPU
limits and exporter checks as the historical evaluator. Each build's own companion
provided function locations; no source prototypes were supplied. This does not
measure function discovery. Raw evidence remains local under `work/`.

All six symbol-bearing executables and their stripped copies agreed on 633
deterministic boundary/random rows of eight results. Output SHA-256 was
`52b7784ef28505b0f53a3b69beae840a42c7606d87d57313934ea477ce424807`.
Eight Ghidra jobs exported 64 records, including repeated normal analyses at each
optimization level. Both repeats had identical normalized C and selected metrics;
there were no decompilation timeouts, cancellation or exporter errors. A preliminary
harness run was incomplete because its repeat-control helper still expected the
old corpus's names; the final run parameterizes and checks that set explicitly.

The all-family IR counters were:

| Optimization | Adds / sub / bitwise / cmp / branches | CFG / loop edges | Switches | Literal operands | Strings / bytes |
| --- | --- | --- | --- | --- | --- |
| O2 | 10 / 2 / 10 / 11 / 7 | 21 / 2 | 1 | 22 | 1 / 9 |
| O3 | 17 / 2 / 12 / 18 / 15 | 36 / 4 | 1 | 35 | 1 / 9 |

These are module totals, with separate per-function budgets. LLVM's earlier
optimizations change the operations available at the optimizer-last extension.
Counters establish that a family ran, not that it survived machine-code emission.

Native instruction counts, including returns but excluding inter-symbol padding:

| Function | O2: normal / general / all families | O3: normal / general / all families |
| --- | --- | --- |
| Branches (`re_cfg32`) | 13 / 25 / 25 | 13 / 25 / 25 |
| Nested loops (`re_loop32`) | 39 / 61 / 61 | 91 / 135 / 135 |
| Switch (`re_switch32`) | 22 / 32 / 31 | 22 / 32 / 31 |
| Constant arithmetic (`re_constant64`) | 2 / 4 / 4 | 2 / 4 / 4 |
| Private string (`re_string8`) | 7 / 7 / 8 | 7 / 7 / 8 |
| Escaping string control | 1 / 1 / 1 | 1 / 1 / 1 |
| Unselected arithmetic control | 2 / 2 / 2 | 2 / 2 / 2 |
| Integer logic (`re_bool32`) | 15 / 39 / 39 | 15 / 39 / 39 |

All stripped files were 14,296 bytes; alignment/file layout masks local growth.
No runtime overhead measurement or resistance score is inferred from this table.

Ghidra reconstructed ordinary conditions and a readable case ladder. The extra
CFG/backedge routes did not produce additional decompiled blocks compared with
the general profile, and literal splits did not introduce extra native instructions
in these functions. The string retained one extra native instruction and decompiled
as a byte-table load XORed with `0x23`: the key is visible, and recovery is direct.
The escaping string and unselected function remained unchanged controls. These
observations support keeping structural/data families opt-in; this run provides
no demonstrated increase in analyst effort.

At O2, Ghidra inferred a `void` return for the nested loop in all three variants,
omitting its actual returned arithmetic despite agreeing native executions. At O3
it inferred a non-void return and emitted a global-overlap warning. Loop pseudocode
and P-code/block counts are therefore excluded from claims about recovery or
difficulty. Stable repeated output does not establish correct decompiler typing.

Candidate plugin SHA-256:
`7e87cc9bc3d68d95d805d3b2ca46a7e8d470cee96f298e3ddb7fd9931e1c3386`.
Fixture SHA-256:
`4fbb306d7692511044e60c541d440b81b35a0366e49cf891a560766511450e18`.
Reproduce with the [framework protocol](re-validation.md#experimental-framework-protocol).

The decoder-load budget added in source `daa47a0` was evaluated with a new plugin
SHA-256 `37686d36f59b8354e2e0785452d2a1e002df5b323bbfc6ea01443c20ffe1322e`.
The full six-build/eight-Ghidra-job protocol completed again, with both repeated
controls stable. All six native binaries and stripped copies were byte-for-byte
identical to the corresponding earlier artifacts, and every 633-row behavior
hash matched. Each all-family build decoded one byte load, within the new default
4096-load module budget. Thus the table and counterevidence above also describe
this revised corpus run. These fixtures do not exercise budget exhaustion; the
separate LLVM regression uses a two-byte string with 4097 static readers and
checks atomic skipping, module-wide accounting and later globals that still fit.

## Bounded flattening experiment

Source `2d79275` was evaluated on Linux x86-64 under WSL2 with LLVM/Clang 18.1.3,
Ghidra 12.2 and Temurin 25.0.5+8, using the
[predefined flattening protocol](re-validation.md#bounded-flattening-protocol).
Only `transforms=flatten` was enabled, at seed 42 and the default 16 dispatched
blocks/256 added instructions per function. Ordinary, flattened and reoptimized
variants were built at O2/O3. Reoptimized means an extra `opt default<O2/O3>`
pipeline on flattened IR, then the same backend level with IR passes disabled.
The source's volatile cells and disabled loop unrolling apply to every variant.
This is a synthetic integer/control-flow workload, not an application sample.

### Behavior and IR work

All six symbol companions and stripped copies agreed on 633 boundary/random rows,
each containing eight function results and four resulting memory cells. Their
behavior SHA-256 was
`e9b7c7c999d3e186e0c8f25727634f34f9eaf7279d3326de9c9c06e402fae16e`.
Every benchmark run also agreed on checksum `afa8a286231f35d5` for 1,000,000
iterations. The separate tests cover O0/O1/O2/O3, debug info, ASan/UBSan, shared
atomic calls, parallel PHIs, critical edges and reoptimization; behavior checks
remain distinct from the observations about decompilation below.

At both O2/O3, five functions flattened: branch logic, a loop, loop-carried PHIs,
possibly aliased memory and recursive source. LLVM had already converted the
recursive source to a loop in these optimized builds. Module totals were 34
dispatched blocks, 42 private spill slots and 199 net additional IR instructions.
The input switch and straight-line selected function were unsupported controls;
the unselected function was never eligible. No function exhausted its budget.

Initially each transformed function had a PHI-fed switch. Reoptimization removed
all 42 IR spill slots and the switches in the branch/memory cases. Three remaining
functions still had PHI-fed switches; all five retained the processed/flattened
attributes. Thus attributes record past work, not survival. Backends also split
or duplicate dispatch routing: four direct flattened functions contained indirect
jumps, while the memory case used direct branches with state comparisons.

### Native footprint and timing

Native cost is measured over each complete ELF symbol from its own companion,
including padding within that symbol and excluding padding beyond its size.
It is independent of Ghidra's inferred function body, which can omit code.
The following O2 values are ordinary / flatten / reoptimized:

| Function | Native instructions | Symbol bytes |
| --- | --- | --- |
| Branch | 18 / 43 / 19 | 39 / 166 / 41 |
| Loop | 29 / 95 / 81 | 70 / 448 / 286 |
| Loop-carried PHIs | 23 / 66 / 47 | 65 / 325 / 164 |
| Aliased memory | 15 / 38 / 15 | 29 / 138 / 28 |
| Recursive source | 41 / 110 / 116 | 87 / 492 / 410 |

At O3 the branch row is 22 / 43 / 23 instructions and 45 / 166 / 47 bytes; the
other positive rows are unchanged. Negative controls retain their counts/bytes
within each optimization level. All stripped files are 14,320 bytes because
alignment/layout masks local growth. In-symbol instruction counts include NOP
padding; they are static footprint observations, not dynamic instruction counts.

Five measured runs per variant followed one omitted warmup, with alternating
compilation pairs and forward/reverse runtime orders. The benchmark invokes the
five positive functions with deterministic inputs and volatile cells. Median
process wall times in seconds were:

| Mode | Compile ordinary / flatten | Run ordinary / flatten / reoptimized |
| --- | --- | --- |
| O2 | 0.306 / 0.279 | 0.0409 / 0.0973 / 0.0840 |
| O3 | 0.330 / 0.283 | 0.0430 / 0.0924 / 0.0860 |

Flattened runtime was approximately 2.38x/O2 and 2.15x/O3 the ordinary median;
reoptimized runtime was 2.06x/O2 and 2.00x/O3. The lower observed compilation
medians do not establish a compiler speed improvement. These include process
startup, warm caches, two-CPU affinity and uncontrolled host load; no isolated-pass
profiling or confidence interval was measured. Raw samples and timed binary-hash
checks are retained with the local evidence. These timings do not generalize to
other programs, configurations or machines.

### Ghidra survival and counterevidence

Eight fresh Ghidra jobs exported 64 records, including two stable repeated normal
controls. Heap/CPU limits and all analysis/decompilation deadlines were unchanged;
there were no timeouts, cancellations or exporter failures. Each function entry
came from its own symbol companion, with no source prototypes. This grants known
locations and does not measure discovery.

The direct flattened branch decompiles to switches on the original boolean tests,
not an opaque central state machine. Loop/PHI cases expose the original iteration
conditions and arithmetic, with extra temporaries/gotos/switches. The memory case
retains public state comparisons; after reoptimization it becomes ordinary direct
flow. Reoptimized branch and memory cases lose their dispatch entirely. Native
state routing survives in the other three cases, but this is structural retention,
not measured analyst resistance or proof of a harder recovery problem.

The direct flattened recursive-source case has a jumptable Ghidra cannot fully
recover and treats an indirect jump as a call. Its inferred body covers only 107
of the symbol's 492 bytes. Reoptimized loop and recursive-source cases are inferred
as void/infinite loops despite returning normally in native executions. These six
O2/O3 records have explicit known-limit flags; their C/P-code/block comparisons
are excluded from difficulty claims. Normal padding gaps can also make inferred
bodies smaller than ELF symbols, so byte differences alone do not diagnose a
missing semantic path. No decompiler error is counted as protection.

The candidate remains opt-in. It adds substantial runtime and local code cost;
ordinary optimization and decompilation recover important parts of the flow.
No result here justifies enabling it by default or promising general survival.
Plugin SHA-256:
`5b197b2d27add349c159b612e69934f21ab91bae7847e4dde8c80c2fd6ab7aad`.
Fixture SHA-256:
`61e655d993425ecd87293e57d3c751cffe25b28bc973309f867231b6e30b735d`.
Final structured evidence and raw exports stay in `work/flatten-evaluation-final/`;
the earlier local run is diagnostic evidence preceding the ELF-symbol cost fix.
