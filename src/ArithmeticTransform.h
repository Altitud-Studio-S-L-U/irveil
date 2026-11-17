#ifndef IRVEIL_ARITHMETIC_TRANSFORM_H
#define IRVEIL_ARITHMETIC_TRANSFORM_H

namespace llvm { class BinaryOperator; }

namespace irveil {

enum class ArithmeticIdentity { XorCarry, DoubleOrMinusXor };

// Replaces an eligible integer addition. The instruction becomes invalid after the call.
void rewriteArithmetic(llvm::BinaryOperator &instruction, ArithmeticIdentity identity);

} // namespace irveil

#endif
