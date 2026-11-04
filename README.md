# IRVeil

```text
 ___ ____  __     __   _ _
|_ _|  _ \ \ \   / /__(_) |
 | || |_) | \ \ / / _ \ | |
 | ||  _ <   \ V /  __/ | |
|___|_| \_\   \_/ \___|_|_|
```

**Selective LLVM obfuscation for C and C++.** A C++ library and compiler plugin that replace integer additions in explicitly marked functions with equivalent mixed boolean/arithmetic expressions.

IRVeil aims to make reverse engineering harder through selective, bounded transformations at the LLVM IR level. The current release provides arithmetic diversification, with reproducible compiler and reverse-engineering evaluations guiding further improvements. Seeds control reproducibility; they are not secrets, and embedded credentials and runtime values remain recoverable.

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

## Integrate an existing CMake application

Install the build above:

```sh
cmake --install build --prefix "$PWD/work/install"
```

In your application's `CMakeLists.txt`, after creating its target:

```cmake
find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)
add_executable(my-app main.cpp)
irveil_protect_target(my-app SEED 42 MAX_ADDS 64 REPORT)
```

Mark function definitions with `IRVEIL_PROTECT` as shown below. Configure the
application with Clang 18 and `-DCMAKE_PREFIX_PATH=/absolute/path/to/work/install`.
The `Plugin` component supplies the header and compiler plugin without linking
`IRVeil::Core` or LLVM into the application or finding LLVM's development package.
The plugin still requires the matching LLVM runtime used to build it.
`IRVeil::Pass` locates the installed module; `IRVeil::Headers` exposes the header.

`irveil_protect_target(target [SEED N] [MAX_ADDS N] [REPORT])` changes only that
target's C/C++ compilation. Call it once after declaring a local executable,
static/shared/module library or object library. Only annotated definitions are
selected; other targets, callees and linked dependencies are independent.

| Option | Default | Accepted values |
| --- | --- | --- |
| `SEED` | `0` | Unsigned decimal integer, `0..18446744073709551615` |
| `MAX_ADDS` | `256` | Original additions per selected function, `1..4096` |
| `REPORT` | Off | Flag; print configuration and module counters to stderr |

Unknown, repeated, missing and out-of-range options fail during CMake
configuration with an IRVeil diagnostic. Leading decimal zeros are accepted.
Reports show `selected`, `changed` and `rewritten-adds` when a source is compiled.
A selected function may have no eligible additions after Clang optimization.
Inspect native output to check what survived codegen; reports alone show IR work.

Compatibility remains Linux x86-64, Clang/LLVM 18 and CMake 3.20+. C-only and
C++-only applications are supported. GCC/MSVC and LTO are outside the contract;
the helper rejects visible CMake IPO settings. Sources added later or through
generator expressions must also use Clang 18. Manually adding `-flto` remains
outside the contract. Clang's `-save-temps` is not supported with these options:
its assembler invocation rejects the plugin's LLVM flags, and its saved bitcode
precedes the pass. Use explicit IR emission below.

### Repeat the two-target example

Starting at the repository root after installation, copy the independent
[C++ application example](examples/cmake-consumer) and build both targets normally:

```sh
mkdir -p work
cp -R examples/cmake-consumer work/application
cmake -S work/application -B work/application-build \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$PWD/work/install" \
  -DCMAKE_CXX_COMPILER=clang++-18 -DENABLE_IRVEIL=OFF
cmake --build work/application-build --parallel 2
./work/application-build/ordinary-app 4294967295 1
./work/application-build/protected-app 4294967295 1
llvm-objdump-18 -d --no-show-raw-insn --disassemble-symbols=protected_calculation \
  work/application-build/protected-app > work/normal.asm

# Only protected-app receives IRVeil after reconfiguration.
cmake -S work/application -B work/application-build \
  -DENABLE_IRVEIL=ON -DIRVEIL_SEED=42 -DIRVEIL_MAX_ADDS=2
cmake --build work/application-build --parallel 2
./work/application-build/ordinary-app 4294967295 1
./work/application-build/protected-app 4294967295 1
llvm-objdump-18 -d --no-show-raw-insn --disassemble-symbols=protected_calculation \
  work/application-build/protected-app > work/protected.asm
diff -u work/normal.asm work/protected.asm
```

All four executions must agree. The protected build reports
`seed=42 max-adds=2 selected=1 changed=1 rewritten-adds=2`. The diff should return
status 1 because the selected function changed. Inspect `ordinary_calculation`
and `ordinary-app` as controls. In the LLVM 18.1.3 acceptance run, the selected
function grew from 12 to 20 native instructions, excluding alignment; the ordinary
function stayed at 12 and `ordinary-app` remained byte-identical. These are
fixture observations, not resistance scores.

An invalid configuration fails before compilation:

```sh
cmake -S work/application -B work/application-build -DIRVEIL_MAX_ADDS=0
# IRVeil MAX_ADDS must be between 1 and 4096; got '0'
cmake -S work/application -B work/application-build -DIRVEIL_MAX_ADDS=2
```

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

The local suite checks integration through `clang` and `opt`, the library API, selection, deterministic configuration, expansion caps, repeat-run behavior and invalid options. It installs and relocates the package, then builds and runs both the library consumer and the two-target compiler consumer outside the source tree. Compiler consumption includes C-only and C++-only applications with LLVM package discovery disabled. Arithmetic checks cover exhaustive small-width inputs and reproducible boundary/random inputs at larger widths. Native fixture outputs are compared with ordinary builds. Structural IR verification and execution tests provide different evidence; neither alone proves equivalence for every possible C++ program.

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
