# IRVeil

[![CI](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/ci.yml/badge.svg)](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/codeql.yml/badge.svg)](https://github.com/Altitud-Studio-S-L-U/irveil/actions/workflows/codeql.yml)
[![LLVM 18](https://img.shields.io/badge/LLVM-18-262d3a?logo=llvm)](docs/design.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

IRVeil is a Clang plugin and C++ library for experimenting with obfuscation in selected C and C++ functions. Mark a function with `IRVEIL_PROTECT`, compile it with LLVM 18, and compare the program's output and generated code with an ordinary build.

The [v0.2.1 pre-release](https://github.com/Altitud-Studio-S-L-U/irveil/releases/tag/v0.2.1) rewrites integer additions. For example, it can replace `a + b` with `(a ^ b) + ((a & b) << 1)` in LLVM IR. On `main`, addition is still the default. You can also opt into experiments with branches, loops, switches, constants, strings and control-flow flattening. The [binary evaluation](#validation) shows which changes survive compilation and what they cost.

[Build](#build) · [Run the demo](#use-while-compiling-directly) · [Choose transformations](#choose-transformations) · [Integrate with CMake](docs/integration.md#integrate-an-existing-cmake-application)

## Build

Use **Linux x86-64, LLVM and Clang 18 from the same installation, C++17 and CMake 3.20+**. The build needs the LLVM development package. The tests also need Python 3.8+ and the Clang sanitizer runtimes.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DLLVM_DIR="$(llvm-config-18 --cmakedir)"
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

## Use while compiling directly

Include the header and mark the function definition. The annotation selects that function and prevents Clang from inlining it. Callees are selected only if they have their own annotation.

```cpp
#include <cstdint>
#include <irveil/Protect.h>

IRVEIL_PROTECT
std::uint32_t add_values(std::uint32_t a, std::uint32_t b) {
    return a + b;
}
```

Try both builds of the [included demo](examples/demo.cpp) from the repository root. Each executable runs the same inputs through the annotated function and prints a checksum.

```sh
clang++-18 -O2 -I include examples/demo.cpp -o build/demo-ordinary
clang++-18 -O2 -I include -fpass-plugin=./build/IRVeilPass.so \
  examples/demo.cpp -o build/demo
./build/demo-ordinary 10000
./build/demo 10000
```

Each build prints `f78085e317c84659`. To inspect the LLVM instructions before code generation, add `-S -emit-llvm` to the plugin compilation command and change the output path to `build/demo.ll`.

## Choose transformations

| Selection | What happens in a marked function |
| --- | --- |
| Default (`arithmetic`) | Rewrite up to 256 original scalar integer additions of width 2–64 bits. |
| `profile=general` | Also rewrite eligible subtractions, bitwise operations, integer comparisons and conditional branches. |
| `transforms=...` | Choose the exact families to run, joined by `+`. This list replaces the profile. Use `none` to disable all transforms. |

The experimental selections below are available when building from `main`.

| Family | What to expect |
| --- | --- |
| `adds`, `sub`, `bitwise`, `cmp`, `branches` | Select the instruction rewrites individually. LLVM can simplify the resulting expressions. |
| `cfg`, `loops` | Route branch edges or loop backedges through extra blocks. The backend can remove those blocks. |
| `switch` | Turn eligible switches into chains of comparisons. Large chains can cost more than a jump table. |
| `constants`, `strings` | Split integer literals or encode private byte strings read through eligible byte loads. String keys and decoded bytes remain visible. |
| `flatten` | Route eligible blocks through a dispatcher. Preserving values across blocks can add stack traffic and runtime overhead. |

### Bounded flattening experiment

This example applies only flattening to the [loop and PHI fixture](tests/fixtures/flatten.ll) and asks LLVM to verify the result. Look for `irveil.flatten.dispatch` in the marked function in `build/flatten.ll`.

```sh
opt-18 -load-pass-plugin=./build/IRVeilPass.so \
  '-passes=irveil<transforms=flatten;seed=42>' -verify-each \
  -S tests/fixtures/flatten.ll -o build/flatten.ll
```

The default limits are **16 dispatched blocks and 256 net additional IR instructions per function**. Flattening checks both before modifying a function and skips unsupported control flow, calls and spill types. The limits apply to LLVM IR. The [configuration reference](docs/integration.md#configuration-reference) and [flattening contract](docs/design.md#bounded-flattening-experiment) cover the options, units and exclusions.

## Integrate with an application

| Entry point | How to use it |
| --- | --- |
| [CMake target](docs/integration.md#integrate-an-existing-cmake-application) | Apply `irveil_protect_target` to a target compiled with Clang 18. The application does not need to link LLVM. |
| [LLVM IR](docs/integration.md#use-on-llvm-ir) | Run the plugin with `opt-18` on an annotated module, then compile the output to a native executable. |
| [C++ library](docs/integration.md#embed-the-library) | Link `IRVeil::Core` and call `irveil::applyObfuscation` on an `llvm::Module`. |

## Transformation contract

For defined source executions, the rewrites are designed to preserve observable behavior. The arithmetic pass freezes operands before reusing them and computes modulo the original integer width. Replacing one addition adds at most five net IR instructions. A processed function is skipped on subsequent runs. Start from fresh input IR to compare seeds or configurations. See the [semantic arguments and expansion bounds](docs/design.md).

## Validation

LLVM 18 Debug and Release tests cover arithmetic identities, PHIs, control flow, memory effects, concurrent calls and installed consumers. The separate Ghidra study compares stripped binaries with ordinary builds and records cases where the decompiler inferred the wrong control flow or return type.

On the synthetic flattening corpus, all six O2/O3 variants agreed on 633 output rows, including the resulting memory values. Flattening five functions took **2.38× the ordinary runtime at O2 and 2.15× at O3**. Reoptimization removed the dispatcher from two functions. In a follow-up, lowering the block limit to five kept only those two functions eligible and reduced the measured overhead to 4.3% at O2 and 5.3% at O3. Ghidra recovered many of the original conditions. Human analyst effort remains unmeasured. [Results](docs/re-evaluation.md#bounded-flattening-experiment) · [Cost comparison](docs/re-evaluation.md#reducing-the-cost-of-flattening) · [Reproduction protocol](docs/re-validation.md)

## Project

Created by [Altitud Studio](https://altitudstudio.ad/es/codigo-abierto/) and released under the [MIT license](LICENSE). See the [changelog](CHANGELOG.md), [contributing guide](CONTRIBUTING.md) and [security reporting policy](SECURITY.md).
