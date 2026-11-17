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

void rewriteArithmetic(llvm::BinaryOperator &add, ArithmeticIdentity identity) {
  // NoFolder keeps constant operands from collapsing the intended IR structure.
  // Fresh instructions deliberately inherit no nsw, nuw, exact or other flags.
  llvm::IRBuilder<llvm::NoFolder> builder(&add);
  builder.SetCurrentDebugLocation(add.getDebugLoc());

  // The identities duplicate their operands. Freeze once per original operand
  // so every generated use observes the same choice for an undef/poison value.
  llvm::Value *left = builder.CreateFreeze(add.getOperand(0), "irveil.left");
  llvm::Value *right = builder.CreateFreeze(add.getOperand(1), "irveil.right");
  llvm::Value *replacement = identity == ArithmeticIdentity::XorCarry
                                 ? emitXorCarry(builder, left, right)
                                 : emitDoubleOrMinusXor(builder, left, right);

  replacement->takeName(&add);
  add.replaceAllUsesWith(replacement);
  add.eraseFromParent();
}

// Emits a subtraction as a modular two's-complement addition.
// Unlike the existing addition identities this is an experimental rewrite, not a protection claim.
void rewriteSubtraction(llvm::BinaryOperator &sub) {
  llvm::IRBuilder<llvm::NoFolder> builder(&sub);
  builder.SetCurrentDebugLocation(sub.getDebugLoc());
  llvm::Value *left = builder.CreateFreeze(sub.getOperand(0), "irveil.sub.left");
  llvm::Value *right = builder.CreateFreeze(sub.getOperand(1), "irveil.sub.right");
  llvm::Value *complement = builder.CreateNot(right, "irveil.sub.not");
  llvm::Value *bits = builder.CreateXor(left, complement, "irveil.sub.bits");
  llvm::Value *both = builder.CreateAnd(left, complement, "irveil.sub.both");
  llvm::Value *carry = builder.CreateShl(
      both, llvm::ConstantInt::get(sub.getType(), 1), "irveil.sub.carry");
  llvm::Value *partial = builder.CreateAdd(bits, carry, "irveil.sub.partial");
  llvm::Value *replacement = builder.CreateAdd(
      partial, llvm::ConstantInt::get(sub.getType(), 1), "irveil.sub.result");
  replacement->takeName(&sub);
  sub.replaceAllUsesWith(replacement);
  sub.eraseFromParent();
}

} // namespace irveil
