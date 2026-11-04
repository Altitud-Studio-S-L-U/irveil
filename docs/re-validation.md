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

## SiMBA recovery protocol

This separate experiment starts from the **native stripped binaries published with
v0.2.0**, including the ordinary control. It does not simplify source expressions
or IR and label them as native evidence. `tools/re/simba.py` verifies the published
report's SHA-256, each binary hash and each function map. Known function locations
are still granted. An optional candidate is compiled from the same checked fixture
with the same LLVM 18.1.3 flags and compared against the same ordinary executable.
All executables must produce identical output for the existing 633-row corpus.

Freeze these settings before comparing a transformation:

- Linux x86-64, LLVM/Clang 18.1.3, Ghidra 12.2 and JDK 25. The recorded run uses
  Temurin 25.0.5+8. O2 and O3 are separate cases; seed 0 and max-adds 256 are the
  plugin defaults for the historical and experimental builds.
- Official [SiMBA](https://github.com/DenuvoSoftwareSolutions/SiMBA) commit
  `228179970f5906ed763afb33fc8649de2846696e`, with its linearity check enabled.
  Z3 is `z3-solver==4.13.3.0` (engine 4.13.3, [MIT license](https://github.com/Z3Prover/z3/blob/z3-4.13.3/LICENSE.txt)).
  SiMBA is a GPL-3.0 external evaluation tool; neither its code nor Z3 is added
  to IRVeil's build or package.
- The eight functions in `tests/fixtures/re-corpus.cpp`, at their actual 32/64-bit
  widths. There is no width coercion, guessed prototype or branch/path selection.
  Multiple-block functions, PHIs, non-parameter leaves, loads, mixed widths and
  unsupported P-code operations are rejected explicitly.
- `ExportExpressions.java` follows the SSA definitions backwards from the single
  scalar `RETURN`. Register addresses in printed P-code are not SSA identities.
  The accepted operations are COPY, integer add/subtract/multiply, AND/OR/XOR,
  bitwise/unary negation, and constant left shifts represented as multiplication
  modulo the return width. A slice has at most 512 nodes, depth 64, four parameters
  and 16 KiB of expression text.
- Each SiMBA worker has a five-second wall deadline, five CPU seconds, a 512 MiB
  address-space bound and 64 KiB output bound. Ghidra retains a 120-second analysis
  deadline, 30 seconds per function, two CPUs and a 1 GiB JVM heap (not total RSS).
  The enclosing headless process has a 405-second deadline.

The evaluator records five disjoint outcomes for every function:

| Status | Meaning |
| --- | --- |
| `recovered` | SiMBA produced a purely linear arithmetic expression whose modular coefficients match the predefined source operation; both Z3 proofs below passed. |
| `not_recovered` | A supported expression was simplified correctly, but the result retained structure outside that recovery criterion. |
| `unsupported` | The extractor or SiMBA's linearity checker rejected the input, with its reason. |
| `timeout` | Decompilation, worker deadline or a bounded Z3 proof did not finish. |
| `error` | Tool failure, malformed result or a semantic counterexample. |

SiMBA runs without its unbounded internal Z3 check. The evaluator instead proves
**extracted input = simplified result** and **simplified result = predefined source
operation** separately using bitvectors, with two seconds per solver query. Only
`unsat` for the inequality counts as a proof. A counterexample is an error, while
`unknown` is inconclusive and reported as timeout. These proofs validate the
extracted expression and its simplification, not the correctness of Ghidra's whole
decompilation. Native differential execution remains a separate check.

Do not turn `unsupported`, timeout or error into a resistance score. Compare raw
expressions and supported recovery alongside native function instruction/byte
counts. A candidate that only moves expressions outside SiMBA's supported domain
and raises cost has not demonstrated the intended improvement and stays out of
the default transformation. Record its algebra, LLVM constraints and hypothesis
before building it; use the same evaluator and controls afterwards.

### Reproduce SiMBA extraction and recovery

Obtain and verify Ghidra/JDK as above. This optional evaluation also uses `curl`,
`unzip`, Git and Python's `venv` module (`python3-venv` on Ubuntu). Starting at the
repository root, use a new output directory for each run. The following retrieves
only SiMBA source needed by the evaluator; tools and published binaries remain
under ignored `work/`.

```sh
mkdir -p work/simba-evaluation/historical
curl -fL https://github.com/Altitud-Studio-S-L-U/irveil/releases/download/v0.2.0/irveil-v0.2.0-re-evidence.zip \
  -o work/simba-evaluation/historical/irveil-v0.2.0-re-evidence.zip
echo '2dd1afdf7e731e39eebd4ac2831881e7106f0e2fa6edc0e75153ad07d6b438c4  work/simba-evaluation/historical/irveil-v0.2.0-re-evidence.zip' | sha256sum -c -
unzip work/simba-evaluation/historical/irveil-v0.2.0-re-evidence.zip \
  -d work/simba-evaluation/historical/evidence
git clone --filter=blob:none --sparse \
  https://github.com/DenuvoSoftwareSolutions/SiMBA.git work/simba-evaluation/SiMBA
git -C work/simba-evaluation/SiMBA sparse-checkout set src
git -C work/simba-evaluation/SiMBA checkout 228179970f5906ed763afb33fc8649de2846696e
python3 -m venv work/simba-evaluation/venv
work/simba-evaluation/venv/bin/pip install z3-solver==4.13.3.0
work/simba-evaluation/venv/bin/python -m unittest discover -s tools/re -p 'tests_*.py'
work/simba-evaluation/venv/bin/python tools/re/check_simba_solver.py
work/simba-evaluation/venv/bin/python tools/re/simba.py \
  --historical-dir work/simba-evaluation/historical/evidence \
  --simba-root work/simba-evaluation/SiMBA \
  --ghidra-home /absolute/path/to/ghidra_12.2_PUBLIC \
  --java-home /absolute/path/to/jdk-25 \
  --llvm-bin /usr/lib/llvm-18/bin \
  --output "$PWD/work/simba-evaluation/run-1"
# To compare a separate candidate, repeat with a new output directory and:
# --candidate-plugin /absolute/path/to/candidate/IRVeilPass.so
```

`simba.json` contains per-function expressions, widths, results, proof statuses,
native instruction/byte counts, tool identities, limits, hashes and command logs.
The runner makes no network requests. It returns nonzero for incomplete runs;
unsupported entries remain visible in an otherwise completed experiment.

## Complementary general-MBA attack: GAMBA

This is a separate attack, specified after the SiMBA baseline exposed unsupported
semilinear input and **before** measuring a composed candidate. It preserves the
SiMBA results and consumes the same extracted P-code expressions. The primary
question is whether a composition actually lowers supported recovery against a
simplifier designed for general MBAs, rather than merely leaving SiMBA's domain.

Use official [GAMBA](https://github.com/DenuvoSoftwareSolutions/GAMBA) commit
`96691c0f1c7fd1be66bd11a6f2b60ce6865ce68c` (GPL-3.0), NumPy `1.26.4` and the same
Z3 `4.13.3.0` environment. NumPy's wheel requires Python 3.9 or later for this
optional attack (the measured environment uses Python 3.12.3); it is not an IRVeil
build dependency and does not change the Python 3.8 build/test contract. Reports
record the actual interpreter version. No upstream algorithm is
changed. Its core `_simplify` entry runs inside our already isolated worker,
avoiding the public wrapper's extra multiprocessing workers and its independent
30-second deadline. The pinned core uses the same simplification and polishing.

Keep the 32/64-bit widths, O2/O3 corpus, seed 0, max-adds 256, five-second worker
deadline, 512 MiB address space, 16 KiB expressions and two-second Z3 query limits.
Set NumPy/BLAS thread counts to one. Reuse all historical, normal and candidate
expressions in the input report, including expressions rejected by SiMBA's
linearity checker. Branch/loop slices still remain unsupported by the extractor.
Use the same five outcome states, recovery criterion and the two separately
labelled semantic proofs. Bounded constant exponentiation/left shifts in GAMBA
output are expanded to multiplication before the existing bitvector checks.

Exploratory algebraic formulas may be used to check the attack adapter, but are
labelled synthetic and are excluded from native recovery counts. For the first
candidate, composing an identity over `u=a^b` and `v=2*(a&b)` is expected to leave
SiMBA's linear domain. The hypothesis to test is that GAMBA's substitutions will
still recover `a+b`; if so, composition is not an algorithmic improvement and its
code/runtime overhead is a rejection reason. The normal executable, released
v0.2.0, degenerate sums and unselected function prevent attributing a tool failure
or unsupported input to the candidate. Generalizing beyond these functions or
selecting a later candidate requires new held-out cases and a separate hypothesis.

```sh
git clone --filter=blob:none --sparse \
  https://github.com/DenuvoSoftwareSolutions/GAMBA.git work/simba-evaluation/GAMBA
git -C work/simba-evaluation/GAMBA sparse-checkout set src
git -C work/simba-evaluation/GAMBA checkout 96691c0f1c7fd1be66bd11a6f2b60ce6865ce68c
work/simba-evaluation/venv/bin/pip install numpy==1.26.4
work/simba-evaluation/venv/bin/python tools/re/gamba.py \
  --input work/simba-evaluation/run-1/simba.json \
  --gamba-root work/simba-evaluation/GAMBA \
  --output work/simba-evaluation/run-1/gamba.json
```

Workers disable bytecode writes so file-size bounds cannot truncate dependency
caches. The GAMBA report links the exact input report by SHA-256; it keeps the
SiMBA status separately for each retried expression. Use a fresh output filename.

### Secondary expanded extraction profile

The prefix-carry candidate exceeded the primary extractor's 512-node tree-slice
limit on the general and constant sums. Those primary results remain
`unsupported`; they are not evidence about GAMBA. Before running a secondary
comparison, define `--profile expanded`: 4,096 slice nodes, depth 64, 131,072
expression bytes and 8,192 parser nodes. Widths, fixture, source hash, tool pins,
seed 0, max-adds 256, five-second wall/CPU deadlines, 512 MiB worker address space,
64 KiB worker output and two-second Z3 queries stay fixed. The CPU soft limit is
five seconds with a six-second hard fallback; `SIGXCPU` is recorded as timeout
with a distinct reason, while other abnormal exits are errors.

Run ordinary/v0.2.0/prefix controls at O2 and O3 under this new profile. Repeat the
composed comparison with that same profile. Keep new reports separately and
record the effective limits in each JSON; do not replace primary results. The
secondary question is whether GAMBA actually simplifies a successfully extracted
carry network. An extraction rejection, timeout, error or missing semantic proof
remains inconclusive. This profile is an experimental extension of the evaluator,
not a post-hoc reclassification of the primary results.

Use the preceding `simba.py` command with `--profile expanded`, the corresponding
candidate plugin and a fresh output directory. `gamba.py` inherits the input
profile automatically. Its input-to-result proof and result-to-source proof use
the effective parser bounds from that profile.

### Candidate algebra and LLVM scope

The optional algebra checker constructs the candidate formulas independently of
the LLVM emitter. For each width 2 through 64 and each of the two seeded
alternatives, it asks Z3 whether the formula can differ from `a+b` modulo that
width: 126 queries per candidate, ten seconds per query, pinned Z3 4.13.3.

```sh
work/simba-evaluation/venv/bin/python tools/re/check_candidate_algebra.py \
  --candidate composed --output "$PWD/work/composed-algebra.json"
work/simba-evaluation/venv/bin/python tools/re/check_candidate_algebra.py \
  --candidate prefix --output "$PWD/work/prefix-algebra.json"
```

`unsat` proves these pure bitvector obligations; this is not an Alive2 proof of
the LLVM pass. The separate LLVM argument and tests must still establish operand
freezes before duplicated use, refinement for undef/poison, no copied overflow
flags, legal shifts, verifier validity, idempotence, selection and independent
instruction budgets. Do not convert an algebra proof or differential corpus into
a claim about every LLVM behavior.

### Bounded semantic recognition control

This additional attack is a small IRVeil-owned recognizer, not Xyntia, msynth or
GAMBA. Its worker receives only an extracted expression and width, without the
function's name or source operation. Before executing workers it writes a protocol
JSON with input/script/fixture hashes and the effective inherited profile.

The fixed grammar contains zero or one operation over `p0`, `p1`, `0`, `1`, `2`
and the observed `f(0,0)`: unary `~`/`-`, or binary `+`, `-`, `*`, `&`, `|`, `^`.
There are at most 234 candidates. Select the first candidate matching 64 boundary
pairs and 32 deterministic PRNG training pairs. A separate 32-pair holdout, seeded
with `0x49525645 + width`, is never used for candidate selection. Then prove
`extracted != learned` unsatisfiable with Z3 under the same two-second limit.
Only after that proof may the coordinator compare the learned expression with
the predefined source operation. A matching holdout without the SMT proof is
inconclusive and must not be counted as verified recovery. The five-second,
512 MiB worker limits and primary/expanded expression limits remain in force.

Run the same grammar against all ordinary, v0.2.0, composed and prefix expressions,
including controls and both optimization levels. Branch/loop extraction failures
remain unsupported. This tests recognition of a deliberately tiny operation
grammar, not human analyst time or general program synthesis.

```sh
work/simba-evaluation/venv/bin/python tools/re/synthesize.py \
  --input normal=work/simba-evaluation/prefix-fixed-expanded-final/simba.json \
  --input v0.2.0=work/simba-evaluation/prefix-fixed-expanded-final/simba.json \
  --input composed=work/simba-evaluation/composed-expanded-final/simba.json \
  --input prefix=work/simba-evaluation/prefix-fixed-expanded-final/simba.json \
  --output work/simba-evaluation/synthesis-expanded-final.json
```

## Rebuild and compare the two experimental sources

Run the acquisition/setup commands above first from an evaluation checkout that
contains these tools. Both experiments are source-only draft PRs outside `main`:
[composed #5](https://github.com/Altitud-Studio-S-L-U/irveil/pull/5), commit
`61bc636ff1bd52851391053aac9b96e877547c56`, and
[prefix #6](https://github.com/Altitud-Studio-S-L-U/irveil/pull/6), commit
`52813541196ec63619ed300277dc4aacddea04a0`. Use fresh directories. Set the two
tool-home paths to the verified installations obtained earlier:

```sh
export GHIDRA_HOME=/absolute/path/to/ghidra_12.2_PUBLIC
export JAVA_HOME=/absolute/path/to/jdk-25

build_candidate() {
  candidate_name="$1"
  candidate_commit="$2"
  candidate_source="$PWD/work/candidates/$candidate_name/source"
  candidate_build="$PWD/work/candidates/$candidate_name/build"
  mkdir -p "$PWD/work/candidates/$candidate_name" || return
  git clone --no-checkout https://github.com/Altitud-Studio-S-L-U/irveil.git "$candidate_source" || return
  git -C "$candidate_source" checkout "$candidate_commit" || return
  cmake -S "$candidate_source" -B "$candidate_build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang-18 \
    -DCMAKE_CXX_COMPILER=clang++-18 -DLLVM_DIR=/usr/lib/llvm-18/lib/cmake/llvm || return
  cmake --build "$candidate_build" --parallel 2 || return
  (cd "$candidate_build" && ctest --output-on-failure)
}
build_candidate composed 61bc636ff1bd52851391053aac9b96e877547c56
build_candidate prefix 52813541196ec63619ed300277dc4aacddea04a0

evaluate_candidate() {
  candidate_name="$1"
  candidate_output="$PWD/work/simba-evaluation/$2"
  work/simba-evaluation/venv/bin/python tools/re/simba.py --profile expanded \
    --historical-dir work/simba-evaluation/historical/evidence \
    --candidate-plugin "$PWD/work/candidates/$candidate_name/build/IRVeilPass.so" \
    --simba-root work/simba-evaluation/SiMBA --ghidra-home "$GHIDRA_HOME" \
    --java-home "$JAVA_HOME" --llvm-bin /usr/lib/llvm-18/bin --output "$candidate_output"
}
evaluate_candidate composed composed-expanded-final
evaluate_candidate prefix prefix-fixed-expanded-final

work/simba-evaluation/venv/bin/python tools/re/gamba.py \
  --input work/simba-evaluation/composed-expanded-final/simba.json \
  --gamba-root work/simba-evaluation/GAMBA \
  --output work/simba-evaluation/gamba-composed-expanded-final.json
work/simba-evaluation/venv/bin/python tools/re/gamba.py \
  --input work/simba-evaluation/prefix-fixed-expanded-final/simba.json \
  --gamba-root work/simba-evaluation/GAMBA \
  --output work/simba-evaluation/gamba-prefix-fixed-expanded-final.json
# Prefix GAMBA returns 1 with explicit timeout records in the measured profile.
# Continue with the bounded recognition command above; retain those timeouts.

python3 tools/measure.py --llvm-bin /usr/lib/llvm-18/bin \
  --plugin work/candidates/composed/build/IRVeilPass.so \
  --iterations 10000000 --samples 5 --output work/composed-cost.json
python3 tools/measure.py --llvm-bin /usr/lib/llvm-18/bin \
  --plugin work/candidates/prefix/build/IRVeilPass.so \
  --iterations 10000000 --samples 5 --output work/prefix-cost.json
```

Do not use `set -e` to discard the remaining experiment when a deliberately
retained timeout makes GAMBA return nonzero. Read the JSON state before drawing a
conclusion. The final evaluator rejects a run if its own source, exporter, helper,
fixture or candidate plugin changes during that run. GAMBA checks its wrapper,
shared evaluator and input-report fingerprints as well. Primary and exploratory
reports generated during tool development are kept separately from these final
comparisons.
