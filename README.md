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

## Transformation contract

For a scalar integer of width `w`, both identities preserve addition modulo `2^w`:

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
