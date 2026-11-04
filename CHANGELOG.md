# Changelog

## Unreleased

- Add installed compiler-only CMake consumption and per-target seed, cap and
  reporting options, with an independent two-target C++ example.
- State reverse-engineering resistance as the project's goal and distinguish
  current arithmetic diversification from future improvements.
- Add bounded SSA P-code extraction, pinned SiMBA/GAMBA recovery evaluation and
  an independent semantic recognition control using the v0.2.0 release artifacts.
- Record two rejected transformation experiments, their semantic checks and
  native costs; the released arithmetic algorithm remains unchanged.

## 0.2.1

- Keep the RE evaluator's output-path validation compatible with Python 3.8, including the restriction that evidence inside the repository belongs under `work/`.
- Add a standalone CMake consumer with a complete install, configure, build and run example. Local checks exercise the exported `IRVeil::Core` target from a relocated installation prefix and compare native results with an ordinary build.
- Describe the supported arithmetic diversification and measured limits directly in the documentation.

The transformation and public C++ API are unchanged. The published Ghidra measurements and artifact hashes remain those of v0.2.0; this patch does not claim new RE resistance results.

## 0.2.0

- Replace the OR/AND addition identity that LLVM 18 InstCombine simplified directly, and add canonicalization regression checks.
- Publish the [LLVM and Ghidra evaluation](docs/re-evaluation.md), including reproducible artifacts, controls and counterevidence.
