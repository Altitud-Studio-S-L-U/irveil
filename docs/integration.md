# Compiler and library integration

[Back to the project overview](../README.md). Commands run from the repository root unless stated otherwise.

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
precedes the pass. Use the explicit IR emission command in the [direct compiler instructions](../README.md#use-while-compiling-directly).

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

This is a post-frontend step over LLVM IR, before native code generation. The plugin does not rewrite an existing ELF, PE or Mach-O executable. Keep annotations in the input IR; previously compiled native object files are not transformed.

## Embed the library

The static target exposes `irveil::applyObfuscation(llvm::Module&, irveil::Config)` and returns `llvm::Expected<irveil::Statistics>`. Its counters describe selected functions, changed functions and rewritten additions. A cap outside `1..4096` returns a recoverable error before mutation.

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
