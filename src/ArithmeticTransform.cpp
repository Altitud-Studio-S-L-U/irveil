#include "ArithmeticTransform.h"

#include "llvm/IR/Constants.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/NoFolder.h"

namespace irveil {
namespace {

llvm::Value *emitXorCarry(llvm::IRBuilder<llvm::NoFolder> &builder,
                          llvm::Value *left, llvm::Value *right) {
  llvm::Value *common = builder.CreateAnd(left, right, "irveil.and");
  llvm::Value *bits = builder.CreateXor(left, right, "irveil.xor");
  llvm::Value *carry = builder.CreateShl(
      common, llvm::ConstantInt::get(left->getType(), 1), "irveil.carry");
  return builder.CreateAdd(bits, carry, "irveil.sum");
}

llvm::Value *emitDoubleOrMinusXor(llvm::IRBuilder<llvm::NoFolder> &builder,
                                  llvm::Value *left, llvm::Value *right) {
  llvm::Value *bits = builder.CreateOr(left, right, "irveil.or");
  llvm::Value *doubled = builder.CreateShl(
      bits, llvm::ConstantInt::get(left->getType(), 1), "irveil.doubled");
  llvm::Value *different = builder.CreateXor(left, right, "irveil.xor");
  return builder.CreateSub(doubled, different, "irveil.sum");
}

} // namespace

void rewriteArithmetic(llvm::BinaryOperator &add, AddIdentity identity) {
  // NoFolder keeps constant operands from collapsing the intended IR structure.
  // Fresh instructions deliberately inherit no nsw, nuw, exact or other flags.
  llvm::IRBuilder<llvm::NoFolder> builder(&add);
  builder.SetCurrentDebugLocation(add.getDebugLoc());

  // The identities duplicate their operands. Freeze once per original operand
  // so every generated use observes the same choice for an undef/poison value.
  llvm::Value *left = builder.CreateFreeze(add.getOperand(0), "irveil.left");
  llvm::Value *right = builder.CreateFreeze(add.getOperand(1), "irveil.right");
  llvm::Value *replacement = identity == AddIdentity::XorCarry
                                 ? emitXorCarry(builder, left, right)
                                 : emitDoubleOrMinusXor(builder, left, right);

  replacement->takeName(&add);
  add.replaceAllUsesWith(replacement);
  add.eraseFromParent();
}

} // namespace irveil
