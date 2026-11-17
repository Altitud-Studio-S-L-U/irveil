#ifndef IRVEIL_CONTROL_FLOW_TRANSFORM_H
#define IRVEIL_CONTROL_FLOW_TRANSFORM_H
#include "irveil/Pass.h"
namespace llvm { class Function; }
namespace irveil {
// Returns true only when IR changed. Excludes EH, indirect control flow and
// address-taken blocks; natural backedges share the edge budget with CFG edges.
bool rewriteControlFlow(llvm::Function &function, const Config &config,
                        Statistics &statistics);
}
#endif
