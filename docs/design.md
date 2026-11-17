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
6. Inspect staged files, run local checks and merge through a PR whose CI build and CTest pass on Ubuntu 24.04 with LLVM 18. No binaries, downloaded toolchains, benchmark output or build trees are committed. Publish source only after validation. Keep a professional README, MIT license, contributing guide and private vulnerability reporting route.

## Delivery sequence

Establish this contract; implement the core and compiler adapter; add independent black-box fixtures; validate the public integration and bounds; independently review the diff; publish the repository with maintainer-controlled branches and PR-only main. Future transformations need their own semantic argument, supported-input contract, regression corpus and final-binary measurements before becoming defaults.

## Experimental modular framework

The preceding v0.2 arithmetic contract remains the default. The experimental
`general` profile adds subtraction, bitwise identities, inverse integer comparisons
and conditional branch inversion; its defaults do not enable the new structural
or data families. Explicit `Config::transforms`/`transforms=` overrides the profile,
including a zero mask/`none` that disables all work. Unknown library enum values,
mask bits and every expansion limit are validated before inspecting the module.
The C++ configuration keeps its original first three aggregate members. Consumers
must rebuild against the matching static library/header; no stable binary ABI is
promised. LLVM 18, Linux x86-64, annotation selection and non-transitive behavior
remain the compatibility boundary.

`Config.cpp` owns parsing and validation shared by the plugin adapters. `Pass.cpp`
coordinates annotation selection, reproducible per-function state, candidate
snapshots, counters and the processed marker. Instruction, control-flow and data
emitters remain internal translation units of the same core library. There is no
runtime dependency or new build dependency. The installed CMake helper validates
the same option vocabulary at configure time and forwards target-private flags.

Order: snapshot original instruction candidates; encode original literal operands;
rewrite snapshotted instructions; snapshot and rewrite structural edges/switches;
finally encode eligible global strings and their loads. Emitted operations do not
reenter an earlier family. A changed function receives the existing processed
attribute; subsequent runs skip it regardless of configuration. Unchanged functions
remain eligible for a later run. Changed-function counters include string-only
changes and conservatively invalidate all module analyses.

### Semantic arguments and exclusions

- Subtraction uses modular two's complement; AND/OR use De Morgan and XOR uses
  `(a|b)&~(a&b)`. Duplicated operands are frozen. Comparisons invert the predicate
  and result without duplicating operands. Branch inversion swaps successors and
  their profile weights. Scalar widths remain 2..64; no pointer or float compares.
- A routed edge adds a single unconditional jump to the original target. Its PHIs
  replace the original predecessor with the route block. Loop edges are natural
  backedges where the successor dominates a reachable source; loop metadata moves
  to the new backedge terminator. Iteration order, exits and memory accesses remain
  unchanged. CFG and loop edges share a cap and can exhaust it in IR order.
- Switch lowering freezes its condition once before duplicating it in equality
  tests. It preserves default/case edges and PHI multiplicity for shared targets.
  For defined input it chooses the same destination; it does not repair input UB.
  New branches omit switch-specific profile metadata. EH/personality, address-taken
  blocks, indirect terminators, presplit coroutines and calls marked convergent,
  noduplicate or returns_twice exclude structural work in that function.
- Literal encoding computes `(constant XOR key) XOR key` at the exact integer
  width. Only original binary, `icmp` and return operands qualify. PHIs, switches,
  GEP indices, calls, intrinsics, vectors, i1 and integers wider than 64 are skipped.
  Existing arithmetic flags retain their meaning because operands are unchanged.
  This identity is deliberately simple and may disappear during constant folding.
- String encoding only mutates private, constant, non-TLS C byte arrays in address
  space zero without sections or external initialization. A complete use-graph
  walk accepts GEPs and ordinary `i8` loads in selected, previously unprocessed
  functions. All other users reject the entire global, including aliases, pointer
  escape, mutable storage, calls, PHIs, unselected readers and wide/volatile/atomic
  reads. A nonzero public byte key encodes every byte, including the terminator;
  each accepted load decodes via XOR. No ctor, alloca, writable cache, extra memory
  access or thread synchronization is introduced. The address and lifetime remain
  the same. Original load range metadata is removed because it describes decoded
  bytes. The global receives an encoding marker; all affected functions receive
  the processed marker. This is reversible representation, not encryption.

### Bounds and validation

The README lists valid ranges and defaults. Instruction rewrites and switch count
each use the legacy per-function `max-adds` cap. Edge routing adds at most one block
and jump per budgeted edge. A switch with N cases adds N test blocks, N comparisons,
N conditional branches, one final branch and one freeze, replacing the original
switch; sum of N is capped per function. Zero-case switches still consume the
switch-count budget. Literal work adds one instruction per capped operand. String
bytes have a module-wide cap; each original accepted byte load adds one XOR. The
pointer-use walk and its auxiliary storage scale with the inspected use graph;
load expansion is proportional to original loads, not solely to string byte count.
Dominator analysis, PHI/use-list repair and the rest of LLVM have their own costs;
the arithmetic-only complexity bound above does not describe all new families.

Validation includes exhaustive sub/AND/OR/XOR and all ten integer predicates at
widths 2..8, structural verifier checks, PHI/backedge/switch regressions, byte/string
exclusions and limits, plus a separate native corpus with boundary/random integers,
nested loops, continue/break, switches and selected/unselected strings. Both
unoptimized and optimized compilation of transformed IR are compared to ordinary
executables. Debug/Release builds and relocated installed C/C++ consumers remain
required. Ghidra evaluation uses a separate corpus/protocol and records eliminated
transforms as counterevidence, without replacing the historical v0.2 results.
