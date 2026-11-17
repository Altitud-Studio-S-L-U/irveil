#include "DataTransform.h"
#include "Config.h"
#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/NoFolder.h"

namespace irveil {
bool encodeConstants(llvm::Function &function, const Config &config,
                     std::uint64_t seed, Statistics &statistics) {
  if (!(effectiveTransforms(config) & Constants)) return false;
  struct Operand { llvm::Instruction *instruction; unsigned index; llvm::ConstantInt *value; };
  llvm::SmallVector<Operand, 16> operands;
  // Snapshot before emission. PHIs, switches, GEP indices, intrinsics and calls
  // may require literals or edge-specific placement and are deliberately skipped.
  for (auto &block : function) {
    for (auto &instruction : block) {
      if (!llvm::isa<llvm::BinaryOperator, llvm::ICmpInst, llvm::ReturnInst>(&instruction)) continue;
      for (unsigned i = 0; i < instruction.getNumOperands(); ++i) {
        auto *value = llvm::dyn_cast<llvm::ConstantInt>(instruction.getOperand(i));
        if (value && value->getBitWidth() >= 2 && value->getBitWidth() <= 64 &&
            operands.size() < config.maxConstantsPerFunction)
          operands.push_back({&instruction, i, value});
      }
    }
  }
  for (auto operand : operands) {
    seed = seed * UINT64_C(6364136223846793005) + UINT64_C(1442695040888963407);
    const auto width = operand.value->getBitWidth();
    llvm::APInt key(width, seed);
    key.setBit(0); // Nonzero even at narrow widths.
    auto *type = operand.value->getType();
    auto *encoded = llvm::ConstantInt::get(type, operand.value->getValue() ^ key);
    llvm::IRBuilder<llvm::NoFolder> builder(operand.instruction);
    builder.SetCurrentDebugLocation(operand.instruction->getDebugLoc());
    auto *decoded = builder.CreateXor(encoded, llvm::ConstantInt::get(type, key), "irveil.constant");
    operand.instruction->setOperand(operand.index, decoded);
  }
  statistics.encodedConstants += operands.size();
  return !operands.empty();
}

namespace {
bool collectLoads(llvm::GlobalVariable &global,
                  const llvm::SmallPtrSetImpl<llvm::Function *> &eligible,
                  std::uint32_t limit,
                  llvm::SmallVectorImpl<llvm::LoadInst *> &loads) {
  llvm::SmallVector<llvm::Value *, 16> pending{&global};
  llvm::SmallPtrSet<llvm::Value *, 32> visited;
  while (!pending.empty()) {
    auto *pointer = pending.pop_back_val();
    if (!visited.insert(pointer).second) continue;
    for (auto *user : pointer->users()) {
      if (auto *load = llvm::dyn_cast<llvm::LoadInst>(user)) {
        if (load->getPointerOperand() != pointer || !load->getType()->isIntegerTy(8) ||
            load->isVolatile() || load->isAtomic() || !eligible.contains(load->getFunction())) return false;
        if (loads.size() == limit) return false;
        loads.push_back(load);
      } else if (auto *gep = llvm::dyn_cast<llvm::GetElementPtrInst>(user)) {
        if (gep->getPointerOperand() != pointer || !eligible.contains(gep->getFunction())) return false;
        pending.push_back(gep);
      } else if (auto *expression = llvm::dyn_cast<llvm::ConstantExpr>(user)) {
        if (expression->getOpcode() != llvm::Instruction::GetElementPtr ||
            expression->getOperand(0) != pointer) return false;
        pending.push_back(expression);
      } else {
        return false; // Escapes, aliases, stores, ptrtoint, PHIs and calls.
      }
    }
  }
  return !loads.empty();
}
} // namespace

void encodeStrings(llvm::Module &module, llvm::ArrayRef<llvm::Function *> functions,
                   const Config &config, Statistics &statistics) {
  if (!(effectiveTransforms(config) & Strings)) return;
  llvm::SmallPtrSet<llvm::Function *, 16> eligible(functions.begin(), functions.end());
  std::uint32_t remaining = config.maxStringBytesPerModule;
  std::uint32_t remainingLoads = config.maxStringLoadsPerModule;
  for (auto &global : module.globals()) {
    if (!remaining || !remainingLoads) break;
    if (!global.hasPrivateLinkage() || !global.isConstant() || !global.hasInitializer() ||
        global.isThreadLocal() || global.hasSection() || global.isExternallyInitialized() ||
        global.getAddressSpace() != 0 || global.getMetadata("irveil.encoded")) continue;
    auto *data = llvm::dyn_cast<llvm::ConstantDataArray>(global.getInitializer());
    if (!data || !data->isCString() || data->getNumElements() > remaining) continue;
    llvm::SmallVector<llvm::LoadInst *, 16> loads;
    // The complete global must fit: accepting only some readers would expose
    // encoded storage to the skipped readers. Do not mutate on budget failure.
    if (!collectLoads(global, eligible, remainingLoads, loads)) continue;
    // Seed and key are public diversification inputs, not encryption secrets.
    const auto key = static_cast<std::uint8_t>((config.seed ^ data->getNumElements()) | 1);
    llvm::SmallVector<std::uint8_t, 64> bytes;
    for (unsigned i = 0; i < data->getNumElements(); ++i)
      bytes.push_back(static_cast<std::uint8_t>(data->getElementAsInteger(i)) ^ key);
    global.setInitializer(llvm::ConstantDataArray::get(module.getContext(), bytes));
    global.setMetadata("irveil.encoded", llvm::MDNode::get(module.getContext(), {}));
    for (auto *load : loads) {
      llvm::IRBuilder<llvm::NoFolder> builder(load->getNextNode());
      builder.SetCurrentDebugLocation(load->getDebugLoc());
      auto *decoded = llvm::cast<llvm::Instruction>(builder.CreateXor(load,
          llvm::ConstantInt::get(load->getType(), key), "irveil.string.byte"));
      load->replaceAllUsesWith(decoded);
      decoded->setOperand(0, load);
      // A range about decoded bytes is not valid for encoded storage.
      load->setMetadata(llvm::LLVMContext::MD_range, nullptr);
      load->getFunction()->addFnAttr("irveil.processed");
    }
    remaining -= bytes.size();
    remainingLoads -= loads.size();
    ++statistics.encodedStrings;
    statistics.encodedStringBytes += bytes.size();
    statistics.decodedStringLoads += loads.size();
  }
}
} // namespace irveil
