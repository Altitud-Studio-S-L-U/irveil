#include "InstructionTransform.h"
#include "ArithmeticTransform.h"

#include "llvm/IR/Constants.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/NoFolder.h"
#include "llvm/Support/ErrorHandling.h"

namespace irveil {
namespace {

bool eligibleInteger(const llvm::Type *type) {
  const auto *integer = llvm::dyn_cast<llvm::IntegerType>(type);
  return integer && integer->getBitWidth() >= 2 && integer->getBitWidth() <= 64;
}

void replaceInstruction(llvm::Instruction &original, llvm::Value *replacement) {
  replacement->takeName(&original);
  original.replaceAllUsesWith(replacement);
  original.eraseFromParent();
}

void rewriteBitwise(llvm::BinaryOperator &operation) {
  llvm::IRBuilder<llvm::NoFolder> builder(&operation);
  builder.SetCurrentDebugLocation(operation.getDebugLoc());
  llvm::Value *left = builder.CreateFreeze(operation.getOperand(0), "irveil.bool.left");
  llvm::Value *right = builder.CreateFreeze(operation.getOperand(1), "irveil.bool.right");
  llvm::Value *result = nullptr;
  switch (operation.getOpcode()) {
  case llvm::Instruction::And:
    result = builder.CreateNot(builder.CreateOr(builder.CreateNot(left), builder.CreateNot(right)), "irveil.bool.and");
    break;
  case llvm::Instruction::Or:
    result = builder.CreateNot(builder.CreateAnd(builder.CreateNot(left), builder.CreateNot(right)), "irveil.bool.or");
    break;
  case llvm::Instruction::Xor:
    result = builder.CreateAnd(builder.CreateOr(left, right),
                               builder.CreateNot(builder.CreateAnd(left, right)), "irveil.bool.xor");
    break;
  default:
    llvm_unreachable("classifyInstruction must reject unsupported bitwise opcodes");
  }
  replaceInstruction(operation, result);
}

void rewriteComparison(llvm::ICmpInst &comparison) {
  llvm::IRBuilder<llvm::NoFolder> builder(&comparison);
  builder.SetCurrentDebugLocation(comparison.getDebugLoc());
  const auto opposite = llvm::CmpInst::getInversePredicate(comparison.getPredicate());
  llvm::Value *inverted = builder.CreateICmp(opposite, comparison.getOperand(0),
                                             comparison.getOperand(1), "irveil.cmp.inverted");
  llvm::Value *result = builder.CreateNot(inverted, "irveil.cmp.result");
  replaceInstruction(comparison, result);
}

void rewriteBranch(llvm::BranchInst &branch) {
  llvm::IRBuilder<llvm::NoFolder> builder(&branch);
  builder.SetCurrentDebugLocation(branch.getDebugLoc());
  llvm::Value *opposite = builder.CreateNot(branch.getCondition(), "irveil.branch.condition");
  llvm::BasicBlock *yes = branch.getSuccessor(0);
  llvm::BasicBlock *no = branch.getSuccessor(1);
  branch.setCondition(opposite);
  branch.setSuccessor(0, no);
  branch.setSuccessor(1, yes);
}

} // namespace

OperationKind classifyInstruction(const llvm::Instruction &instruction, bool general) {
  if (const auto *operation = llvm::dyn_cast<llvm::BinaryOperator>(&instruction)) {
    if (!eligibleInteger(operation->getType())) return OperationKind::Unsupported;
    switch (operation->getOpcode()) {
    case llvm::Instruction::Add: return OperationKind::Add;
    case llvm::Instruction::Sub: return general ? OperationKind::Sub : OperationKind::Unsupported;
    case llvm::Instruction::And:
    case llvm::Instruction::Or:
    case llvm::Instruction::Xor:
      return general ? OperationKind::Bitwise : OperationKind::Unsupported;
    default: return OperationKind::Unsupported;
    }
  }
  if (!general) return OperationKind::Unsupported;
  if (const auto *compare = llvm::dyn_cast<llvm::ICmpInst>(&instruction))
    return eligibleInteger(compare->getOperand(0)->getType()) ? OperationKind::Comparison : OperationKind::Unsupported;
  if (const auto *branch = llvm::dyn_cast<llvm::BranchInst>(&instruction))
    return branch->isConditional() && branch->getSuccessor(0) != branch->getSuccessor(1)
               ? OperationKind::Branch : OperationKind::Unsupported;
  return OperationKind::Unsupported;
}

void rewriteInstruction(llvm::Instruction &instruction, OperationKind kind, std::uint64_t selector) {
  switch (kind) {
  case OperationKind::Add:
    rewriteArithmetic(llvm::cast<llvm::BinaryOperator>(instruction),
                      (selector & 1) ? ArithmeticIdentity::XorCarry : ArithmeticIdentity::DoubleOrMinusXor);
    break;
  case OperationKind::Sub:
    rewriteSubtraction(llvm::cast<llvm::BinaryOperator>(instruction));
    break;
  case OperationKind::Bitwise:
    rewriteBitwise(llvm::cast<llvm::BinaryOperator>(instruction));
    break;
  case OperationKind::Comparison:
    rewriteComparison(llvm::cast<llvm::ICmpInst>(instruction));
    break;
  case OperationKind::Branch:
    rewriteBranch(llvm::cast<llvm::BranchInst>(instruction));
    break;
  case OperationKind::Unsupported:
    llvm_unreachable("Unsupported instruction cannot be rewritten");
  }
}

} // namespace irveil
