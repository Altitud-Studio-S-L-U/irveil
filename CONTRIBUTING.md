# Contributing

Propose focused changes through pull requests. The maintainer controls branch writes and merges into protected `main`. Forks can propose contributions without write access to this repository.

Name branches by purpose: `feat/...`, `fix/...`, `docs/...`, `test/...` or
`chore/...`; use `experiment/...` for research candidates. Do not prepend tool or
agent names. Remove work branches after their PR is merged or rejected. Preserve
referenced rejected experiments with explicit tags before deleting their branches.

Use the LLVM 18 setup documented in the README. Run the build and CTest locally and include the actual outcomes in the PR. This repository has no CI/CD workflows. Distinguish passing checks, existing failures and checks you could not execute.

A transformation needs a semantic argument, an explicit supported-input contract, relevant boundary and differential tests, and final-binary measurements. Treat LLVM poison/undef values, arithmetic flags, debug information and analysis invalidation as part of correctness. Preserve valid tests; do not weaken assertions or silently skip failures to obtain a passing result.

Keep source changes and tests readable. Comments should explain an invariant or a non-obvious LLVM constraint. Do not commit build trees, binaries, benchmark output, downloaded toolchains, credentials or customer programs. Inspect the staged diff before committing.

Bug reports should contain the affected commit, exact LLVM/Clang versions, optimization flags, a small owned or synthetic reproducer, and expected versus observed behavior. Use [SECURITY.md](SECURITY.md) for private reports.
