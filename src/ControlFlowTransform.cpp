#include "ControlFlowTransform.h"
#include "Config.h"
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/NoFolder.h"

namespace irveil {
namespace {
bool supported(const llvm::Function &function) {
  if (function.hasPersonalityFn() || function.hasFnAttribute("presplitcoroutine")) return false;
  for (const auto &block : function) {
    if (block.isEHPad() || block.hasAddressTaken()) return false;
    const auto *term = block.getTerminator();
    if (!llvm::isa<llvm::BranchInst, llvm::SwitchInst, llvm::ReturnInst,
                   llvm::UnreachableInst>(term)) return false;
    for (const auto &inst : block)
      if (const auto *call = llvm::dyn_cast<llvm::CallBase>(&inst))
        if (call->isConvergent() || call->cannotDuplicate() ||
            call->hasFnAttr(llvm::Attribute::ReturnsTwice)) return false;
  }
  return true;
}

void lowerSwitch(llvm::SwitchInst &sw) {
  auto *origin = sw.getParent();
  auto *function = origin->getParent();
  llvm::IRBuilder<llvm::NoFolder> builder(&sw);
  builder.SetCurrentDebugLocation(sw.getDebugLoc());
  // A single choice must feed all comparisons, including an undef condition.
  auto *condition = builder.CreateFreeze(sw.getCondition(), "irveil.switch.value");
  llvm::DenseMap<llvm::BasicBlock *, llvm::SmallVector<llvm::BasicBlock *, 4>> incoming;
  auto *test = origin;
  for (auto item : sw.cases()) {
    if (test != origin) builder.SetInsertPoint(test);
    auto *next = llvm::BasicBlock::Create(function->getContext(), "irveil.switch.next", function);
    auto *equal = builder.CreateICmpEQ(condition, item.getCaseValue(), "irveil.switch.equal");
    builder.CreateCondBr(equal, item.getCaseSuccessor(), next);
    incoming[item.getCaseSuccessor()].push_back(test);
    test = next;
  }
  if (test != origin) builder.SetInsertPoint(test);
  builder.CreateBr(sw.getDefaultDest());
  incoming[sw.getDefaultDest()].push_back(test);
  // One old predecessor may have several switch edges to the same destination.
  // Preserve edge multiplicity and its (necessarily identical) PHI value.
  for (auto &entry : incoming) {
    for (auto &phi : entry.first->phis()) {
      auto *value = phi.getIncomingValueForBlock(origin);
      for (int i = static_cast<int>(phi.getNumIncomingValues()) - 1; i >= 0; --i)
        if (phi.getIncomingBlock(i) == origin) phi.removeIncomingValue(i, false);
      for (auto *predecessor : entry.second) phi.addIncoming(value, predecessor);
    }
  }
  sw.eraseFromParent();
}
} // namespace

bool rewriteControlFlow(llvm::Function &function, const Config &config,
                        Statistics &statistics) {
  const auto mask = effectiveTransforms(config);
  if (!(mask & (CFG | Loops | Switches)) || !supported(function)) return false;
  struct Edge { llvm::BranchInst *branch; unsigned index; bool backedge; };
  llvm::SmallVector<Edge, 16> edges;
  llvm::SmallVector<llvm::SwitchInst *, 8> switches;
  // Build analysis from the current CFG and snapshot original terminators only.
  llvm::DominatorTree dominators(function);
  std::uint32_t cases = 0;
  for (auto &block : function) {
    if (auto *branch = llvm::dyn_cast<llvm::BranchInst>(block.getTerminator())) {
      if (branch->isConditional() && branch->getSuccessor(0) == branch->getSuccessor(1)) continue;
      for (unsigned i = 0; i < branch->getNumSuccessors(); ++i) {
        auto *target = branch->getSuccessor(i);
        const bool backedge = dominators.isReachableFromEntry(&block) && dominators.dominates(target, &block);
        if ((mask & (backedge ? Loops : CFG)) && edges.size() < config.maxEdgesPerFunction)
          edges.push_back({branch, i, backedge});
      }
    } else if (auto *sw = llvm::dyn_cast<llvm::SwitchInst>(block.getTerminator())) {
      if ((mask & Switches) && sw->getNumCases() <= config.maxSwitchCasesPerFunction - cases &&
          switches.size() < config.maxAddsPerFunction) {
        switches.push_back(sw);
        cases += sw->getNumCases();
      }
    }
  }
  for (auto edge : edges) {
    auto *from = edge.branch->getParent();
    auto *target = edge.branch->getSuccessor(edge.index);
    auto *route = llvm::BasicBlock::Create(function.getContext(),
        edge.backedge ? "irveil.loop.edge" : "irveil.cfg.edge", &function, target);
    auto *jump = llvm::BranchInst::Create(target, route);
    jump->setDebugLoc(edge.branch->getDebugLoc());
    edge.branch->setSuccessor(edge.index, route);
    for (auto &phi : target->phis()) phi.replaceIncomingBlockWith(from, route);
    if (edge.backedge) ++statistics.routedLoopEdges;
    else ++statistics.routedCFGEdges;
  }
  for (auto *sw : switches) lowerSwitch(*sw);
  statistics.loweredSwitches += switches.size();
  return !edges.empty() || !switches.empty();
}
} // namespace irveil
