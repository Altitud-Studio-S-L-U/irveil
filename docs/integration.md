# Compiler and library integration

[Back to the project overview](../README.md). Commands run from the repository root unless stated otherwise.

This guide describes `main`. The v0.2.1 prerelease supports annotated arithmetic
through Clang, the static C++ library and the `opt` pipeline with `seed` and
`max-adds`. Build from `main` for the per-target CMake helper, configurable
Clang flags and experimental transform families. [v0.2.1 documentation](https://github.com/Altitud-Studio-S-L-U/irveil/blob/v0.2.1/README.md).

## Integrate an existing CMake application

First complete the [build steps](../README.md#build), then install:

```sh
cmake --install build --prefix "$PWD/work/install"
```

In your application's `CMakeLists.txt`, after creating its target:

```cmake
find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)
add_executable(my-app main.cpp)
irveil_protect_target(my-app SEED 42 MAX_ADDS 64 REPORT)
```

Mark function definitions with [`IRVEIL_PROTECT`](../README.md#use-while-compiling-directly). Configure the
application with Clang 18 and `-DCMAKE_PREFIX_PATH=/absolute/path/to/work/install`.
The `Plugin` component supplies the header and compiler plugin without linking
`IRVeil::Core` or LLVM into the application or finding LLVM's development package.
The plugin still requires the matching LLVM runtime used to build it.
`IRVeil::Pass` locates the installed module; `IRVeil::Headers` exposes the header.

Call `irveil_protect_target(target [options...])` once after declaring a local executable,
static/shared/module library or object library. Only annotated definitions are
selected. Compile options and annotation headers are private to the target.

Compatibility remains Linux x86-64, Clang/LLVM 18 and CMake 3.20+. C-only and
C++-only applications are supported. GCC/MSVC and LTO are outside the contract;
the helper rejects visible CMake IPO settings. Sources added later or through
generator expressions must also use Clang 18. Manually adding `-flto` remains
outside the contract. Clang's `-save-temps` is not supported with these options:
its assembler invocation rejects the plugin's LLVM flags, and its saved bitcode
precedes the pass. To inspect the transformed IR, use the command under [Direct Clang options](#direct-clang-options).

### Configuration reference

Each CMake option takes the next argument as its value, except the standalone
`REPORT` flag. In an `opt` pipeline use the key in the second column. In Clang,
pass `-mllvm -irveil-<key>=<value>` for each valued option.

| CMake option | Pipeline key | Default | Accepted values and scope |
| --- | --- | --- | --- |
| `PROFILE` | `profile` | `arithmetic` | `arithmetic` selects `adds`. Experimental `general` selects `adds+sub+bitwise+cmp+branches`. |
| `TRANSFORMS` | `transforms` | From profile | A `+`-separated list of distinct families, or `none` to disable all. An explicit list replaces the profile selection. |
| `SEED` | `seed` | 0 | Unsigned decimal `0..18446744073709551615`. Use the same seed and tool version to reproduce a run. |
| `MAX_ADDS` | `max-adds` | 256 | `1..4096`. Caps total original instruction rewrites per function. Independently caps the number of lowered switches per function. |
| `MAX_EDGES` | `max-edges` | 32 | `1..256`. Shared budget per function for `cfg` routes and `loops` backedges. |
| `MAX_SWITCH_CASES` | `max-switch-cases` | 64 | `1..256`. Total lowered cases per function. Skip a whole switch if it exceeds the remaining budget. |
| `MAX_CONSTANTS` | `max-constants` | 32 | `1..4096`. Original integer literal operands split per function. |
| `MAX_STRING_BYTES` | `max-string-bytes` | 4096 | `1..65536`. Total encoded bytes per module, including terminators. |
| `MAX_STRING_LOADS` | `max-string-loads` | 4096 | `1..65536`. Total decoded byte-load instructions per module, independent of the byte budget. |
| `MAX_FLATTEN_BLOCKS` | `max-flatten-blocks` | 16 | `1..64`. Dispatched non-entry blocks per function, including critical-edge splits. |
| `MAX_FLATTEN_INSTRUCTIONS` | `max-flatten-instructions` | 256 | `1..4096`. Conservative upper bound on net IR instructions added by flattening per function. |
| `REPORT` | — | Off | Print configuration and module counters on stderr. In Clang use `-mllvm -irveil-report`. |

The complete vocabulary is `adds`, `sub`, `bitwise`, `cmp`, `branches`, `cfg`,
`loops`, `switch`, `constants`, `strings`, and `flatten`. For example, to route
up to eight ordinary edges or natural backedges and split up to four literals:

```cmake
irveil_protect_target(my-app TRANSFORMS cfg+loops+constants MAX_EDGES 8 MAX_CONSTANTS 4 REPORT)
```

CMake rejects unknown or repeated options, missing values and limits outside
the table ranges at configure time. Use decimal integers. `strings` requires
all readers of a private constant C byte array to be eligible and to fit both
module budgets. It skips modules with nonempty assembly text because assembly
can observe symbols outside the LLVM use graph. `flatten` checks the whole
function before modifying it. Its limits apply after earlier selected structural
passes. To lower input switches first, select `switch+flatten`. For supported
control flow, spill types, calling conventions and exclusions, see the
[transform contracts](design.md#experimental-modular-framework).

Reports count annotated definitions (`selected`) and functions modified in this
run (`changed`). A previously processed function counts toward `selected`
even when `changed` is zero. Per-family counters include
`rewritten-adds`, `sub`, `bitwise`, `cmp`, `branches`, `cfg-edges`, `loop-edges`,
`switches`, `constants`, `strings`, `string-bytes` and `decoded-string-loads`.
For flattening, compare `flattened`, `flatten-blocks`, `flatten-spills` and
`flatten-added` with `flatten-skipped-unsupported` and `flatten-skipped-budget`.
These are IR counts. Inspect the native symbol to see which changes survived code generation.

### Direct Clang options

With the plugin defaults, `-fpass-plugin` registers the optimizer-last pass.
For custom settings, load the same module early with `-Xclang -load` so Clang
recognizes its `-mllvm` options. This example writes IR and prints the counters:

```sh
plugin="$PWD/build/IRVeilPass.so"
clang++-18 -O2 -I include -Xclang -load -Xclang "$plugin" -fpass-plugin="$plugin" \
  -mllvm -irveil-profile=general -mllvm -irveil-seed=42 -mllvm -irveil-max-adds=32 \
  -mllvm -irveil-report -S -emit-llvm examples/demo.cpp -o build/demo-general.ll
```

For a native build, omit `-S -emit-llvm` and give the executable a distinct output name.
When using an installed plugin, use its installed module path and header directory.

### Repeat the two-target example

Starting at the repository root after installation, copy the independent
[C++ application example](../examples/cmake-consumer) and build both targets normally:

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

## Use on LLVM IR

```sh
clang++-18 -O2 -I include -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-18 -load-pass-plugin=./build/IRVeilPass.so \
  '-passes=irveil<seed=42;max-adds=64>' -verify-each \
  -S build/demo.ll -o build/demo.veiled.ll
clang++-18 build/demo.veiled.ll -o build/demo-from-ir
```

The explicit pipeline accepts `irveil` for defaults or
`irveil<key=value;key=value>` for settings from the configuration table. Quote
the pipeline so the shell passes the semicolons through. For example, replace
the pipeline argument above with
`'-passes=irveil<transforms=switch+flatten;max-flatten-blocks=5>'` to limit
flattening to five dispatched blocks. The explicit pipeline reads its own
settings independently of the Clang flags. Its input must be LLVM IR containing
the annotations, before native code generation.

## Embed the library

The static target exposes `irveil::applyObfuscation(llvm::Module&, irveil::Config)`
and returns `llvm::Expected<irveil::Statistics>`. Set `Config::profile` or assign
a bitmask to `Config::transforms` for explicit selection. Invalid masks, profiles
and limits return a recoverable error before module mutation. The configuration
and statistics fields are declared in the [public header](../include/irveil/Pass.h).

```sh
cmake --install build --prefix "$PWD/build/install"
```

The [standalone consumer](../examples/library-consumer) loads LLVM IR, calls the library, verifies the result and writes the transformed IR to standard output. Its CMake project links only the exported target:

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
