# IRVeil v0.2 contract

## Purpose and threat model

IRVeil is a C++ library and LLVM pass plugin for selective compile-time obfuscation of C and C++ programs. The intended user owns the source and distributes a native executable. An analyst can read, modify, disassemble and run that executable and knows IRVeil's implementation. Seeds are reproducibility inputs, not secrets.

The transformation changes selected integer additions into equivalent mixed boolean/arithmetic expressions. This arithmetic diversification does not establish a quantified resistance to reverse engineering, hide runtime values, protect embedded credentials, or prevent patching. Control-flow virtualization, anti-debugging, binary rewriting, Go support and whole-program protection are outside v0.2. The [evaluation protocol](re-validation.md) defines the criteria; [the measured evaluation](re-evaluation.md) records results and counterevidence.

## Integration

Target Linux x86-64 and LLVM/Clang 18 only for the initial release. Keep compiler, plugin headers/libraries and LLVM tools on the same installation. LLVM plugin interfaces are not a stable cross-version ABI. Use C++17, CMake and the installed LLVM development package; do not fetch dependencies during configuration.

Provide an embeddable static target `IRVeil::Core`, a loadable `IRVeilPass` module and an opt-in source header `irveil/Protect.h`. `IRVEIL_PROTECT` applies Clang's `annotate("irveil")` and `noinline` attributes to a function. Selection is not transitive into callees. The annotation must exist in LLVM IR; linking previously compiled native objects is not sufficient.

Support the explicit module pipeline `irveil` in `opt`, plus `irveil<seed=N;max-adds=N>`. Seed is an unsigned decimal 64-bit integer; max-adds is an integer from 1 through 4096, default 256. Reject unknown, duplicate, malformed and out-of-range options. The explicit pipeline runs only when requested. For `clang -fpass-plugin`, register the default configuration at the optimizer-last extension point. Test the actual supported optimization modes rather than inferring support from registration alone. Re-running the pass on the same function must not expand the generated additions again; mark processed functions with a dedicated IR attribute.

### Installed compiler integration

`find_package(IRVeil CONFIG REQUIRED COMPONENTS Plugin)` imports `IRVeil::Pass`
and `IRVeil::Headers` without finding LLVM's development package or importing the
static core. A package lookup without components retains the existing `Core`
behavior and its matching LLVM development dependency.

`irveil_protect_target(target [SEED N] [MAX_ADDS N] [REPORT])` applies private
compile options and includes to one local compiled target. Seed defaults to 0
and accepts decimal uint64; the cap defaults to 256 and accepts 1..4096. Reject
unknown/repeated/missing/out-of-range options, repeated helper calls, imported or
alias targets and visible IPO settings at configure time. The helper uses Clang's
early DSO load before parsing `-mllvm` options, then `-fpass-plugin` to register
the optimizer-last pass. It does not use process environment configuration.

Clang options `-irveil-seed`, `-irveil-max-adds` and `-irveil-report` configure
only the automatic extension point. Invalid values fail before pass mutation;
the explicit `opt` pipeline retains its own configuration. Optional reports name
the module, effective configuration and selected/changed/rewritten counters.
They establish IR work, not final-binary survival. The README defines the native
inspection procedure and the observed `-save-temps` limitation.

## Semantics and bounds

Only scalar LLVM `add` instructions of integer widths 2 through 64 in annotated, defined functions are eligible. Skip vectors, i1, wider integers and other opcodes. Respect the per-function cap on original additions. Select one of two identities deterministically using a documented, non-cryptographic seed derivation from the configuration and LLVM function name:

`a + b = (a XOR b) + ((a AND b) << 1)`

`a + b = ((a OR b) << 1) - (a XOR b)`

The second identity replaces v0.1's `(a OR b) + (a AND b)`, which LLVM 18 InstCombine restores directly to `add`. Since `a OR b = (a XOR b) + (a AND b)` as integer bit sums, doubling it and subtracting XOR gives the same modular addition as the first identity. This changes seeded output across versions; reproduce results with the same IRVeil version as well as the same LLVM version.

Both identities operate modulo 2^w. Freeze each operand before duplicating its uses: the mathematical identities alone are insufficient for LLVM values that may contain `undef` bits. Do not copy `nsw`, `nuw` or other arithmetic flags onto replacement instructions. For source executions where an original flagged add is defined, the result must be preserved. The pass is not a repair for undefined behavior in the input program. A one-bit shift is only constructed for widths at least two. Preserve debug locations where possible; invalidate affected LLVM analyses accurately. Do not introduce globals, runtime initialization, calls, memory accesses or conditional branches.

Inspect a bounded set of original instructions; never recursively transform generated instructions. With A annotation entries, I instructions inspected, K rewritten additions, U operand uses updated and L bytes of function names hashed, the coordination work is O(A + I + K + U + L), aside from LLVM container internals. Replacing an instruction must visit its users even when the candidate cap ends the scan early. Auxiliary storage is O(A + K). K is bounded by the per-function cap times the number of selected functions. Each replacement adds at most five net instructions, including the two freezes. These bounds describe this pass, not the compiler's other optimizations or machine-code size.

Expose counters for selected/changed functions and rewritten additions through the library API. Invalid library configuration returns a recoverable `llvm::Error` through `llvm::Expected<Statistics>` before mutating the module. A processed function remains unchanged even with another seed or IRVeil version; generate fresh IR from source to evaluate a different transformation. No source content, seeds or application names are uploaded. Diagnostics and artifacts remain local.

## Validation and release gate

1. Build the static library and plugin against the installed LLVM 18 toolchain. Compile and link a separate library consumer and a source-annotation consumer. Install into a temporary prefix and verify that an external CMake consumer discovers and links `IRVeil::Core` after relocating that prefix, with the same LLVM development installation.
2. Verify transformed IR structurally with LLVM's verifier. Check identities exhaustively at small integer widths and with boundary/random inputs at 32/64 bits, with reproducible random seeds. Distinguish structural verification from semantic evidence.
3. Compile the same owned fixtures with and without the plugin; compare observable results. Exercise branches, loops, multiple selected functions, unselected functions, wraparound, signed defined inputs and scalar-width exclusions. Run AddressSanitizer/UndefinedBehaviorSanitizer where compatible.
4. Verify selection, bounded expansion, deterministic output, option rejection, empty/unannotated modules and repeat-pass idempotence. Compare seeds on a fixture with enough eligible operations without claiming a different output is guaranteed for every input.
5. Inspect optimized native disassembly and count instructions in the selected symbol, compared with the same compiler/options and a stripping-only baseline. If the backend removes a transformation, report it; IR growth alone is not evidence of final-binary change. Publish measured overhead with the exact workload and environment. No universal performance or RE-resistance claim follows from one fixture.
6. Inspect staged files, run local checks and merge through a PR. No CI/CD workflows, binaries, downloaded toolchains, benchmark output or build trees are committed. Publish source only after validation. Keep a professional README, MIT license, contributing guide and private vulnerability reporting route.

## Delivery sequence

Establish this contract; implement the core and compiler adapter; add independent black-box fixtures; validate the public integration and bounds; independently review the diff; publish the repository with maintainer-controlled branches and PR-only main. Future transformations need their own semantic argument, supported-input contract, regression corpus and final-binary measurements before becoming defaults.
