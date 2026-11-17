#include "irveil/Pass.h"
#include "InstructionTransform.h"
#include "Config.h"
#include "ControlFlowTransform.h"
#include "DataTransform.h"

#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdint>
#include <system_error>

namespace irveil {
namespace {

constexpr llvm::StringLiteral ProcessedAttribute = "irveil.processed";


llvm::SmallVector<llvm::Function *, 16>
selectFunctions(llvm::Module &module) {
  llvm::SmallVector<llvm::Function *, 16> selected;
  const auto *annotations = module.getNamedGlobal("llvm.global.annotations");
  if (!annotations || !annotations->hasInitializer())
    return selected;

  const auto *entries =
      llvm::dyn_cast<llvm::ConstantArray>(annotations->getInitializer());
  if (!entries)
    return selected;

  llvm::SmallPtrSet<llvm::Function *, 16> seen;
  for (const llvm::Use &operand : entries->operands()) {
    const auto *entry = llvm::dyn_cast<llvm::ConstantStruct>(operand.get());
    if (!entry || entry->getNumOperands() < 2)
      continue;

    auto *function = llvm::dyn_cast<llvm::Function>(
        entry->getOperand(0)->stripPointerCasts());
    const auto *textGlobal = llvm::dyn_cast<llvm::GlobalVariable>(
        entry->getOperand(1)->stripPointerCasts());
    if (!function || function->isDeclaration() || !textGlobal ||
        !textGlobal->hasInitializer())
      continue;

    const auto *text =
        llvm::dyn_cast<llvm::ConstantDataArray>(textGlobal->getInitializer());
    if (!text || text->getNumElements() != 7 || !text->isCString() ||
        text->getAsCString() != "irveil")
      continue;

    if (seen.insert(function).second)
      selected.push_back(function);
  }
  return selected;
}

// FNV-1a hashes the bytes of the LLVM function name, then the configured seed is
// XORed into that state. The cap only changes how many original adds are visited.
std::uint64_t functionSeed(llvm::StringRef name, std::uint64_t seed) {
  std::uint64_t hash = UINT64_C(14695981039346656037);
  for (unsigned char byte : name.bytes()) {
    hash ^= byte;
    hash *= UINT64_C(1099511628211);
  }
  return hash ^ seed;
}

// SplitMix64's low output bit selects an identity. This is reproducible mixing,
// not cryptography: the seed is not a secret or a security boundary.
std::uint64_t nextRandom(std::uint64_t &state) {
  state += UINT64_C(0x9e3779b97f4a7c15);
  std::uint64_t value = state;
  value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}

struct Candidate {
  llvm::Instruction *instruction;
  OperationKind kind;
};

llvm::SmallVector<Candidate, 16> collectCandidates(llvm::Function &function,
                                                    std::uint32_t cap, std::uint32_t transforms) {
  llvm::SmallVector<Candidate, 16> candidates;
  for (llvm::BasicBlock &block : function) {
    for (llvm::Instruction &instruction : block) {
      const auto kind = classifyInstruction(instruction, transforms);
      if (kind == OperationKind::Unsupported) continue;
      candidates.push_back({&instruction, kind});
      if (candidates.size() == cap) return candidates;
    }
  }
  return candidates;
}

} // namespace

llvm::Expected<Statistics> applyObfuscation(llvm::Module &module, Config config) {
  if (auto error = validateConfig(config)) return std::move(error);

  Statistics statistics;
  auto functions = selectFunctions(module);
  statistics.selectedFunctions = functions.size();
  llvm::SmallVector<llvm::Function *, 16> eligible;
  for (llvm::Function *function : functions) {
    if (function->hasFnAttribute(ProcessedAttribute))
      continue;
    eligible.push_back(function);

    // Snapshot only original candidates; generated adds cannot enter this run.
    auto candidates = collectCandidates(*function, config.maxAddsPerFunction,
                                        effectiveTransforms(config));
    std::uint64_t state = functionSeed(function->getName(), config.seed);
    // Encode original operands before arithmetic emission, never generated ones.
    const bool constantsChanged = encodeConstants(*function, config, state, statistics);
    for (const Candidate &candidate : candidates) {
      const auto selector = nextRandom(state);
      switch (candidate.kind) {
      case OperationKind::Add: ++statistics.rewrittenAdds; break;
      case OperationKind::Sub: ++statistics.rewrittenSubtracts; break;
      case OperationKind::Bitwise: ++statistics.rewrittenBitwise; break;
      case OperationKind::Comparison: ++statistics.rewrittenComparisons; break;
      case OperationKind::Branch: ++statistics.rewrittenBranches; break;
      case OperationKind::Unsupported: llvm_unreachable("Unsupported candidate");
      }
      rewriteInstruction(*candidate.instruction, candidate.kind, selector);
    }

    const bool controlChanged = rewriteControlFlow(*function, config, statistics);
    if (!candidates.empty() || controlChanged || constantsChanged) {
      function->addFnAttr(ProcessedAttribute);
    }
  }
  encodeStrings(module, eligible, config, statistics);
  for (auto *function : eligible)
    if (function->hasFnAttribute(ProcessedAttribute)) ++statistics.changedFunctions;
  return statistics;
}

llvm::PreservedAnalyses IRVeilPass::run(
    llvm::Module &module, llvm::ModuleAnalysisManager &) {
  auto result = applyObfuscation(module, config_);
  if (!result)
    llvm::report_fatal_error(llvm::Twine(llvm::toString(result.takeError())));
  if (report_)
    llvm::errs() << "IRVeil: module=" << module.getModuleIdentifier()
                 << " seed=" << config_.seed
                 << " max-adds=" << config_.maxAddsPerFunction
                 << " selected=" << result->selectedFunctions
                 << " changed=" << result->changedFunctions
                 << " rewritten-adds=" << result->rewrittenAdds
                 << " transforms=" << effectiveTransforms(config_)
                 << " sub=" << result->rewrittenSubtracts
                 << " bitwise=" << result->rewrittenBitwise
                 << " cmp=" << result->rewrittenComparisons
                 << " branches=" << result->rewrittenBranches
                 << " cfg-edges=" << result->routedCFGEdges
                 << " loop-edges=" << result->routedLoopEdges
                 << " switches=" << result->loweredSwitches
                 << " constants=" << result->encodedConstants
                 << " strings=" << result->encodedStrings
                 << " string-bytes=" << result->encodedStringBytes
                 << " decoded-string-loads=" << result->decodedStringLoads
                 << " max-edges=" << config_.maxEdgesPerFunction
                 << " max-switch-cases=" << config_.maxSwitchCasesPerFunction
                 << " max-constants=" << config_.maxConstantsPerFunction
                 << " max-string-bytes=" << config_.maxStringBytesPerModule
                 << " max-string-loads=" << config_.maxStringLoadsPerModule << '\n';
  return result->changedFunctions == 0 ? llvm::PreservedAnalyses::all()
                                       : llvm::PreservedAnalyses::none();
}

} // namespace irveil
