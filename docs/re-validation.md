# Reverse-engineering evaluation protocol

## Decision and scope

Determine what the initial arithmetic obfuscation changes after native code generation, what LLVM and Ghidra simplify automatically, and whether a bounded replacement removes an observed simplification. This is a reproducible experiment on owned synthetic functions, not a measurement of analyst time, protection of a real commercial program, or a general RE-resistance score.

The reference implementation is commit `b72eb4a6a962958bb86ffbd88f6e6c310674367d` (v0.1 source). Preserve its built plugin separately before modifying the candidate. Use Clang/LLVM 18.1.3, Linux x86-64, Ghidra 12.2 and a 64-bit JDK 25. Record actual tool versions and archive/plugin/input/output hashes. Keep downloaded tools, Ghidra projects and generated evidence outside source control.

## Comparisons

Use the same owned fixture source, compiler and flags for ordinary, reference-plugin and candidate-plugin builds. Compare `-O2` and `-O3`; include 32-bit and 64-bit sums, constant/identical-operand controls, branch-dependent arithmetic and a small loop. Select functions explicitly. Keep a symbol-bearing companion for mapping and derive its stripped copy with `llvm-strip --strip-all`. Run the same behavioral input corpus through every executable before accepting analysis results.

Resolve each selected function in its own symbol-bearing companion, then use its entry address/RVA to locate that same function in the corresponding stripped copy. Do not assume function addresses remain equal across builds. This grants the experiment known function locations; it does not test discovery of protected functions in an unknown binary.

1. **LLVM canonicalization:** apply InstCombine, a documented combination of canonicalization passes, and the default O2/O3 pipelines to a fixed matrix of identities, widths, seeds and defined/unknown operands. Measure restoration of a single plain addition. Include arithmetic equivalence and special-case controls. IR analysis is a separate exposure model from native-binary analysis.
2. **Native inspection:** use `llvm-objdump`, `llvm-nm`, `readelf` and `strings`. Record selected-function instruction counts and available metadata separately from full-file sizes. Instruction growth is not resistance. Stripping removes a source of analyst information but is not attributed to the obfuscation pass.
3. **Ghidra headless:** import each stripped executable into an independent project with identical analysis settings. Export C, simplified high P-code and native/raw P-code metrics for each mapped function. Record analysis/decompilation timeout, failure and cancellation explicitly. Missing or unsuccessful evidence is inconclusive, never a victory for the candidate.
4. **Controls:** analyze an identical ordinary build twice and require stable function-level metrics and normalized decompiled C. Include simple additions and degenerate cases where simplification is expected. Preserve readable pseudocode and function boundaries as counterevidence when available.

All subprocesses have deadlines; cap headless CPU and JVM heap, selected functions, source size and exported text. Scripts perform no network requests and analyze only binaries generated from the included fixture. Tool acquisition is an explicit operator step with official release checksums.

## Candidate acceptance

The v0.1 identity `(a OR b) + (a AND b)` is algebraically an addition and an observed LLVM simplification target. Evaluate the replacement `((a OR b) << 1) - (a XOR b)` alongside the retained XOR/carry form. All arithmetic is modulo 2^w, both operands remain frozen before duplicated use, no arithmetic flags are inherited, and the maximum net growth remains five instructions per rewritten addition.

Adopt a replacement only if existing semantic/integration checks and new regression cases pass, it avoids the demonstrated canonicalization on the general-input corpus, and final native/Ghidra evidence is complete. Report constant and identical-operand simplifications rather than trying to defeat valid optimizer reasoning. An identity that survives these tools is still public and algebraically recoverable; do not call it cryptographic protection or universal resistance.

## Module boundaries

Keep annotation selection, arithmetic emission and pass orchestration cohesive and independently readable. The LLVM pass/plugin is an adapter for compiler integration; a small named strategy choice selects fixed arithmetic emitters. Avoid virtual hierarchies or factories for two closed alternatives. Keep the Ghidra-specific Java exporter separate from Python subprocess orchestration and result comparison. Every split must serve a current contract or test boundary.

The final report must distinguish successful execution, semantically verified test cases, observed simplification, candidate improvements, analysis failures and untested attacks. Publish enough owned-fixture evidence and commands to reproduce the conclusion without committing toolchains or compiled artifacts.
