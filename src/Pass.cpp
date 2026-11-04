#include "irveil/Pass.h"

#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/NoFolder.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdint>
#include <algorithm>
#include <system_error>

namespace irveil {
namespace {

constexpr llvm::StringLiteral ProcessedAttribute = "irveil.processed";

enum class AddIdentity { XorPropagate, OrPropagate };

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

llvm::SmallVector<llvm::BinaryOperator *, 16>
collectAdds(llvm::Function &function, std::uint32_t cap) {
  llvm::SmallVector<llvm::BinaryOperator *, 16> additions;
  for (llvm::BasicBlock &block : function) {
    for (llvm::Instruction &instruction : block) {
      auto *add = llvm::dyn_cast<llvm::BinaryOperator>(&instruction);
      if (!add || add->getOpcode() != llvm::Instruction::Add)
        continue;
      const auto *type = llvm::dyn_cast<llvm::IntegerType>(add->getType());
      if (!type || type->getBitWidth() < 2 || type->getBitWidth() > 64)
        continue;

      additions.push_back(add);
      if (additions.size() == cap)
        return additions;
    }
  }
  return additions;
}

unsigned prefixRounds(unsigned width) {
  unsigned rounds = 0;
  for (unsigned shift = 1; shift < width; shift <<= 1)
    ++rounds;
  return rounds;
}

unsigned emittedInstructions(unsigned width, AddIdentity identity) {
  return 5 * prefixRounds(width) + 4 +
         (identity == AddIdentity::OrPropagate ? 1 : 0);
}

llvm::Value *emitPrefixCarry(llvm::IRBuilder<llvm::NoFolder> &builder,
                            llvm::Value *left, llvm::Value *right,
                            AddIdentity identity) {
  const auto width = left->getType()->getIntegerBitWidth();
  llvm::Value *bits = builder.CreateXor(left, right, "irveil.bits");
  llvm::Value *propagate = identity == AddIdentity::OrPropagate
                               ? builder.CreateOr(left, right, "irveil.propagate")
                               : bits;
  llvm::Value *generate = builder.CreateAnd(left, right, "irveil.generate");
  for (unsigned shift = 1; shift < width; shift <<= 1) {
    auto *amount = llvm::ConstantInt::get(left->getType(), shift);
    llvm::Value *previous = builder.CreateShl(generate, amount, "irveil.previous");
    llvm::Value *through = builder.CreateAnd(propagate, previous, "irveil.through");
    generate = builder.CreateOr(generate, through, "irveil.generated");
    // The final propagate value is unused; reserve and emit only live stages.
    if ((shift << 1) < width) {
      llvm::Value *neighbor = builder.CreateShl(propagate, amount, "irveil.neighbor");
      propagate = builder.CreateAnd(propagate, neighbor, "irveil.propagated");
    }
  }
  llvm::Value *carry = builder.CreateShl(
      generate, llvm::ConstantInt::get(left->getType(), 1), "irveil.carry");
  return builder.CreateXor(bits, carry, "irveil.sum");
}

void rewriteAdd(llvm::BinaryOperator &add, AddIdentity identity) {
  // NoFolder keeps constant operands from collapsing the intended IR structure.
  // Fresh instructions deliberately inherit no nsw, nuw, exact or other flags.
  llvm::IRBuilder<llvm::NoFolder> builder(&add);
  builder.SetCurrentDebugLocation(add.getDebugLoc());

  // The identities duplicate their operands. Freeze once per original operand
  // so every generated use observes the same choice for an undef/poison value.
  llvm::Value *left = builder.CreateFreeze(add.getOperand(0), "irveil.left");
  llvm::Value *right = builder.CreateFreeze(add.getOperand(1), "irveil.right");
  llvm::Value *replacement = emitPrefixCarry(builder, left, right, identity);

  replacement->takeName(&add);
  add.replaceAllUsesWith(replacement);
  add.eraseFromParent();
}

} // namespace

llvm::Expected<Statistics> applyObfuscation(llvm::Module &module, Config config) {
  if (config.maxAddsPerFunction < 1 || config.maxAddsPerFunction > 4096)
    return llvm::createStringError(
        std::errc::invalid_argument,
        "IRVeil maxAddsPerFunction must be between 1 and 4096");
  if (config.maxInstructionsPerFunction < 9 ||
      config.maxInstructionsPerFunction > 36864)
    return llvm::createStringError(
        std::errc::invalid_argument,
        "IRVeil maxInstructionsPerFunction must be between 9 and 36864");

  Statistics statistics;
  auto functions = selectFunctions(module);
  statistics.selectedFunctions = functions.size();
  for (llvm::Function *function : functions) {
    if (function->hasFnAttribute(ProcessedAttribute))
      continue;

    // Snapshot only original candidates; generated adds cannot enter this run.
    auto additions = collectAdds(*function, config.maxAddsPerFunction);
    if (additions.empty())
      continue;

    std::uint64_t state = functionSeed(function->getName(), config.seed);
    std::uint32_t remaining = config.maxInstructionsPerFunction;
    std::uint64_t rewritten = 0;
    for (llvm::BinaryOperator *add : additions) {
      auto identity = (nextRandom(state) & 1) != 0
                          ? AddIdentity::XorPropagate
                          : AddIdentity::OrPropagate;
      // Equal defined operands have no XOR propagation. Expose that zero so
      // ordinary optimization can still reduce a+a to a single shift.
      if (add->getOperand(0) == add->getOperand(1))
        identity = AddIdentity::XorPropagate;
      const auto cost = emittedInstructions(add->getType()->getIntegerBitWidth(),
                                            identity);
      if (cost > remaining)
        continue;
      remaining -= cost;
      rewriteAdd(*add, identity);
      ++rewritten;
    }

    if (rewritten == 0)
      continue;
    function->addFnAttr(ProcessedAttribute);
    ++statistics.changedFunctions;
    statistics.rewrittenAdds += rewritten;
  }
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
                 << " max-instructions=" << config_.maxInstructionsPerFunction << '\n';
  return result->changedFunctions == 0 ? llvm::PreservedAnalyses::all()
                                       : llvm::PreservedAnalyses::none();
}

} // namespace irveil
