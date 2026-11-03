# Security policy

IRVeil transforms application-selected LLVM IR inside the compiler process. It is not an isolation boundary for untrusted source or IR and does not authenticate artifacts or enforce application authorization.

## Report privately

Use this repository's **Report a vulnerability** option. If it is unavailable, contact [Altitud Studio](https://altitudstudio.ad/es/) to request a private reporting channel. Include the affected version or commit, toolchain and a minimal synthetic reproduction. Do not put credentials, proprietary programs or exploit details in a public issue. No response-time guarantee is offered for this initial project.

## Protection boundary

The attacker may inspect the executable, run it, modify it and read IRVeil's source. The seed is not a key. The initial algebraic transformation can be recognized or simplified and does not establish measured resistance to reverse engineering. It cannot protect credentials embedded in a distributed executable or values available during execution.

Use trusted toolchains and matched LLVM versions. Validate the output against the application's behavioral and operational requirements. Preserve authorization, credential handling and ordinary build security independently of obfuscation. Keep private debug information and application inputs out of public bug reports.
