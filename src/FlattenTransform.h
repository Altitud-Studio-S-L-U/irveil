#ifndef IRVEIL_FLATTEN_TRANSFORM_H
#define IRVEIL_FLATTEN_TRANSFORM_H
#include "irveil/Pass.h"
namespace llvm { class Function; }
namespace irveil {
// Whole-function preflight; an unsupported or over-budget function is unchanged.
bool flattenControlFlow(llvm::Function &function, const Config &config,
                        std::uint64_t seed, Statistics &statistics);
}
#endif
