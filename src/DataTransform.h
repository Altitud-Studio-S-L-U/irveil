#ifndef IRVEIL_DATA_TRANSFORM_H
#define IRVEIL_DATA_TRANSFORM_H
#include "irveil/Pass.h"
#include "llvm/ADT/ArrayRef.h"
namespace llvm { class Function; class Module; }
namespace irveil {
bool encodeConstants(llvm::Function &function, const Config &config,
                     std::uint64_t seed, Statistics &statistics);
// Only private constant byte arrays whose complete use graph ends in ordinary
// i8 loads inside eligible functions. Never decode in shared writable storage.
void encodeStrings(llvm::Module &module, llvm::ArrayRef<llvm::Function *> functions,
                   const Config &config, Statistics &statistics);
}
#endif
