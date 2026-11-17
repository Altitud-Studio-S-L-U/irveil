#include "FlattenTransform.h"
#include "Config.h"
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/Analysis/CFG.h"
#include "llvm/IR/CFG.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/NoFolder.h"
#include "llvm/Transforms/Utils/BasicBlockUtils.h"
#include "llvm/Transforms/Utils/Local.h"

#include <algorithm>
#include <cassert>

namespace irveil {
namespace {
bool spillable(llvm::Type *type) {
  if (auto *integer = llvm::dyn_cast<llvm::IntegerType>(type))
    return integer->getBitWidth() <= 64;
  auto *pointer = llvm::dyn_cast<llvm::PointerType>(type);
  return pointer && pointer->getAddressSpace() == 0;
}

bool restrictedCall(const llvm::CallBase &call) {
  const auto *callee = call.getCalledFunction();
  if (!callee || call.getCallingConv() != llvm::CallingConv::C || call.hasOperandBundles() ||
      call.isConvergent() || call.cannotDuplicate() ||
      call.hasFnAttr(llvm::Attribute::ReturnsTwice)) return true;
  if (auto *ordinary = llvm::dyn_cast<llvm::CallInst>(&call))
    if (ordinary->isMustTailCall()) return true;
  if (!callee->isIntrinsic()) return false;
  // Spilling an equivalent pointer can violate an intrinsic's requirement
  // that its operand statically resolve to a specific alloca or function.
  if (const auto *lifetime = llvm::dyn_cast<llvm::LifetimeIntrinsic>(&call))
    return !llvm::isa<llvm::AllocaInst>(lifetime->getArgOperand(1));
  return !llvm::isa<llvm::DbgInfoIntrinsic, llvm::MemIntrinsic, llvm::MinMaxIntrinsic,
                    llvm::WithOverflowInst, llvm::SaturatingInst>(&call);
}

std::uint64_t instructionCount(const llvm::Function &function) {
  std::uint64_t result = 0;
  for (auto &block : function) result += block.size();
  return result;
}
} // namespace

bool flattenControlFlow(llvm::Function &function, const Config &config,
                        std::uint64_t seed, Statistics &statistics) {
  if (!(effectiveTransforms(config) & Flatten)) return false;
  const auto unsupported = [&]() { ++statistics.flattenSkippedUnsupported; return false; };
  const auto overBudget = [&]() { ++statistics.flattenSkippedBudget; return false; };
  auto &entry = function.getEntryBlock();
  if (function.hasPersonalityFn() || function.hasGC() || function.isVarArg() ||
      function.isPresplitCoroutine() || function.hasFnAttribute("presplitcoroutine") ||
      function.hasFnAttribute(llvm::Attribute::Naked) ||
      function.hasFnAttribute(llvm::Attribute::ReturnsTwice) ||
      function.getCallingConv() != llvm::CallingConv::C ||
      function.getParent()->getDataLayout().getAllocaAddrSpace() != 0 ||
      function.size() < 3 || !llvm::isa<llvm::BranchInst>(entry.getTerminator())) return unsupported();
  if (function.size() - 1 > config.maxFlattenBlocksPerFunction) return overBudget();
  for (const auto &argument : function.args())
    if (argument.hasAttribute(llvm::Attribute::InAlloca) ||
        argument.hasAttribute(llvm::Attribute::Preallocated)) return unsupported();

  llvm::SmallVector<llvm::Instruction *, 16> registers;
  llvm::SmallVector<llvm::PHINode *, 16> phis;
  std::uint64_t bound = 3; // Dispatcher PHI, switch and invalid-state unreachable.
  unsigned criticalEdges = 0;
  llvm::DominatorTree dominators(function);
  for (auto &block : function) {
    if (block.isEHPad() || block.hasAddressTaken() ||
        !dominators.isReachableFromEntry(&block)) return unsupported();
    auto *branch = llvm::dyn_cast<llvm::BranchInst>(block.getTerminator());
    if (!branch && !llvm::isa<llvm::ReturnInst, llvm::UnreachableInst>(block.getTerminator()))
      return unsupported(); // Input switches require the explicit switch family first.
    if (branch) {
      if (branch->isConditional()) {
        if (branch->getSuccessor(0) == branch->getSuccessor(1)) return unsupported();
        ++bound; // One select, using the original condition once.
      }
      for (unsigned i = 0; i < branch->getNumSuccessors(); ++i)
        if (llvm::isCriticalEdge(branch, i)) { ++criticalEdges; ++bound; }
    }
    for (auto &instruction : block) {
      if (auto *alloca = llvm::dyn_cast<llvm::AllocaInst>(&instruction))
        if (!alloca->isStaticAlloca() || alloca->isUsedWithInAlloca()) return unsupported();
      if (auto *call = llvm::dyn_cast<llvm::CallBase>(&instruction))
        if (restrictedCall(*call)) return unsupported();
      if (auto *phi = llvm::dyn_cast<llvm::PHINode>(&instruction)) {
        if (&block == &entry || !spillable(phi->getType())) return unsupported();
        phis.push_back(phi);
        bound += 1 + phi->getNumIncomingValues(); // Net: slot + load + stores - PHI.
      }
      // Entry definitions continue to dominate the dispatcher and every case.
      if (&block == &entry) continue;
      bool escapes = false;
      std::uint64_t uses = 0;
      for (auto &use : instruction.uses()) {
        auto *user = llvm::dyn_cast<llvm::Instruction>(use.getUser());
        if (!user) return unsupported();
        ++uses;
        escapes |= user->getParent() != &block || llvm::isa<llvm::PHINode>(user);
      }
      if (escapes) {
        if (!spillable(instruction.getType())) return unsupported();
        registers.push_back(&instruction);
        bound += 2 + uses; // Slot, store and at most one reload per original use.
      }
      if (bound > config.maxFlattenInstructionsPerFunction) return overBudget();
    }
  }
  if (function.size() - 1 + criticalEdges > config.maxFlattenBlocksPerFunction ||
      bound > config.maxFlattenInstructionsPerFunction) return overBudget();

  // Follow LLVM 18 reg2mem ordering: split critical edges, demote escaping
  // registers (including escaping PHI results), then demote the PHIs. A PHI's
  // current result must be cached separately from its next incoming value.
  const auto before = instructionCount(function);
  const auto split = llvm::SplitAllCriticalEdges(function);
  assert(split == criticalEdges && "preflight must account for every split edge");
  (void)split;
  auto *allocaPoint = entry.getTerminator();
  std::uint64_t slots = 0;
  for (auto *reg : llvm::reverse(registers))
    if (llvm::DemoteRegToStack(*reg, false, allocaPoint)) ++slots;
  for (auto *phi : llvm::reverse(phis))
    if (llvm::DemotePHIToStack(phi, allocaPoint)) ++slots;

  llvm::SmallVector<llvm::BasicBlock *, 16> cases;
  for (auto &block : function) if (&block != &entry) cases.push_back(&block);
  auto *dispatcher = llvm::BasicBlock::Create(function.getContext(), "irveil.flatten.dispatch",
                                             &function, cases.front());
  auto *invalid = llvm::BasicBlock::Create(function.getContext(), "irveil.flatten.invalid", &function);
  llvm::IRBuilder<llvm::NoFolder> builder(dispatcher);
  auto *state = builder.CreatePHI(builder.getInt32Ty(), cases.size() + 1, "irveil.flatten.state");
  auto *dispatch = builder.CreateSwitch(state, invalid, cases.size());
  llvm::DenseMap<llvm::BasicBlock *, llvm::ConstantInt *> tags;
  for (unsigned i = 0; i < cases.size(); ++i) {
    // XOR with a public seeded word is injective over these distinct i32 IDs.
    auto *tag = builder.getInt32((i + 1) ^ static_cast<std::uint32_t>(seed));
    tags[cases[i]] = tag;
    dispatch->addCase(tag, cases[i]);
  }
  builder.SetInsertPoint(invalid);
  builder.CreateUnreachable();
  const auto redirect = [&](llvm::BasicBlock *block) {
    auto *branch = llvm::dyn_cast<llvm::BranchInst>(block->getTerminator());
    if (!branch) return;
    llvm::IRBuilder<llvm::NoFolder> at(branch);
    at.SetCurrentDebugLocation(branch->getDebugLoc());
    llvm::Value *next = tags.lookup(branch->getSuccessor(0));
    if (branch->isConditional())
      next = at.CreateSelect(branch->getCondition(), next, tags.lookup(branch->getSuccessor(1)),
                             "irveil.flatten.next");
    assert(next && "all original branch targets must be dispatch cases");
    state->addIncoming(next, block);
    at.CreateBr(dispatcher); // Old loop/profile metadata no longer describes this CFG.
    branch->eraseFromParent();
  };
  redirect(&entry);
  for (auto *block : cases) redirect(block);
  const auto added = std::max(before, instructionCount(function)) - before;
  assert(added <= bound && "flattening exceeded its preflight bound");
  function.addFnAttr("irveil.flattened");
  ++statistics.flattenedFunctions;
  statistics.flattenedBlocks += cases.size();
  statistics.flattenSpillSlots += slots;
  statistics.flattenAddedInstructions += added;
  return true;
}
} // namespace irveil
