#ifndef IRVEIL_PROTECT_H
#define IRVEIL_PROTECT_H

// Selection is local to the annotated definition, never transitive to callees.
#if defined(__clang__)
#define IRVEIL_PROTECT __attribute__((annotate("irveil"), noinline))
#else
#error "IRVEIL_PROTECT requires Clang; IRVeil supports LLVM/Clang 18"
#endif

#endif
