#ifndef IRVEIL_INSTRUCTION_TRANSFORM_H
#define IRVEIL_INSTRUCTION_TRANSFORM_H

#include <cstdint>

namespace llvm { class Instruction; }

namespace irveil {

enum class OperationKind { Add, Sub, Bitwise, Comparison, Branch, Unsupported };

// Return the supported operation family. No user code or memory operations are inspected.
OperationKind classifyInstruction(const llvm::Instruction &instruction, bool general);
// Rewrite a classified instruction. The caller must not use the old instruction afterward.
void rewriteInstruction(llvm::Instruction &instruction, OperationKind kind, std::uint64_t selector);

} // namespace irveil

#endif
