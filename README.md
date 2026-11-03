# IRVeil

```text
 ___ ____  __     __   _ _
|_ _|  _ \ \ \   / /__(_) |
 | || |_) | \ \ / / _ \ | |
 | ||  _ <   \ V /  __/ | |
|___|_| \_\   \_/ \___|_|_|
```

**Selective LLVM obfuscation for C and C++.** A C++ library and compiler plugin that replace integer additions in explicitly marked functions with equivalent mixed boolean/arithmetic expressions.

IRVeil provides selective arithmetic diversification with explicit transformation bounds and reproducible compiler and Ghidra evaluations. The current transformation does not establish resistance against a skilled reverse engineer. An analyst can recover, simplify or patch the distributed executable. Seeds are public reproducibility inputs; embedded credentials and runtime values remain recoverable.

## Build

Initial support: **Linux x86-64, LLVM/Clang 18, C++17, CMake 3.20+**. Python 3.8+ runs the local checks. Use compiler, LLVM development headers/libraries and tools from the same LLVM installation. Other versions, platforms, GCC/MSVC, LTO and Go builds are outside the initial compatibility contract.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DLLVM_DIR="$(llvm-config-18 --cmakedir)"
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

Configuration does not download dependencies. This repository deliberately has no CI/CD workflows; checks run locally.

## Use while compiling

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

## Use on LLVM IR

```sh
clang++-18 -O2 -I include -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-18 -load-pass-plugin=./build/IRVeilPass.so \
  '-passes=irveil<seed=42;max-adds=64>' -verify-each \
  -S build/demo.ll -o build/demo.veiled.ll
clang++-18 build/demo.veiled.ll -o build/demo-from-ir
```

This is a post-frontend step over LLVM IR, before native code generation. The plugin does not rewrite an existing ELF, PE or Mach-O executable. Keep annotations in the input IR; previously compiled native object files are not transformed.

## Embed the library

The static target exposes `irveil::applyObfuscation(llvm::Module&, irveil::Config)` and returns `llvm::Expected<irveil::Statistics>`. Its counters describe selected functions, changed functions and rewritten additions. A cap outside `1..4096` returns a recoverable error before mutation.

```sh
cmake --install build --prefix "$PWD/build/install"
```

The [standalone consumer](examples/library-consumer) loads LLVM IR, calls the library, verifies the result and writes the transformed IR to standard output. Its CMake project links only the exported target:

```cmake
find_package(IRVeil 0.2 CONFIG REQUIRED)
add_executable(irveil-consumer main.cpp)
target_link_libraries(irveil-consumer PRIVATE IRVeil::Core)
```

Configure it against the installation prefix, then run it from the repository root:

```sh
cmake -S examples/library-consumer -B build/consumer \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$PWD/build/install" \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DLLVM_DIR="$(llvm-config-18 --cmakedir)"
cmake --build build/consumer --parallel 2
clang++-18 -O2 -I build/install/include -S -emit-llvm examples/demo.cpp -o build/input.ll
./build/consumer/irveil-consumer build/input.ll > build/transformed.ll
clang++-18 build/transformed.ll -o build/consumer-demo
./build/consumer-demo
```

The example uses the default seed and cap; counters go to standard error. Parsing, verification or library errors return a nonzero status without writing a result module.

The API depends on LLVM 18 C++ types and is not a stable cross-version LLVM ABI. Installed consumers still need the matching LLVM development package. Enable C as well as C++ in the consumer because LLVM's package configuration checks C dependencies.

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

The local suite checks integration through `clang` and `opt`, the library API, selection, deterministic configuration, expansion caps, repeat-run behavior and invalid options. It also installs the package into a temporary prefix, relocates that prefix, and builds and runs the standalone consumer through `find_package` outside the source tree with the same LLVM installation. Arithmetic checks cover exhaustive small-width inputs and reproducible boundary/random inputs at larger widths. Native fixture outputs are compared with ordinary builds. Structural IR verification and execution tests provide different evidence; neither alone proves equivalence for every possible C++ program.

Measure the included synthetic fixture, including a stripping-only baseline:

```sh
python3 tools/measure.py --plugin build/IRVeilPass.so \
  --llvm-bin "$(llvm-config-18 --bindir)" --output work/measurement.json
```

The command compares outputs and records native instruction counts, executable sizes, compile observations and paired execution times. It runs the owned example program; instruction growth is not a measure of RE resistance. Review the workload and environment recorded in the JSON before interpreting timings.

The [Ghidra and LLVM evaluation](docs/re-evaluation.md) compares ordinary, v0.1 and v0.2 builds at O2/O3. It records the eliminated LLVM simplification and the counterevidence: the expressions remain readable in Ghidra and their algebra is recoverable. The experiment does not demonstrate increased resistance to Ghidra or a human analyst.

The durable scope and acceptance criteria are in [the design contract](docs/design.md) and [the reverse-engineering evaluation protocol](docs/re-validation.md). No measured percentage of RE resistance or universal performance guarantee is claimed.

## Project

Created by [Altitud Studio](https://altitudstudio.ad/es/codigo-abierto/). Source is available under the [MIT license](LICENSE). Changes go through pull requests; see [contributing](CONTRIBUTING.md). Report security concerns privately using [the security policy](SECURITY.md).

See the [changelog](CHANGELOG.md) for release changes.
