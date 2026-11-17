# IRVeil

[![CI](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/ci.yml/badge.svg)](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/codeql.yml/badge.svg)](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/codeql.yml)
[![LLVM 18](https://img.shields.io/badge/LLVM-18-262d3a?logo=llvm)](docs/design.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Selective LLVM transformations for C and C++: diversify integer additions in explicitly marked functions.**

IRVeil is a C++ library and compiler plugin for experiments with bounded arithmetic obfuscation. Mark a function with `IRVEIL_PROTECT`; eligible additions in that function are replaced with equivalent mixed boolean/arithmetic expressions.

```text
Input:       a + b
Equivalent:  (a XOR b) + ((a AND b) << 1)
Scope:       annotated functions, scalar integers of 2–64 bits
```

This illustrates the arithmetic identity, not a guaranteed native instruction sequence. Seeds make transformations reproducible; they are not secrets. The current evaluation does **not** demonstrate increased resistance to Ghidra or a human analyst, and embedded credentials remain recoverable. See the [evaluation](docs/re-evaluation.md).

**Start here:** [build](#build) · [mark a function](#use-while-compiling-directly) · [CMake integration](docs/integration.md#integrate-an-existing-cmake-application) · [transformation contract](#transformation-contract)

## Build

Initial support: **Linux x86-64, LLVM/Clang 18, C++17, CMake 3.20+**. Python 3.8+ runs the local checks. Use compiler, LLVM development headers/libraries and tools from the same LLVM installation. Other versions, platforms, GCC/MSVC, LTO and Go builds are outside the initial compatibility contract.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DLLVM_DIR="$(llvm-config-18 --cmakedir)"
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

Configuration does not download dependencies. Every pull request runs this build and CTest in Release and Debug on Ubuntu 24.04 with Clang/LLVM 18 from the distribution's packages, and a CodeQL scan of the C++, Python and Java sources.

## Integrate an existing CMake application

The installed CMake helper applies the plugin to one target without linking LLVM into your application. See the [CMake integration and two-target example](docs/integration.md#integrate-an-existing-cmake-application), including supported targets, configuration ranges and compatibility limits.

## Use while compiling directly

Mark the functions you want to transform:

```cpp
#include <cstdint>
#include <irveil/Protect.h>

IRVEIL_PROTECT
std::uint32_t add_values(std::uint32_t a, std::uint32_t b) {
    return a + b;
}
```

```sh
clang++-18 -O2 -I include -fpass-plugin=./build/IRVeilPass.so \
  examples/demo.cpp -o build/demo
./build/demo
```

`IRVEIL_PROTECT` adds a Clang annotation and prevents inlining of that function. It does not select its callees. The plugin runs at the optimizer-last extension point using seed `0` and a cap of `256` additions per selected function. Inspect the final binary: later code generation can simplify expressions, and an IR change alone does not prove increased analysis difficulty.

For direct configuration, load the same plugin early so Clang can parse its
`-mllvm` options. The CMake helper supplies this flag sequence:

```sh
clang++-18 -O2 -I work/install/include \
  -Xclang -load -Xclang "$PWD/work/install/lib/irveil/IRVeilPass.so" \
  -fpass-plugin="$PWD/work/install/lib/irveil/IRVeilPass.so" \
  -mllvm -irveil-seed=42 -mllvm -irveil-max-adds=2 -mllvm -irveil-report \
  -S -emit-llvm work/application/main.cpp -o work/protected.ll
```

This emits final optimizer IR before machine-code generation. LLVM symbol names
and `"irveil.processed"` identify processed functions. Remove `-S -emit-llvm` and
choose an executable output for native compilation. The path assumes the default
`CMAKE_INSTALL_LIBDIR=lib`; adjust it if configured differently. Invalid direct
options fail compilation with their name and range. The explicit `opt` pipeline
below has its own configuration and does not inherit these Clang options.

## Use on LLVM IR

The plugin can also transform an LLVM IR module through `opt-18`. See the [explicit IR pipeline](docs/integration.md#use-on-llvm-ir). It does not rewrite existing native executables.

## Embed the library

Use `IRVeil::Core` to call `irveil::applyObfuscation` from another C++ application. See the [standalone library consumer](docs/integration.md#embed-the-library). Consumers require the matching LLVM 18 development package; there is no stable cross-version LLVM ABI.

## Experimental general profile (opt-in)

The default profile remains the released arithmetic-only behavior. The
experimental `general` profile additionally rewrites selected scalar integer
`sub`, `and`, `or`, `xor`, integer comparisons (`icmp`), and conditional
branches with distinct successors. It preserves branch destinations by swapping
the targets when inverting the condition. The profile is bounded by the same
per-function instruction count setting (named `max-adds` for compatibility).

Use the general profile explicitly with `opt`:

```sh
opt-18 -load-pass-plugin ./build/IRVeilPass.so \
  '-passes=irveil<profile=general;seed=42;max-adds=32>' \
  -S input.ll -o output.ll
```

Or when compiling C/C++ via Clang:

```sh
clang++-18 -O2 -I include \
  -Xclang -load -Xclang ./build/IRVeilPass.so \
  -fpass-plugin=./build/IRVeilPass.so \
  -mllvm -irveil-profile=general \
  examples/demo.cpp -o build/demo-general
```

Unsupported instructions and values outside the documented scalar widths are
left unchanged. Instructions are snapshotted before mutation, and only the
selected functions are transformed. These rewrites are for semantic and
compiler-architecture experiments: trivial inverse-comparison and De Morgan
identities may be optimized away or recovered instantly by a decompiler.
They are **not** a demonstrated increase in reverse-engineering resistance.
Inspect the final binary and independently compare its behavior before claiming
any protection. The profile defaults remain unchanged; additional families require
an explicit `transforms` list, which replaces the profile selection:

```sh
opt-18 -load-pass-plugin ./build/IRVeilPass.so \
  '-passes=irveil<transforms=cfg+loops+switch+constants+strings;seed=42;max-edges=16;max-switch-cases=32;max-constants=16;max-string-bytes=1024>' \
  -verify-each -S input.ll -o output.ll
```

| Family | Supported transformation and trade-off |
| --- | --- |
| `adds`, `sub`, `bitwise`, `cmp`, `branches` | Existing bounded instruction identities, scalar integer widths 2..64; conditional branch inversion also swaps profile weights |
| `cfg` | Route ordinary non-backedge branch edges through new blocks; one extra jump per edge in IR, often removed by the backend |
| `loops` | Route natural backedges identified by dominators; PHIs and loop metadata follow the new predecessor; no loop unrolling or state dispatcher |
| `switch` | Freeze the condition once, then emit an equality ladder with repaired PHIs, including repeated destinations; linear comparisons can cost more than a jump table |
| `constants` | Split original integer literals into two XOR operands in arithmetic, integer comparisons and returns; one extra IR instruction per operand, readily constant-folded |
| `strings` | XOR private constant C byte arrays and decode each ordinary scalar `i8` load; requires all uses to end in selected functions, with no escaping pointers, calls, aliases, wide/atomic/volatile loads or mutable storage |
| `flatten` | Experimental whole-function SSA dispatcher for a restricted branch CFG; spills crossing registers/PHIs to private stack slots, with preflight block/instruction limits; additional memory traffic and dispatch overhead can be substantial |

Use `transforms=none` to disable work. Unknown/repeated families and malformed or
out-of-range options are rejected before mutation. `max-adds` (1..4096, default
256) bounds original instruction rewrites and, independently, the number of
lowered switches. CFG and loop edges share `max-edges` (1..256, default 32).
Switch cases share `max-switch-cases` per function (1..256, default 64); an entire
switch is skipped if it does not fit. Literal operands share `max-constants`
(1..4096, default 32). String bytes, including terminators, share
`max-string-bytes` per module (1..65536, default 4096). Decoded byte loads share
`max-string-loads` per module (1..65536, default 4096), independently of byte count.
A global is skipped without changing its initializer or any reader if all its
loads do not fit the remaining budget. This bounds string instruction growth even
when a small array has many readers.

Clang accepts matching `-mllvm -irveil-transforms=...`, `-irveil-max-edges`,
`-irveil-max-switch-cases`, `-irveil-max-constants`, `-irveil-max-string-bytes`
and `-irveil-max-string-loads`
options with the same early DSO load shown above. The installed CMake helper
accepts `PROFILE`, `TRANSFORMS`, `MAX_EDGES`, `MAX_SWITCH_CASES`, `MAX_CONSTANTS`,
`MAX_STRING_BYTES` and `MAX_STRING_LOADS` alongside the existing options. For example:

```cmake
irveil_protect_target(app TRANSFORMS cfg+loops+switch+constants+strings
  MAX_EDGES 16 MAX_SWITCH_CASES 32 MAX_CONSTANTS 16
  MAX_STRING_BYTES 1024 MAX_STRING_LOADS 256 REPORT)
```

Local structural rewrites skip functions with EH/personality, address-taken blocks,
indirect control flow, presplit coroutines or restricted calls. The `cfg`/`loops`
families provide local CFG diversification. Flattening has its own subset below. String
decoding preserves static lifetime without writable shared initialization, but
keys and decoded bytes remain observable. Calls such as `puts`/`strlen` cause a
string to be skipped. Counters report actual IR work, not final-binary survival.
See the [experimental contract](docs/design.md#experimental-modular-framework)
and [framework evaluation](docs/re-evaluation.md#experimental-framework-evaluation).

### Bounded flattening experiment

Enable only with `transforms=flatten` (or an explicit list containing it). Neither
profile enables it by default. `max-flatten-blocks` caps dispatched blocks after
critical-edge splitting (1..64, default 16); `max-flatten-instructions` caps a
conservative upper bound on net IR instruction growth (1..4096, default 256).
An unsupported or over-budget function is skipped before flattening mutates it.
The equivalent Clang flags are `-irveil-max-flatten-blocks` and
`-irveil-max-flatten-instructions`; CMake accepts `MAX_FLATTEN_BLOCKS` and
`MAX_FLATTEN_INSTRUCTIONS`.

```sh
opt-18 -load-pass-plugin ./build/IRVeilPass.so \
  '-passes=irveil<transforms=flatten;seed=42;max-flatten-blocks=16;max-flatten-instructions=256>' \
  -verify-each -S input.ll -o output.ll
```

The initial subset has at least two non-entry blocks, a branching entry, only
branch/return/unreachable terminators, no unreachable blocks or duplicate branch
successors, and only scalar integers up to 64 bits or address-space-zero pointers
requiring spills. Entry definitions keep their dominance; other escaping values
and PHIs use LLVM 18's register-to-memory utilities. A state PHI and switch route
the original blocks without reordering their observable operations. No globals,
runtime calls or volatile accesses are added. Private spills are ordinary memory.

EH, block addresses, GC, varargs/non-C calling conventions, naked functions,
dynamic/non-entry/inalloca allocas, preallocated/inalloca parameters,
indirect/inline-asm/non-C/restricted calls, `musttail`, stack/frame/register queries
and manipulation and experimental/coroutine/EH/varargs intrinsics exclude the function. Input
switches are skipped unless `switch` is explicitly enabled to lower them first.
Flattening runs after the other structural families and never rewrites its own
dispatcher in that run. Its budgets apply to that current CFG, independently of
earlier families. Reports separate unsupported/budget skips and actual changes.
Generated dispatch branches do not inherit obsolete loop/profile metadata.

Reoptimization can promote spills or recover control flow. This experiment has
no anti-optimization, anti-debug or universal-survival guarantee. The detailed
[flattening contract](docs/design.md#bounded-flattening-experiment) defines the
semantic argument, exclusions and exact preflight bound.
The [measured experiment](docs/re-evaluation.md#bounded-flattening-experiment)
records native/reoptimized survival, Ghidra recovery and partial-analysis limits,
and roughly 2.2–2.4x runtime on its synthetic workload. It does not justify a
default change or a general resistance claim.

## Transformation contract

For the default arithmetic profile, both identities preserve scalar integer
addition modulo `2^w`:

```text
a + b = (a XOR b) + ((a AND b) << 1)
a + b = ((a OR b) << 1) - (a XOR b)
```

Operands are frozen before reuse to handle LLVM `undef` semantics. Arithmetic overflow flags are not copied to the replacement. This preserves results for defined input executions; it does not fix undefined behavior in the source.

| Boundary | v0.2 behavior |
| --- | --- |
| Selection | Defined functions annotated `irveil`; no transitive selection |
| Operations | Scalar integer `add`, widths 2 through 64 |
| Exclusions | Vectors, `i1`, wider integers and other opcodes |
| Work cap | At most `max-adds` original additions per selected function |
| IR growth | At most five net instructions per rewritten addition |
| Repeat runs | A processed function is not expanded again |
| Reproducibility | Same IR, configuration and toolchain produce the same transformation |

Version 0.2 replaces the OR/AND identity from v0.1, which LLVM 18 InstCombine simplifies directly to an addition. The algebra remains publicly recognizable; avoiding that particular compiler rewrite does not prevent an analyst from recovering the addition. Seeded output is version-dependent. Generate fresh IR from source when comparing versions: the processed-function marker deliberately prevents re-expansion, including with another seed or version.

The choice of identity uses FNV-1a over the LLVM function name, XOR with the configured seed, followed by SplitMix64 for each eligible addition in IR order. This is deterministic diversification, not cryptography.

With `A` annotations, `I` inspected instructions, `K` rewritten additions, `U` operand uses updated and `L` bytes of function names hashed, the coordination work is `O(A + I + K + U + L)`, aside from LLVM container internals. Replacing an instruction visits its users even when the candidate cap ends the scan early. Auxiliary space is `O(A + K)`. These bounds exclude the rest of the compiler and do not predict machine-code size or runtime overhead.

## Validation

The local suite checks integration through `clang` and `opt`, the library API, selection, deterministic configuration, expansion caps, repeat-run behavior and invalid options. It installs and relocates the package, then builds and runs both the library consumer and the two-target compiler consumer outside the source tree. Compiler consumption includes C-only and C++-only applications with LLVM package discovery disabled. Arithmetic checks cover exhaustive small-width inputs and reproducible boundary/random inputs at larger widths. Native fixture outputs are compared with ordinary builds. Structural IR verification and execution tests provide different evidence; neither alone proves equivalence for every possible C++ program.

Measure the included synthetic fixture, including a stripping-only baseline:

```sh
python3 tools/measure.py --plugin build/IRVeilPass.so \
  --llvm-bin "$(llvm-config-18 --bindir)" --output work/measurement.json
```

The command compares outputs and records native instruction counts, executable sizes, compile observations and paired execution times. It runs the owned example program; instruction growth is not a measure of RE resistance. Review the workload and environment recorded in the JSON before interpreting timings.

The [Ghidra and LLVM evaluation](docs/re-evaluation.md) compares ordinary, v0.1 and v0.2 builds at O2/O3. It records the eliminated LLVM simplification and the counterevidence: the expressions remain readable in Ghidra and their algebra is recoverable. The experiment does not demonstrate increased resistance to Ghidra or a human analyst.

The extended evaluation applies pinned SiMBA and GAMBA attacks to expressions
extracted from the v0.2.0 native artifacts, with separate recovered, unsupported,
timeout and error outcomes. The [recovery protocol](docs/re-validation.md#simba-recovery-protocol)
contains the optional tool setup, limits and commands; these tools are not build
dependencies. Experimental transformations are evaluated separately from the
released algorithm.

The durable scope and acceptance criteria are in [the design contract](docs/design.md) and [the reverse-engineering evaluation protocol](docs/re-validation.md). No measured percentage of RE resistance or universal performance guarantee is claimed.

## Project

Created by [Altitud Studio](https://altitudstudio.ad/es/codigo-abierto/). Source is available under the [MIT license](LICENSE). Changes go through pull requests; see [contributing](CONTRIBUTING.md). Report security concerns privately using [the security policy](SECURITY.md).

See the [changelog](CHANGELOG.md) for release changes.
